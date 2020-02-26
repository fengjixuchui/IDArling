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
import json
import sqlite3

from .models import Group, Project, Database
from .packets import Default, DefaultEvent


class Storage(object):
    """
    This object is used to access the SQL database used by the server. It
    also defines some utility methods. Currently, only SQLite3 is implemented.
    """

    def __init__(self, dbpath):
        self._conn = sqlite3.connect(dbpath, check_same_thread=False)
        self._conn.isolation_level = None  # No need to commit
        self._conn.row_factory = sqlite3.Row  # Use Row objects

    def initialize(self):
        """Create all the default tables."""
        self._create(
            "groups",
            [
                "name text not null",
                "date text not null",
                "primary key (name)",
            ],
        )
        self._create(
            "projects",
            [
                "group_name text not null",
                "name text not null",
                "hash text not null",
                "file text not null",
                "type text not null",
                "date text not null",
                "foreign key(group_name) references groups(name)",
                "primary key (group_name, name)",
            ],
        )
        self._create(
            "databases",
            [
                "group_name text not null",
                "project text not null",
                "name text not null",
                "date text not null",
                "foreign key(group_name) references groups(name)",
                "foreign key(group_name, project) references projects(group_name, name)",
                "primary key(group_name, project, name)",
            ],
        )
        self._create(
            "events",
            [
                "group_name text not null",
                "project text not null",
                "database text not null",
                "tick integer not null",
                "dict text not null",
                "foreign key(group_name) references groups(name)",
                "foreign key(group_name, project) references projects(group_name, name)",
                "foreign key(group_name, project, database)"
                "     references databases(group_name, project, name)",
                "primary key(group_name, project, database, tick)",
            ],
        )

    def insert_group(self, group):
        """Insert a new group into the database."""
        self._insert("groups", Default.attrs(group.__dict__))

    def select_group(self, name):
        """Select the group with the given name."""
        objects = self.select_groups(name, 1)
        return objects[0] if objects else None

    def select_groups(self, name=None, limit=None):
        """Select the groups with the given name."""
        results = self._select("groups", {"name": name}, limit)
        return [Group(**result) for result in results]

    def insert_project(self, project):
        """Insert a new project into the database."""
        self._insert("projects", Default.attrs(project.__dict__))

    def select_project(self, name):
        """Select the project with the given name."""
        objects = self.select_projects(name, 1)
        return objects[0] if objects else None

    def select_projects(self, group=None, name=None, limit=None):
        """Select the projects with the given group and name."""
        results = self._select(
            "projects", {"group_name": group, "name": name}, limit
        )
        return [Project(**result) for result in results]

    def update_project_name(self, group=None, old_name=None, new_name=None, limit=None):
        """Update a project with the given new name."""
        self._update("projects", "name", new_name, {"group_name": group, "name": old_name}, limit)

    def update_database_project(self, group=None, old_name=None, new_name=None, limit=None):
        """Update a project with the given new name."""
        self._update("databases", "project", new_name, {"group_name": group, "project": old_name}, limit)

    def update_events_project(self, group=None, old_name=None, new_name=None, limit=None):
        """Update a project with the given new name."""
        self._update("events", "project", new_name, {"group_name": group, "project": old_name}, limit)

    def insert_database(self, database):
        """Insert a new database into the database."""
        attrs = Default.attrs(database.__dict__)
        attrs.pop("tick")
        self._insert("databases", attrs)

    def select_database(self, group, project, name):
        """Select the database with the given project and name."""
        objects = self.select_databases(group, project, name, 1)
        return objects[0] if objects else None

    def select_databases(self, group=None, project=None, name=None, limit=None):
        """Select the databases with the given project and name."""
        results = self._select(
            "databases", {"group_name": group, "project": project, "name": name}, limit
        )
        return [Database(**result) for result in results]

    def insert_event(self, client, event):
        """Insert a new event into the database."""
        dct = DefaultEvent.attrs(event.__dict__)
        self._insert(
            "events",
            {
                "group_name": client.group,
                "project": client.project,
                "database": client.database,
                "tick": event.tick,
                "dict": json.dumps(dct),
            },
        )

    def select_events(self, group, project, database, tick):
        """Get all events sent after the given tick count."""
        c = self._conn.cursor()
        sql = "select * from events where group_name = ? and project = ? and database = ?"
        sql += "and tick > ? order by tick asc;"
        c.execute(sql, [group, project, database, tick])
        events = []
        for result in c.fetchall():
            dct = json.loads(result["dict"])
            dct["tick"] = result["tick"]
            events.append(DefaultEvent.new(dct))
        return events

    def last_tick(self, group, project, database):
        """Get the last tick of the specified project and database."""
        c = self._conn.cursor()
        sql = "select tick from events where group_name = ? and project = ? and database = ? "
        sql += "order by tick desc limit 1;"
        c.execute(sql, [group, project, database])
        result = c.fetchone()
        return result["tick"] if result else 0

    def _create(self, table, cols):
        """Create a table with the given name and columns."""
        c = self._conn.cursor()
        sql = "create table if not exists {} ({});"
        c.execute(sql.format(table, ", ".join(cols)))

    def _select(self, table, fields, limit=None):
        """Select the rows of a table matching the given values."""
        c = self._conn.cursor()
        sql = "select * from {}".format(table)
        fields = {key: val for key, val in fields.items() if val}
        if len(fields):
            cols = ["{} = ?".format(col) for col in fields.keys()]
            sql = (sql + " where {}").format(" and ".join(cols))
        sql += " limit {};".format(limit) if limit else ";"
        c.execute(sql, list(fields.values()))
        return c.fetchall()

    def _update(self, table, field, new_value, search_fields, limit=None):
        """Update the field in a table matching the given search fields."""
        c = self._conn.cursor()
        sql = "update {} set {} = ?".format(table, field)
        search_fields = {key: val for key, val in search_fields.items() if val}
        if len(search_fields):
            cols = ["{} = ?".format(col) for col in search_fields.keys()]
            sql = (sql + " where {}").format(" and ".join(cols))
        sql += " limit {};".format(limit) if limit else ";"
        conditions = [new_value] + list(search_fields.values())
        #print(sql)
        #print(conditions)
        c.execute(sql, conditions)
        return c.fetchall()

    def _insert(self, table, fields):
        """Insert a row into a table with the given values."""
        c = self._conn.cursor()
        sql = "insert into {} ({}) values ({});"
        keys = ", ".join(fields.keys())
        vals = ", ".join(["?"] * len(fields))
        c.execute(sql.format(table, keys, vals), list(fields.values()))
