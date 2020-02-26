# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
import logging
import os
import socket
import ssl
import threading

from .commands import (
    CreateGroup,
    CreateProject,
    CreateDatabase,
    DownloadFile,
    InviteToLocation,
    JoinSession,
    LeaveSession,
    ListGroups,
    ListProjects,
    ListDatabases,
    RenameProject,
    UpdateFile,
    UpdateLocation,
    UpdateUserColor,
    UpdateUserName,
)
from .discovery import ClientsDiscovery
from .packets import Command, Event
from .sockets import ClientSocket, ServerSocket
from .storage import Storage


class ServerClient(ClientSocket):
    """
    This class represents a client socket for the server. It implements all the
    handlers for the packet the client is susceptible to send.
    """

    def __init__(self, logger, parent=None):
        ClientSocket.__init__(self, logger, parent)
        self._group = None
        self._project = None
        self._database = None
        self._name = None
        self._color = None
        self._ea = None
        self._handlers = {}

    @property
    def group(self):
        return self._group

    @property
    def project(self):
        return self._project

    @property
    def database(self):
        return self._database

    @property
    def name(self):
        return self._name

    @property
    def color(self):
        return self._color

    @property
    def ea(self):
        return self._ea

    def wrap_socket(self, sock):
        ClientSocket.wrap_socket(self, sock)

        # Setup command handlers
        self._handlers = {
            ListGroups.Query: self._handle_list_groups,
            ListProjects.Query: self._handle_list_projects,
            ListDatabases.Query: self._handle_list_databases,
            CreateGroup.Query: self._handle_create_group,
            CreateProject.Query: self._handle_create_project,
            CreateDatabase.Query: self._handle_create_database,
            UpdateFile.Query: self._handle_upload_file,
            DownloadFile.Query: self._handle_download_file,
            RenameProject.Query: self._handle_rename_project,
            JoinSession: self._handle_join_session,
            LeaveSession: self._handle_leave_session,
            UpdateLocation: self._handle_update_location,
            InviteToLocation: self._handle_invite_to_location,
            UpdateUserName: self._handle_update_user_name,
            UpdateUserColor: self._handle_update_user_color,
        }

        # Add host and port as a prefix to our logger
        prefix = "%s:%d" % sock.getpeername()

        class CustomAdapter(logging.LoggerAdapter):
            def process(self, msg, kwargs):
                return "(%s) %s" % (prefix, msg), kwargs

        self._logger = CustomAdapter(self._logger, {})
        self._logger.info("Connected")

    def disconnect(self, err=None, notify=True):
        # Notify other users that we disconnected
        self.parent().reject(self)
        if self._group and self._project and self._database and notify:
            self.parent().forward_users(self, LeaveSession(self.name, False))
        ClientSocket.disconnect(self, err)
        self._logger.info("Disconnected")

    def recv_packet(self, packet):
        if isinstance(packet, Command):
            # Call the corresponding handler
            self._handlers[packet.__class__](packet)

        elif isinstance(packet, Event):
            if not self._group or not self._project or not self._database:
                self._logger.warning(
                    "Received a packet from an unsubscribed client"
                )
                return True

            # Check for de-synchronization
            tick = self.parent().storage.last_tick(
                self._group, self._project, self._database
            )
            if tick >= packet.tick:
                self._logger.warning("De-synchronization detected!")
                packet.tick = tick + 1

            # Save the event into the database
            self.parent().storage.insert_event(self, packet)
            # Forward the event to the other users
            self.parent().forward_users(self, packet)

            # Ask for a snapshot of the database if needed
            interval = self.parent().SNAPSHOT_INTERVAL
            if packet.tick and interval and packet.tick % interval == 0:

                def file_downloaded(reply):
                    file_name = "%s_%s_%s.idb" % (self._group, self._project, self._database)
                    file_path = self.parent().server_file(file_name)

                    # Write the file to disk
                    with open(file_path, "wb") as output_file:
                        output_file.write(reply.content)
                    self._logger.info("Auto-saved file %s" % file_name)

                d = self.send_packet(
                    DownloadFile.Query(self._group, self._project, self._database)
                )
                d.add_callback(file_downloaded)
                d.add_errback(self._logger.exception)
        else:
            return False
        return True

    def _handle_rename_project(self, query):
        self._logger.info("Got rename project request")
        projects = self.parent().storage.select_projects(query.group)
        for project in projects:
            if project.name == query.new_name:
                self._logger.error("Attempt to rename project to existing name")
                return

        # Grab the database lock. This basically means no other client can be
        # connected for a rename to occur.
        db_update_locked = False
        for project in projects:
            if project.name == query.old_name:
                self.parent().client_lock.acquire()
                # Only do the rename if we could lock the db. Otherwise we will
                # mess with other clients.
                db_update_locked = self.parent().db_update_lock.acquire(blocking=False)
                self.parent().client_lock.release()
                if db_update_locked:
                    self.parent().storage.update_project_name(query.group, query.old_name, query.new_name)
                    self.parent().storage.update_database_project(query.group, query.old_name, query.new_name)
                    self.parent().storage.update_events_project(query.group, query.old_name, query.new_name)

                    # We just changed the table entries so be sure to use new names 
                    # for queries
                    databases = self.parent().storage.select_databases(query.group, query.new_name)
                    for database in databases:
                        old_file_name = "%s_%s_%s.idb" % (query.group, query.old_name, database.name)
                        new_file_name = "%s_%s_%s.idb" % (query.group, query.new_name, database.name)
                        old_file_path = self.parent().server_file(old_file_name)
                        new_file_path = self.parent().server_file(new_file_name)
                        # If a rename happens before a file is uploaded, the 
                        # idb won't exist
                        if os.path.exists(old_file_path):
                            self._logger.info("Renaming: %s to %s" % (old_file_path, new_file_name))
                            os.rename(old_file_path, new_file_path)
                        else:
                            self._logger.warning("Skipping file rename due to non existing file: %s" % old_file_path)

                    self.parent().db_update_lock.release()
                else:
                    self._logger.info("Skipping rename due to database lock")

        # Resend an updated list of project names since it just changed
        projects = self.parent().storage.select_projects(query.group)
        self.send_packet(RenameProject.Reply(query, projects, db_update_locked))

    def _handle_list_groups(self, query):
        self._logger.info("Got list groups request")
        groups = self.parent().storage.select_groups()
        self.send_packet(ListGroups.Reply(query, groups))

    def _handle_list_projects(self, query):
        self._logger.info("Got list projects request")
        projects = self.parent().storage.select_projects(query.group)
        self.send_packet(ListProjects.Reply(query, projects))

    def _handle_list_databases(self, query):
        self._logger.info("Got list databases request")
        databases = self.parent().storage.select_databases(query.group, query.project)
        for database in databases:
            database_info = database.group_name, database.project, database.name
            file_name = "%s_%s_%s.idb" % (database_info)
            file_path = self.parent().server_file(file_name)
            if os.path.isfile(file_path):
                database.tick = self.parent().storage.last_tick(*database_info)
            else:
                database.tick = -1
        self.send_packet(ListDatabases.Reply(query, databases))

    def _handle_create_group(self, query):
        self.parent().storage.insert_group(query.group)
        self.send_packet(CreateGroup.Reply(query))

    def _handle_create_project(self, query):
        self.parent().storage.insert_project(query.project)
        self.send_packet(CreateProject.Reply(query))

    def _handle_create_database(self, query):
        self.parent().storage.insert_database(query.database)
        self.send_packet(CreateDatabase.Reply(query))

    def _handle_upload_file(self, query):
        database = self.parent().storage.select_database(
            query.group, query.project, query.database
        )
        file_name = "%s_%s_%s.idb" % (query.group, database.project, database.name)
        file_path = self.parent().server_file(file_name)

        # Write the file received to disk
        with open(file_path, "wb") as output_file:
            output_file.write(query.content)
        self._logger.info("Saved file %s" % file_name)
        self.send_packet(UpdateFile.Reply(query))

    def _handle_download_file(self, query):
        database = self.parent().storage.select_database(
            query.group, query.project, query.database
        )
        file_name = "%s_%s_%s.idb" % (query.group, database.project, database.name)
        file_path = self.parent().server_file(file_name)

        # Read file from disk and sent it
        reply = DownloadFile.Reply(query)
        with open(file_path, "rb") as input_file:
            reply.content = input_file.read()
        self._logger.info("Loaded file %s" % file_name)
        self.send_packet(reply)

    def _handle_join_session(self, packet):
        self._group = packet.group
        self._project = packet.project
        self._database = packet.database
        self._name = packet.name
        self._color = packet.color
        self._ea = packet.ea

        # Inform the other users that we joined
        packet.silent = False
        self.parent().forward_users(self, packet)

        # Inform ourselves about the other users
        for user in self.parent().get_users(self):
            self.send_packet(
                JoinSession(
                    packet.project,
                    packet.database,
                    packet.tick,
                    user.name,
                    user.color,
                    user.ea,
                )
            )

        # Send all missed events
        events = self.parent().storage.select_events(
            self._group, self._project, self._database, packet.tick
        )
        self._logger.debug("Sending %d missed events..." % len(events))
        for event in events:
            self.send_packet(event)
        self._logger.debug("Done sending %d missed events" % len(events))

    def _handle_leave_session(self, packet):
        # Inform others users that we are leaving
        packet.silent = False
        self.parent().forward_users(self, packet)

        # Inform ourselves that the other users leaved
        for user in self.parent().get_users(self):
            self.send_packet(LeaveSession(user.name))

        self._group = None
        self._project = None
        self._database = None
        self._name = None
        self._color = None

    def _handle_update_location(self, packet):
        self.parent().forward_users(self, packet)

    def _handle_invite_to_location(self, packet):
        def matches(other):
            return other.name == packet.name or packet.name == "everyone"

        packet.name = self._name
        self.parent().forward_users(self, packet, matches)

    def _handle_update_user_name(self, packet):
        # FXIME: ensure the name isn't already taken
        self._name = packet.new_name
        self.parent().forward_users(self, packet)

    def _handle_update_user_color(self, packet):
        self.parent().forward_users(self, packet)


