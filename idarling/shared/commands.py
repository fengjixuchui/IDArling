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
from .models import Group, Project, Database
from .packets import (
    Command,
    Container,
    DefaultCommand,
    ParentCommand,
    Query as IQuery,
    Reply as IReply,
)


class ListGroups(ParentCommand):
    __command__ = "list_groups"

    class Query(IQuery, DefaultCommand):
        pass

    class Reply(IReply, Command):
        def __init__(self, query, groups):
            super(ListGroups.Reply, self).__init__(query)
            self.groups = groups

        def build_command(self, dct):
            dct["groups"] = [group.build({}) for group in self.groups]

        def parse_command(self, dct):
            self.groups = [
                Group.new(group) for group in dct["groups"]
            ]


class ListProjects(ParentCommand):
    __command__ = "list_projects"

    class Query(IQuery, DefaultCommand):
        def __init__(self, group):
            super(ListProjects.Query, self).__init__()
            self.group = group

    class Reply(IReply, Command):
        def __init__(self, query, projects):
            super(ListProjects.Reply, self).__init__(query)
            self.projects = projects

        def build_command(self, dct):
            dct["projects"] = [project.build({}) for project in self.projects]

        def parse_command(self, dct):
            self.projects = [
                Project.new(project) for project in dct["projects"]
            ]


class ListDatabases(ParentCommand):
    __command__ = "list_databases"

    class Query(IQuery, DefaultCommand):
        def __init__(self, group, project):
            super(ListDatabases.Query, self).__init__()
            self.group = group
            self.project = project

    class Reply(IReply, Command):
        def __init__(self, query, databases):
            super(ListDatabases.Reply, self).__init__(query)
            self.databases = databases

        def build_command(self, dct):
            dct["databases"] = [
                database.build({}) for database in self.databases
            ]

        def parse_command(self, dct):
            self.databases = [
                Database.new(database) for database in dct["databases"]
            ]


class CreateGroup(ParentCommand):
    __command__ = "create_group"

    class Query(IQuery, Command):
        def __init__(self, group):
            super(CreateGroup.Query, self).__init__()
            self.group = group

        def build_command(self, dct):
            self.group.build(dct["group"])

        def parse_command(self, dct):
            self.group = Group.new(dct["group"])

    class Reply(IReply, Command):
        pass


class CreateProject(ParentCommand):
    __command__ = "create_project"

    class Query(IQuery, Command):
        def __init__(self, project):
            super(CreateProject.Query, self).__init__()
            self.project = project

        def build_command(self, dct):
            self.project.build(dct["project"])

        def parse_command(self, dct):
            self.project = Project.new(dct["project"])

    class Reply(IReply, Command):
        pass


class CreateDatabase(ParentCommand):
    __command__ = "create_database"

    class Query(IQuery, Command):
        def __init__(self, database):
            super(CreateDatabase.Query, self).__init__()
            self.database = database

        def build_command(self, dct):
            self.database.build(dct["database"])

        def parse_command(self, dct):
            self.database = Database.new(dct["database"])

    class Reply(IReply, Command):
        pass


class UpdateFile(ParentCommand):
    __command__ = "update_file"

    class Query(IQuery, Container, DefaultCommand):
        def __init__(self, group, project, database):
            super(UpdateFile.Query, self).__init__()
            self.group = group
            self.project = project
            self.database = database

    class Reply(IReply, Command):
        pass


class DownloadFile(ParentCommand):
    __command__ = "download_file"

    class Query(IQuery, DefaultCommand):
        def __init__(self, group, project, database):
            super(DownloadFile.Query, self).__init__()
            self.group = group
            self.project = project
            self.database = database

    class Reply(IReply, Container, Command):
        pass

class RenameProject(ParentCommand):
    __command__ = "rename_project"

    class Query(IQuery, DefaultCommand):
        def __init__(self, group, old_name, new_name):
            super(RenameProject.Query, self).__init__()
            self.group = group
            self.old_name = old_name
            self.new_name = new_name

    class Reply(IReply, Command):
        def __init__(self, query, projects, renamed):
            super(RenameProject.Reply, self).__init__(query)
            self.projects = projects
            self.renamed = renamed

        def build_command(self, dct):
            dct["renamed"] = self.renamed
            dct["projects"] = [project.build({}) for project in self.projects]

        def parse_command(self, dct):
            self.renamed = dct["renamed"]
            self.projects = [
                Project.new(project) for project in dct["projects"]
            ]

class JoinSession(DefaultCommand):
    __command__ = "join_session"

    def __init__(self, group, project, database, tick, name, color, ea, silent=True):
        super(JoinSession, self).__init__()
        self.group = group
        self.project = project
        self.database = database
        self.tick = tick
        self.name = name
        self.color = color
        self.ea = ea
        self.silent = silent


class LeaveSession(DefaultCommand):
    __command__ = "leave_session"

    def __init__(self, name, silent=True):
        super(LeaveSession, self).__init__()
        self.name = name
        self.silent = silent


class UpdateUserName(DefaultCommand):
    __command__ = "update_user_name"

    def __init__(self, old_name, new_name):
        super(UpdateUserName, self).__init__()
        self.old_name = old_name
        self.new_name = new_name


class UpdateUserColor(DefaultCommand):
    __command__ = "update_user_color"

    def __init__(self, name, old_color, new_color):
        super(UpdateUserColor, self).__init__()
        self.name = name
        self.old_color = old_color
        self.new_color = new_color


class UpdateLocation(DefaultCommand):
    __command__ = "update_location"

    def __init__(self, name, ea, color):
        super(UpdateLocation, self).__init__()
        self.name = name
        self.ea = ea
        self.color = color


class InviteToLocation(DefaultCommand):
    __command__ = "invite_to_location"

    def __init__(self, name, loc):
        super(InviteToLocation, self).__init__()
        self.name = name
        self.loc = loc
