# core/migration.py

import importlib
from pathlib import Path

from django.apps import apps as global_apps
from django.conf import settings
from django.core.management import call_command
from django.db import connections, utils as db_utils

def auto_apply_migrations():
    # 1) Group dynamic apps by project ID
    projects = {}
    for cfg in global_apps.get_app_configs():
        if not cfg.label.startswith("project_"):
            continue
        pid = cfg.label.split("_", 2)[1]
        projects.setdefault(pid, []).append(cfg)

    # 2) For each project, run makemigrations + migrate + fallback
    for project_id, cfgs in projects.items():
        db_alias = f"project_{project_id}"

        # 2a) Ensure at least one migration file exists per app
        for cfg in cfgs:
            migrations_dir = Path(settings.BASE_DIR) / "dynamic_apps" / cfg.label / "migrations"
            if not any(migrations_dir.glob("00*.py")):
                call_command("makemigrations", cfg.label, interactive=False, verbosity=0)
        # 2b) Migrate all apps on this DB, faking any “initial” migrations
        #    whose tables already exist
        print(f"→ [project_{project_id}] migrating all apps on {db_alias} (fake_initial=True)")
        call_command(
            "migrate",
            database=db_alias,
            interactive=False,
            verbosity=1,
            fake_initial=True,
        )

        # 2c) Fallback: create any managed-model tables not yet created
        conn     = connections[db_alias]
        existing = set(conn.introspection.table_names())

        for cfg in cfgs:
            try:
                models_mod = importlib.import_module(f"{cfg.name}.models")
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
                    table = cls._meta.db_table
                    if table not in existing:
                        try:
                            with conn.schema_editor() as editor:
                                editor.create_model(cls)
                            existing.add(table)
                            print(f"↳ [project_{project_id}] fallback-created `{table}`")
                        except db_utils.OperationalError as e:
                            # If the table already exists, ignore and continue
                            if "already exists" in str(e):
                                print(f"⚠️ [project_{project_id}] skipped existing table `{table}`")
                                existing.add(table)
                            else:
                                # Re-raise unexpected OperationalErrors
                                raise