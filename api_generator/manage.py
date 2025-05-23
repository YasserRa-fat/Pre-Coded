#!/usr/bin/env python
import os
import sys
# manage.py
# 1) point at your settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api_generator.settings")
sys.path.insert(0, os.path.dirname(__file__))

# 2) figure out which command is being run
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
print(">>> sys.argv:", sys.argv)
print(">>> cmd:", repr(cmd))

# 3) Early registration of databases and apps
import core.early as early
early.dynamic_register_databases_early()
early.dynamic_register_apps_early()

# 4) Bootstrap Django first
import django
django.setup()

# 5) Set up dynamic project environment
# 5.1) Install the DB importer
from core.db_importer import install as install_db_importer
install_db_importer()

# 5.2) Register databases
from core.startup import dynamic_register_databases
dynamic_register_databases()

# 5.3) Disable foreign‐key enforcement
from django.db import connections
for alias in list(connections):
    if alias.startswith("project_"):
        conn = connections[alias]
        conn.ensure_connection()
        conn.cursor().execute("PRAGMA foreign_keys = OFF;")

# 5.4) Register and dump apps
from core.startup import dynamic_register_apps, dynamic_register_and_dump
dynamic_register_apps()
dynamic_register_and_dump()

# 5.5) Set up migration modules
from django.conf import settings
from django.apps import apps as global_apps
settings.MIGRATION_MODULES = getattr(settings, "MIGRATION_MODULES", {})

# Register migration modules for all dynamic apps
for cfg in global_apps.get_app_configs():
    if cfg.label.startswith("project_"):
        module_path = f"dynamic_apps.{cfg.label}.migrations"
        settings.MIGRATION_MODULES[cfg.label] = module_path
        # Ensure the module exists in sys.modules
        try:
            __import__(module_path)
        except ImportError:
            import sys
            import types
            module = types.ModuleType(module_path)
            module.__path__ = [str(settings.BASE_DIR / "dynamic_apps" / cfg.label / "migrations")]
            sys.modules[module_path] = module

# 5.6) Patch login views
from core.patch_login_views import patch_dynamic_login_views
patch_dynamic_login_views()

# 5.7) Apply migrations and ensure they're properly recorded
from core.migration import auto_apply_migrations
auto_apply_migrations()

# 6) Hand off to Django's CLI
from django.core.management import execute_from_command_line
execute_from_command_line(sys.argv)
