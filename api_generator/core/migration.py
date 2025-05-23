# core/migration.py

import importlib
from pathlib import Path
import logging

from django.apps import apps as global_apps
from django.conf import settings
from django.core.management import call_command
from django.db import connections, utils as db_utils
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.executor import MigrationExecutor

logger = logging.getLogger(__name__)

def check_migration_plan():
    """Debug function to check Django's migration plan"""
    for alias in connections.databases:
        if not alias.startswith('project_'):
            continue
            
        connection = connections[alias]
        executor = MigrationExecutor(connection)
        loader = MigrationLoader(connection)
        
        # Get the migration plan
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        
        if plan:
            logger.info(f"Migration plan for {alias}:")
            for migration, backwards in plan:
                logger.info(f"  {'↓' if backwards else '↑'} {migration.app_label}.{migration.name}")
        else:
            logger.info(f"No migrations planned for {alias}")
            
        # Check if Django thinks any migrations are applied
        logger.info(f"Checking applied migrations in {alias}:")
        applied = loader.applied_migrations
        if isinstance(applied, dict):
            # Handle dict format
            for app_label, migrations in applied.items():
                if isinstance(app_label, str) and app_label.startswith('project_'):
                    logger.info(f"  {app_label}: {sorted(migrations)}")
        else:
            # Handle set format (tuples of (app_label, migration_name))
            by_app = {}
            for app_label, migration_name in applied:
                if app_label.startswith('project_'):
                    by_app.setdefault(app_label, set()).add(migration_name)
            for app_label, migrations in by_app.items():
                logger.info(f"  {app_label}: {sorted(migrations)}")
                
        # Also check the migration graph
        logger.info(f"Checking migration graph in {alias}:")
        for node in loader.graph.nodes.values():
            if node.app_label.startswith('project_'):
                applied_state = (node.app_label, node.name) in applied if isinstance(applied, set) else node.name in applied.get(node.app_label, set())
                logger.info(f"  {node.app_label}.{node.name} -> applied: {applied_state}")
                
        # Check if migrations table exists and has records
        recorder = MigrationRecorder(connection)
        table_name = recorder.Migration._meta.db_table
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            logger.info(f"Migration records in {table_name}: {count}")
            
            cursor.execute(f"SELECT app, name FROM {table_name} WHERE app LIKE 'project_%'")
            rows = cursor.fetchall()
            logger.info("Project migration records:")
            for app, name in rows:
                logger.info(f"  {app}.{name}")
                
        # Check migration history table structure
        logger.info(f"Checking django_migrations table structure in {alias}:")
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA table_info(django_migrations)")
            columns = cursor.fetchall()
            logger.info("Columns:")
            for col in columns:
                logger.info(f"  {col}")

def ensure_migration_records_match_files():
    """Ensure migration records in the database match the actual migration files"""
    for alias in connections.databases:
        if not alias.startswith('project_'):
            continue
            
        project_id = alias.split('_')[1]
        connection = connections[alias]
        recorder = MigrationRecorder(connection)
        
        # Get all recorded migrations
        applied = recorder.applied_migrations()
        logger.info(f"Checking migrations for {alias}")
        
        # Check each app's migrations
        for app in global_apps.get_app_configs():
            if not app.label.startswith(f'project_{project_id}_'):
                continue
                
            migrations_dir = Path(settings.BASE_DIR) / "dynamic_apps" / app.label / "migrations"
            if not migrations_dir.exists():
                continue
                
            # Get all migration files
            migration_files = set(f.stem for f in migrations_dir.glob("*.py") 
                               if f.stem != "__init__")
            
            # Get recorded migrations for this app
            app_migrations = {name for app_label, name in applied if app_label == app.label}
            
            logger.info(f"App {app.label}:")
            logger.info(f"  Files: {migration_files}")
            logger.info(f"  Applied: {app_migrations}")
            
            # Add missing records
            for migration in migration_files:
                if migration not in app_migrations:
                    logger.info(f"  Recording {migration} as applied")
                    recorder.record_applied(app.label, migration)
            
            # Remove extra records
            for migration in app_migrations:
                if migration not in migration_files:
                    logger.info(f"  Removing record for non-existent {migration}")
                    recorder.record_unapplied(app.label, migration)

def clean_migration_records(connection):
    """Clean up duplicate migration records and ensure proper registration"""
    cursor = connection.cursor()
    
    # First, get all project-related migrations
    cursor.execute("""
        SELECT app, name, MIN(id) as first_id, COUNT(*) as count
        FROM django_migrations 
        WHERE app LIKE 'project_%'
        GROUP BY app, name
        HAVING COUNT(*) > 1
    """)
    duplicates = cursor.fetchall()
    
    # Remove duplicates, keeping only the first occurrence
    for app, name, first_id, count in duplicates:
        logger.info(f"Cleaning up {count} duplicate records for {app}.{name}")
        cursor.execute(
            "DELETE FROM django_migrations WHERE app = :app AND name = :name AND id != :id",
            {"app": app, "name": name, "id": first_id}
        )
    
    connection.commit()

def auto_apply_migrations():
    # First clean up any duplicate migration records
    for alias in connections.databases:
        if alias.startswith('project_'):
            clean_migration_records(connections[alias])
    
    # Then ensure migration records match files
    ensure_migration_records_match_files()
    
    # Check Django's migration plan
    check_migration_plan()
    
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
                
            # Register migrations with Django
            migration_module = f"dynamic_apps.{cfg.label}.migrations"
            if hasattr(settings, 'MIGRATION_MODULES'):
                settings.MIGRATION_MODULES[cfg.label] = migration_module
            
            # Force Django to recognize migrations as applied
            recorder = MigrationRecorder(connections[db_alias])
            
            # Get all migration names from the migrations directory
            migration_files = [f.stem for f in migrations_dir.glob("*.py") if f.stem != "__init__"]
            for migration in migration_files:
                if migration != "__init__":
                    recorder.record_applied(cfg.label, migration)

        # 2b) Migrate all apps on this DB, faking any "initial" migrations
        print(f"→ [project_{project_id}] migrating all apps on {db_alias} (fake_initial=True)")
        try:
            # First try with --fake
            call_command(
                "migrate",
                database=db_alias,
                interactive=False,
                verbosity=1,
                fake=True,
            )
        except Exception as e:
            logger.error(f"Error faking migrations: {e}")
            # If faking fails, try normal migrate
            call_command(
                "migrate",
                database=db_alias,
                interactive=False,
                verbosity=1,
            )

        # 2c) Fallback: create any managed-model tables not yet created
        conn = connections[db_alias]
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