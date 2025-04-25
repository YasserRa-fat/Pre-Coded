#!/usr/bin/env python
import os
import sys

# 1) point at your settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api_generator.settings")
sys.path.insert(0, os.path.dirname(__file__))

# 2) install your DB importer so "import projects.project_X.apps.Y" works
from core.db_importer import install as install_db_importer
install_db_importer()

# 3) bootstrap Django (now INSTALLED_APPS is still just the static ones)
import django
django.setup()
# 3.1) dynamic DB aliases
from core.startup import dynamic_register_databases
dynamic_register_databases()

# ─── Disable SQLite FK enforcement on each project_<id> DB ───
from django.db import connections
for alias in list(connections):
    if alias.startswith("project_"):
        # ensure the connection is open…
        conn = connections[alias]
        conn.ensure_connection()
        # then turn off FK checks
        conn.cursor().execute("PRAGMA foreign_keys = OFF;")


# 4) register DB-stored apps
from core.startup import dynamic_register_apps
print("🔧 Registering dynamic apps from DB…")
dynamic_register_apps()

# 4.1) dump & register FS apps
from core.startup import dynamic_register_and_dump
print("💾 Dumping dynamic apps to disk…")
dynamic_register_and_dump()
# ... after dynamic_register_and_dump()
from core.patch_login_views import patch_dynamic_login_views
patch_dynamic_login_views()
# now migrations, then runserver...

# 5) create any missing tables for those newly-registered apps
from core.migration import auto_apply_migrations
print("🛠 Ensuring all migrations are applied…")
auto_apply_migrations()

# 6) hand off to the normal Django CLI
from django.core.management import execute_from_command_line
execute_from_command_line(sys.argv)
