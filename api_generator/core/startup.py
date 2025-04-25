import os
import importlib
from django.conf import settings
from django.apps import AppConfig, apps
from create_api.models import AppFile, ModelFile,SettingsFile, Project
import errno
from django.core.management import call_command
from django.db import connections
import textwrap


def dynamic_register_apps():
    from create_api.models import App as DBApp

    for db_app in DBApp.objects.select_related("project"):
        pid = db_app.project.id
        name = db_app.name
        module = f"projects.project_{pid}.apps.{name}"
        label = f"project_{pid}_{name}"
        path = os.path.abspath(
            os.path.join("projects", f"project_{pid}", "apps", name)
        )

        # 1) Tell Django it’s installed
        if module not in settings.INSTALLED_APPS:
            settings.INSTALLED_APPS.append(module)

        # 2) Import its module, capturing the real module object
        try:
            real_mod = importlib.import_module(module)
        except ModuleNotFoundError:
            print(f" ⚠️  Couldn’t import {module}, skipping.")
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

    # 5) Clear Django’s caches now that we’ve added apps
    apps.apps_ready = True
    apps.models_ready = True
    apps.clear_cache()


DYNAMIC_ROOT = settings.BASE_DIR / "dynamic_apps"


def dynamic_register_and_dump():
    # dump each DB-defined app to disk & register it as a filesystem app
    from create_api.models import App as DBApp

    # ensure dynamic_apps package
    os.makedirs(DYNAMIC_ROOT, exist_ok=True)
    (DYNAMIC_ROOT / "__init__.py").write_text("")

    for db_app in DBApp.objects.select_related("project"):
        pid, name = db_app.project.id, db_app.name
        label = f"project_{pid}_{name}"
        fs_module = f"dynamic_apps.{label}"
        fs_path = DYNAMIC_ROOT / label

        # write package
        os.makedirs(fs_path, exist_ok=True)
        (fs_path / "__init__.py").write_text("")

        # apps.py
        apps_py = fs_path / "apps.py"
        if not apps_py.exists():
            apps_py.write_text(f"""
from django.apps import AppConfig

class {name.capitalize()}Config(AppConfig):
    name = '{fs_module}'
    label = '{label}'
""".lstrip())

        # models.py from DB
        try:
            mf = ModelFile.objects.get(project_id=pid, app__name=name, path="models.py")
            (fs_path / "models.py").write_text(mf.content)
        except ModelFile.DoesNotExist:
            pass

        # migrations package
        mig = fs_path / "migrations"
        os.makedirs(mig, exist_ok=True)
        (mig / "__init__.py").write_text("")

        # register FS-app
        if fs_module not in settings.INSTALLED_APPS:
            settings.INSTALLED_APPS.append(fs_module)

        # replace old AppConfig
        apps.app_configs.pop(label, None)
        mod = importlib.import_module(fs_module)
        # re-label every model class in that module
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if isinstance(cls, type) and hasattr(cls, '_meta'):
                # Force the app_label to match our dynamic AppConfig.label
                cls._meta.app_label = label
                # Ensure the table name reflects the new app_label
                cls._meta.db_table = f"{label}_{cls._meta.model_name}"
                            # now disable DB FK constraint on any auth.User relations

                for field in cls._meta.local_fields:
                    rf = getattr(field, 'remote_field', None)
                    if rf and rf.model is auth_model:
                        field.db_constraint = False
    
                                # — now auto-fix any string-based relation targets —
                # — now auto-fix any string-based relation targets —
                # (we already have `apps` and `settings` from the module imports)
                auth_model = apps.get_model(settings.AUTH_USER_MODEL)
                for field in cls._meta.get_fields():
                    rf = getattr(field, 'remote_field', None)
                    tgt = getattr(rf, 'model', None)
                    if isinstance(tgt, str):
                        # try to resolve it; if it fails, and the name is "User", point at auth.User
                        try:
                            apps.get_model(tgt)
                        except LookupError:
                            if tgt.split('.')[-1] == 'User':
                                rf.model = auth_model


        NewCfg = type(f"DynamicAppConfig_{label}", (AppConfig,), {
            "name": fs_module, "label": label, "path": str(fs_path)
        })
        new_cfg = NewCfg(fs_module, mod)
        new_cfg.apps = apps
        new_cfg.models = {}
        apps.app_configs[label] = new_cfg

    # clear caches
    apps.apps_ready = True
    apps.models_ready = True
    apps.clear_cache()



# core/startup.py
from django.conf import settings


def dynamic_register_databases():
    """
    For each Project in the default DB:
      • Load its stored settings.py from the SettingsFile table
      • Exec it in isolation to extract its DATABASES dict
      • Deep-merge that 'default' over your main default DB cfg
      • Register as settings.DATABASES['project_<id>']
    """
    # grab your real default DB conf once
    base_default = settings.DATABASES.get('default', {}).copy()

    for project in Project.objects.all():
        alias = f"project_{project.id}"
        if alias in settings.DATABASES:
            continue

        # 1) fetch the DB-stored settings.py
        try:
            sf = SettingsFile.objects.get(project=project)
        except SettingsFile.DoesNotExist:
            print(f"⚠️  No SettingsFile for project {project.id}; skipping.")
            continue

        raw = sf.content

        # 2) exec into a clean namespace (so __file__ and imports work)
        fake_path = os.path.join(settings.BASE_DIR, f"project_{project.id}_settings.py")
        ns = {"__file__": fake_path}
        exec(textwrap.dedent(raw), ns)

        proj_dbs = ns.get("DATABASES", {})
        if "default" not in proj_dbs:
            print(f"⚠️  Project {project.id} settings have no DATABASES['default']; skipping.")
            continue

        # 3) merge your real default with the project’s override
        merged = base_default.copy()
        merged.update(proj_dbs["default"])
        # ── HERE: override the NAME so it’s not the parent DB file ──
        # assume base_default['NAME'] is a pathlib.Path or str to ".../db.sqlite3"
        from pathlib import Path
        parent_db = base_default.get("NAME")
        db_dir = Path(parent_db).parent
        merged["NAME"] = str(db_dir / f"{alias}.sqlite3")
        # 4) register
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