class Server(ServerSocket):
    """
    This class represents a server socket for the server. It is used by both
    the integrated and dedicated server implementations. It doesn't do much.
    """

    SNAPSHOT_INTERVAL = 0  # ticks

    def __init__(self, logger, parent=None):
        ServerSocket.__init__(self, logger, parent)
        self._ssl = None
        self._clients = []

        # Initialize the storage
        self._storage = Storage(self.server_file("database.db"))
        self._storage.initialize()

        self._discovery = ClientsDiscovery(logger)
        # A temporory lock to stop clients while updating other locks
        self.client_lock = threading.Lock()
        # A long term lock that stops breaking database updates when multiple
        # clients are connected
        self.db_update_lock = threading.Lock()

    @property
    def storage(self):
        return self._storage

    @property
    def host(self):
        return self._socket.getsockname()[0]

    @property
    def port(self):
        return self._socket.getsockname()[1]

    def start(self, host, port=0, ssl_=None):
        """Starts the server on the specified host and port."""
        self._logger.info("Starting the server on %s:%d" % (host, port))

        # Load the system certificate chain
        self._ssl = ssl_
        if self._ssl:
            cert, key = self._ssl
            self._ssl = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self._ssl.load_cert_chain(certfile=cert, keyfile=key)

        # Create, bind and set the socket options
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except socket.error as e:
            self._logger.warning("Could not start the server")
            self._logger.exception(e)
            return False
        sock.settimeout(0)  # No timeout
        sock.setblocking(0)  # No blocking
        sock.listen(5)
        self.connect(sock)

        # Start discovering clients
        host, port = sock.getsockname()
        self._discovery.start(host, port, self._ssl)
        return True

    def stop(self):
        """Terminates all the connections and stops the server."""
        self._logger.info("Stopping the server")
        self._discovery.stop()
        # Disconnect all clients
        for client in list(self._clients):
            client.disconnect(notify=False)
        self.disconnect()
        try:
            self.db_update_lock.release()
        except RuntimeError:
            # It might not actually be locked
            pass
        return True

    def _accept(self, sock):
        """Called when an user connects."""
        client = ServerClient(self._logger, self)

        if self._ssl:
            # Wrap the socket in an SSL tunnel
            sock = self._ssl.wrap_socket(
                sock, server_side=True, do_handshake_on_connect=False
            )

        sock.settimeout(0)  # No timeout
        sock.setblocking(0)  # No blocking

        # If we already have at least one connection, lock the mutex that
        # prevents database updates like renaming. Connecting clients will
        # block until an existing blocking operation, like a porject rename, is
        # completed
        self.client_lock.acquire()
        if len(self._clients) == 1:
            self.db_update_lock.acquire()
        client.wrap_socket(sock)
        self._clients.append(client)
        self.client_lock.release()

    def reject(self, client):
        """Called when a user disconnects."""

        # Allow clients to update database again
        self.client_lock.acquire()
        self._clients.remove(client)
        if len(self._clients) <= 1:
            try:
                self.db_update_lock.release()
            except RuntimeError:
                pass

        self.client_lock.release()

    def get_users(self, client, matches=None):
        """Get the other users on the same database."""
        users = []
        for user in self._clients:
            if (
                user.project != client.project
                or user.database != client.database
            ):
                continue
            if user == client or (matches and not matches(user)):
                continue
            users.append(user)
        return users

    def forward_users(self, client, packet, matches=None):
        """Sends the packet to the other users on the same database."""
        for user in self.get_users(client, matches):
            user.send_packet(packet)

    def server_file(self, filename):
        """Get the absolute path of a local resource."""
        raise NotImplementedError("server_file() not implemented")
