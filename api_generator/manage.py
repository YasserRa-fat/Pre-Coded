#!/usr/bin/env python
import os
import sys

# 1) point at your settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api_generator.settings")
sys.path.insert(0, os.path.dirname(__file__))

# 2) figure out which command is being run
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
print(">>> sys.argv:", sys.argv)
print(">>> cmd:", repr(cmd))

import core.early as early
early.dynamic_register_databases_early()
early.dynamic_register_apps_early()


# 3) Always bootstrap Django so management commands work
import django
django.setup()

# 4) If we’re *not* running a migration command, do all the dynamic‐project setup:
if cmd not in ("makemigrations", "migrate"):
    # 4.1) Install the DB importer for "projects.project_<id>.apps.X"
    from core.db_importer import install as install_db_importer
    install_db_importer()

    # 4.2) Register each Project’s database alias
    from core.startup import dynamic_register_databases
    dynamic_register_databases()

    # 4.3) Disable foreign‐key enforcement (SQLite pragma) on every project_<id> DB
    from django.db import connections
    for alias in list(connections):
        if alias.startswith("project_"):
            conn = connections[alias]
            conn.ensure_connection()
            conn.cursor().execute("PRAGMA foreign_keys = OFF;")

    # 4.4) Register apps stored in the DB (so INSTALLED_APPS now includes project_<id>_X)
    from core.startup import dynamic_register_apps
    print("🔧 Registering dynamic apps from DB…")
    dynamic_register_apps()

    # 4.5) Dump those apps to disk & re‐register as filesystem apps
    from core.startup import dynamic_register_and_dump
    print("💾 Dumping dynamic apps to disk…")
    dynamic_register_and_dump()

    # 4.6) Tell Django where each dynamic app’s migrations live
    from django.conf import settings
    from django.apps import apps as global_apps
    settings.MIGRATION_MODULES = getattr(settings, "MIGRATION_MODULES", {})
    for cfg in global_apps.get_app_configs():
        if cfg.label.startswith("project_"):
            settings.MIGRATION_MODULES[cfg.label] = f"dynamic_apps.{cfg.label}.migrations"

    # 4.7) Patch any dynamic login/register views
    from core.patch_login_views import patch_dynamic_login_views
    patch_dynamic_login_views()

    # 4.8) Finally, auto‐generate & apply migrations per project DB
    from core.migration import auto_apply_migrations
    print("🛠 Ensuring all dynamic-project migrations are applied…")
    auto_apply_migrations()

# 5) Hand off to Django’s CLI
from django.conf import settings
print("=== INSTALLED_APPS ===")
for app in settings.INSTALLED_APPS:
    print(" ", app)
    print("=== MIGRATION_MODULES ===", getattr(settings, "MIGRATION_MODULES", {}))
from django.core.management import execute_from_command_line
execute_from_command_line(sys.argv)
