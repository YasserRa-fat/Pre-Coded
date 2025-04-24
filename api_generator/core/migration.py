# core/migration.py
import importlib
from django.apps import apps as global_apps
from django.core.management import call_command
from django.db import connections

def auto_apply_migrations():
    # 1) Make & run migrations for each dynamic app
    for cfg in global_apps.get_app_configs():
        if not cfg.label.startswith("project_"):
            continue

        # split into [“project”, “<id>”, “<appname>”]
        parts      = cfg.label.split("_", 2)
        project_id = parts[1]              # just the “1”
        db_alias   = f"project_{project_id}"

        print(f"→ [project_{project_id}] makemigrations for {cfg.label}")
        call_command("makemigrations", cfg.label, interactive=False, verbosity=0)

        print(f"→ [project_{project_id}] migrate {cfg.label} on {db_alias}")
        call_command("migrate", cfg.label, database=db_alias, interactive=False, verbosity=1)

        # 2) Now run all the built-in Django apps on that same DB
        for builtin in ("contenttypes", "auth", "sessions", "admin"):
            print(f"→ [project_{project_id}] migrate built-in '{builtin}' on {db_alias}")
            call_command("migrate", builtin, database=db_alias, interactive=False, verbosity=1)

    # 3) Fallback: create any model tables migrations missed
    for cfg in global_apps.get_app_configs():
        if not cfg.label.startswith("project_"):
            continue

        parts      = cfg.label.split("_", 2)
        project_id = parts[1]
        db_alias   = f"project_{project_id}"
        print(f"→ [project_{project_id}] makemigrations for {cfg.label}")
        call_command("makemigrations", cfg.label, interactive=False, verbosity=0)

        print(f"→ [project_{project_id}] migrate {cfg.label} on {db_alias}")
        call_command("migrate", cfg.label, database=db_alias, interactive=False, verbosity=1)
        conn       = connections[db_alias]
        existing   = set(conn.introspection.table_names())
        print(f"→ [project_{project_id}] existing tables: {existing}")

        for cfg2 in global_apps.get_app_configs():
            if not cfg2.label.startswith("project_"):
                continue

            try:
                models_mod = importlib.import_module(f"{cfg2.name}.models")
            except ModuleNotFoundError:
                continue

            for attr in dir(models_mod):
                cls = getattr(models_mod, attr)
                if (
                    isinstance(cls, type)
                    and hasattr(cls, "_meta")
                    and cls._meta.managed
                    and not cls._meta.auto_created
                ):
                    tbl = cls._meta.db_table
                    if tbl not in existing:
                        with conn.schema_editor() as editor:
                            editor.create_model(cls)
                        existing.add(tbl)
                        print(f"↳ [project_{project_id}] fallback-created `{tbl}`")
