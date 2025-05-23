# core/startup.py
import os
import importlib
from django.conf import settings
from django.apps import AppConfig, apps
from create_api.models import App as DBApp, ModelFile,SettingsFile, Project
import errno
from django.core.management import call_command
from django.db import connections
import textwrap
import re
import sys
from core.importer_local import importer_local

def dynamic_register_apps():
    db_alias = getattr(importer_local, 'db_alias', 'default')
    for db_app in DBApp.objects.using(db_alias).select_related("project"):
        pid = db_app.project.id
        name = db_app.name
        module = f"projects.project_{pid}.apps.{name}"
        label = f"project_{pid}_{name}"
        path = os.path.abspath(
            os.path.join("projects", f"project_{pid}", "apps", name)
        )

        # 1) Tell Django it's installed
        if module not in settings.INSTALLED_APPS:
            settings.INSTALLED_APPS.append(module)

        # 2) Import its module, capturing the real module object
        try:
            real_mod = importlib.import_module(module)
        except ModuleNotFoundError:
            print(f" ⚠️  Couldn't import {module}, skipping.")
            continue

        # 3) Build a minimal AppConfig subclass
        cfg_cls = type(
            f"DynamicAppConfig_{label}",
            (AppConfig,),
            {
                "__module__": __name__,
                "name": module,
                "label": label,
                "path": path,
            }
        )

        # 4) Instantiate & register it, passing the real module
        cfg = cfg_cls(module, real_mod)
        cfg.apps = apps
        cfg.models = {}  # prevent NoneType crashes
        apps.app_configs[label] = cfg

        print(f" ➕ Registered dynamic app: {label} → {module}")

    # 5) Clear Django's caches now that we've added apps
    apps.apps_ready = True
    apps.models_ready = True
    apps.clear_cache()

DYNAMIC_ROOT = settings.BASE_DIR / "dynamic_apps"


def dynamic_register_and_dump():
    """Dump each DB-defined app to disk with all reverse accessors disabled,
       register it as a filesystem app, and purge the original DB-loaded module."""
    db_alias = getattr(importer_local, 'db_alias', 'default')

    # Ensure the dynamic_apps package exists
    os.makedirs(DYNAMIC_ROOT, exist_ok=True)
    (DYNAMIC_ROOT / "__init__.py").write_text("")

    # Helper: inject related_name='+' on every FK/O2O
    fk_pattern = re.compile(
        r"^(?P<indent>\s*)(?P<name>\w+)\s*=\s*models\.(?P<type>ForeignKey|OneToOneField)\((?P<args>.*)\)$"
    )
    def inject_related_names(lines):
        out = []
        for ln in lines:
            m = fk_pattern.match(ln)
            if m:
                indent = m.group("indent")
                name   = m.group("name")
                ftype  = m.group("type")
                args   = m.group("args")
                # strip existing related_name, then force '+'
                args = re.sub(r"related_name\s*=\s*['\"].*?['\"]\s*,?", "", args)
                args = f"{args.rstrip(', ')}, related_name='+'"
                out.append(f"{indent}{name} = models.{ftype}({args})")
            else:
                out.append(ln)
        return out

    # Process each dynamic app from the DB
    for db_app in DBApp.objects.using(db_alias).select_related("project"):
        pid, name = db_app.project.id, db_app.name
        label     = f"project_{pid}_{name}"
        fs_module = f"dynamic_apps.{label}"
        fs_path   = DYNAMIC_ROOT / label

        # 1) Create package directory
        os.makedirs(fs_path, exist_ok=True)
        (fs_path / "__init__.py").write_text("")

        # 2) Write apps.py if missing
        apps_py = fs_path / "apps.py"
        if not apps_py.exists():
            apps_py.write_text(textwrap.dedent(f"""
                from django.apps import AppConfig

                class {name.capitalize()}Config(AppConfig):
                    name = '{fs_module}'
                    label = '{label}'
            """).lstrip())

        # 3) Dump & sanitize models.py
        try:
            mf = ModelFile.objects.using(db_alias).get(
                project_id=pid, app__name=name, path="models.py"
            )
            lines     = mf.content.splitlines()
            sanitized = inject_related_names(lines)
            (fs_path / "models.py").write_text("\n".join(sanitized))
        except ModelFile.DoesNotExist:
            (fs_path / "models.py").write_text("")

        # 4) Ensure migrations package
        mig = fs_path / "migrations"
        os.makedirs(mig, exist_ok=True)
        (mig / "__init__.py").write_text("")

        # 5) Register FS-app in INSTALLED_APPS
        if fs_module not in settings.INSTALLED_APPS:
            settings.INSTALLED_APPS.append(fs_module)

        # 5.5) Unload the DB-sourced modules so they're not double-imported
        sys.modules.pop(f"projects.project_{pid}.apps.{name}.models", None)
        sys.modules.pop(f"projects.project_{pid}.apps.{name}", None)

        # 6) Reload & relabel models in memory
        apps.app_configs.pop(label, None)
        try:
            mod = importlib.import_module(fs_module)
            auth_model = apps.get_model(settings.AUTH_USER_MODEL)
            for attr in dir(mod):
                cls = getattr(mod, attr)
                if isinstance(cls, type) and hasattr(cls, "_meta"):
                    cls._meta.app_label = label
                    cls._meta.db_table  = f"{label}_{cls._meta.model_name}"
                    # disable FK constraint on auth.User
                    for field in cls._meta.local_fields:
                        rf = getattr(field, "remote_field", None)
                        if rf and rf.model is auth_model:
                            field.db_constraint = False
                    # fix string-based relations to User
                    for field in cls._meta.get_fields():
                        rf = getattr(field, "remote_field", None)
                        if rf and isinstance(rf.model, str) and rf.model.endswith("User"):
                            rf.model = auth_model
        except ModuleNotFoundError:
            pass

        # 7) Register new AppConfig
        NewCfg = type(
            f"DynamicAppConfig_{label}",
            (AppConfig,),
            {"name": fs_module, "label": label, "path": str(fs_path)}
        )
        new_cfg = NewCfg(fs_module, mod if 'mod' in locals() else None)
        new_cfg.apps   = apps
        new_cfg.models = {}
        apps.app_configs[label] = new_cfg

    # 8) Clear Django app caches
    apps.apps_ready   = True
    apps.models_ready = True
    apps.clear_cache()

