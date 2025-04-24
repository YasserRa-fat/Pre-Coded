import os
import importlib
from django.conf import settings
from django.apps import AppConfig, apps
from create_api.models import AppFile, ModelFile
import errno
from django.core.management import call_command
from django.db import connections
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
def dynamic_register_databases():
    # copy default DB config for each Project → settings.DATABASES['project_<id>']
    from create_api.models import Project
    base = settings.BASE_DIR
    default_cfg = settings.DATABASES.get('default', {}).copy()
    for project in Project.objects.all():
        alias = f"project_{project.id}"
        if alias not in settings.DATABASES:
            new_cfg = default_cfg.copy()
            new_cfg.update({
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': base / f"{alias}.sqlite3",
            })
            settings.DATABASES[alias] = new_cfg
            print(f"🗄️ Registered database alias '{alias}' → {new_cfg['NAME']}")

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
    For each Project in the default DB, inject a
    settings.DATABASES['project_<id>'] entry (copying
    all the default-DB settings, including TIME_ZONE,
    CONN_HEALTH_CHECKS, etc.).
    """
    # Import inside the function so Django has been set up
    from create_api.models import Project

    base = settings.BASE_DIR
    default_cfg = settings.DATABASES.get('default', {}).copy()

    for project in Project.objects.all():
        alias = f"project_{project.id}"
        if alias not in settings.DATABASES:
            # Copy default settings, then override
            new_cfg = default_cfg.copy()
            new_cfg.update({
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': base / f"{alias}.sqlite3",
            })
            settings.DATABASES[alias] = new_cfg
            print(f"🗄️  Registered database alias '{alias}' → {new_cfg['NAME']}")

from django.db.backends.signals import connection_created
from django.dispatch import receiver

@receiver(connection_created)
def disable_fk_checks(sender, connection, **kwargs):
    # sender is the backend module, connection.alias is the DB alias
    alias = getattr(connection, 'alias', None)
    if alias and alias.startswith("project_"):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys = OFF;")