def dynamic_register_databases():
    """
    For each Project in the default DB:
      • Load its stored settings.py from the SettingsFile table
      • Exec it in isolation to extract its DATABASES dict
      • Deep-merge that 'default' over your main default DB cfg
      • Register as settings.DATABASES['project_<id>']
    """
    # Grab your real default DB conf once
    base_default = settings.DATABASES.get('default', {}).copy()

    for project in Project.objects.all():
        alias = f"project_{project.id}"
        if alias in settings.DATABASES:
            continue

        # 1) Fetch the DB-stored settings.py
        try:
            sf = SettingsFile.objects.get(project=project)
        except SettingsFile.DoesNotExist:
            print(f"⚠️  No SettingsFile for project {project.id}; skipping.")
            continue

        raw = sf.content

        # 2) Exec into a clean namespace (so __file__ and imports work)
        fake_path = os.path.join(settings.BASE_DIR, f"project_{project.id}_settings.py")
        ns = {"__file__": fake_path}
        exec(textwrap.dedent(raw), ns)

        proj_dbs = ns.get("DATABASES", {})
        if "default" not in proj_dbs:
            print(f"⚠️  Project {project.id} settings have no DATABASES['default']; skipping.")
            continue

        # 3) Merge your real default with the project's override
        merged = base_default.copy()
        merged.update(proj_dbs["default"])
        # Override the NAME so it's not the parent DB file
        from pathlib import Path
        parent_db = base_default.get("NAME")
        db_dir = Path(parent_db).parent
        merged["NAME"] = str(db_dir / f"{alias}.sqlite3")
        # 4) Register
        settings.DATABASES[alias] = merged
        print(f"🗄️  Registered '{alias}' → {merged.get('ENGINE')} @ {merged.get('NAME')}")



from django.db.backends.signals import connection_created
from django.dispatch import receiver
from django.db import connections
@receiver(connection_created)
def disable_fk_checks(sender, connection, **kwargs):
    """
    Turn off FK enforcement for all project_<id> connections.
    """
    alias = getattr(connection, 'alias', None)
    if alias and alias.startswith("project_"):
        connection.cursor().execute("PRAGMA foreign_keys = OFF;")

import threading
from django.core.management import call_command
from django.test import RequestFactory
from django.urls import reverse

from create_api.models import Project, AIChangeRequest
from create_api.views import preview_project_with_alias as preview_project
def run_preview_test(change, ai_diff_code=None):
    """Run a preview test for a change request"""
    # Clear import caches to avoid stale module issues (dynamic imports)
    importlib.invalidate_caches()
    
    preview_alias = f"preview_{change.project.id}_after_{change.id}"
    raw_label = change.app_name.split('_', 2)[2].lower() 
    
    # Ensure the raw_label is a valid Django app label (a Python identifier)
    if not raw_label.isidentifier():
        raise ValueError(f"Raw label must be a valid Python identifier: {raw_label!r}")
    
    # Log the label being used
    print(f"Using app label: {raw_label}")
    
    # Create a fake request
    factory = RequestFactory()
    request = factory.get('/')
    
    # Call preview_project with project_id, alias, and raw_label (plus ai_diff_code if given)
    return preview_project(request, change.project.id, preview_alias, raw_label, ai_diff_code=ai_diff_code)



from django.apps import apps
from django.db import models

def patch_dynamic_models():
    """
    For every app whose label starts with "project_<id>_":
      1) assign its models a db_table "<app_label>_<modelname>"
      2) inject a unique related_name/query_name for each FK
    """
    for cfg in apps.get_app_configs():
        if not cfg.label.startswith("project_"):
            continue

        for model in cfg.get_models():
            # 1) canonical table name
            model._meta.db_table = f"{cfg.label}_{model._meta.model_name}"

            # 2) unique reverse names on all FKs
            for field in model._meta.local_fields:
                if isinstance(field, models.ForeignKey):
                    rn = f"{model._meta.model_name}_{field.name}_set"
                    field.remote_field.related_name       = rn
                    field.remote_field.related_query_name = rn