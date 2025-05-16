# preview_registry.py
from pathlib import Path
import sys, types
from django.apps import AppConfig, apps as global_apps
from django.apps.registry import Apps
from django.conf import settings
from django.core.management import call_command
from django.db import connections
import shutil
from io import StringIO

# disable Django’s registry-ready guards
Apps.check_apps_ready   = lambda self: None
Apps.check_models_ready = lambda self: None


def register_preview_app(alias: str, app_label: str, app_path: Path):
    print(f"[DEBUG] register_preview_app(alias={alias!r}, app_label={app_label!r})")
    parts = app_label.split("_", 2)
    if parts[0] == "project" and parts[1].isdigit():
        raw_label = parts[2]
    else:
        raw_label = app_label
    """
    Build (but don’t yet register) an AppConfig for
    module "dynamic_apps.preview_<alias>.<app_label>" with label
    "project_<id>_<app_label>". Returns (module_path, cfg_label, cfg).
    """
    module_path = f"dynamic_apps.{alias}.{raw_label}"
    # stub parent package so it can be imported
    parent_pkg = f"dynamic_apps.{alias}"
    if parent_pkg not in sys.modules:
        pkg = types.ModuleType(parent_pkg)
        pkg.__path__ = [str(Path(settings.BASE_DIR) / "dynamic_apps" / alias)]
        sys.modules[parent_pkg] = pkg
    parts = alias.split("_", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise ValueError(f"Invalid alias format: {alias}")
    project_id  = alias.split("_",2)[1]
    cfg_label = f"project_{project_id}_{raw_label}"

    # dummy module for AppConfig
    module = types.ModuleType(module_path)
    sys.modules[module_path] = module

    def _model_fixes(self):
        from django.apps import apps as _apps
        from django.conf import settings as _settings
        auth_model = _apps.get_model(_settings.AUTH_USER_MODEL)
        for model in self.get_models():
            for field in model._meta.local_fields:
                rf = getattr(field, "remote_field", None)
                if rf and rf.model is auth_model:
                    field.db_constraint = False
            for field in model._meta.get_fields():
                rf = getattr(field, "remote_field", None)
                if rf and isinstance(rf.model, str) and rf.model.endswith("User"):
                    rf.model = auth_model

    ConfigClass = type(
        f"Preview{alias.title().replace('_','')}Config",
        (AppConfig,),
        {"name": module_path, "label": cfg_label, "path": str(app_path), "ready": _model_fixes}
    )
    cfg = ConfigClass(module_path, module)
    print(f"[DEBUG]  ↳ Created AppConfig: {cfg} (label={cfg.label!r})")
    return module_path, cfg_label, cfg

def refresh_registry_with_preview(module_path, cfg_label, cfg):
    # 1) Ensure the preview module path is declared
    if module_path not in settings.INSTALLED_APPS:
        settings.INSTALLED_APPS.append(module_path)
        print(f"[DEBUG] Added '{module_path}' to INSTALLED_APPS")

    # 2) Inject the preview AppConfig
    global_apps.app_configs[cfg_label] = cfg
    print(f"[DEBUG] injected preview cfg under '{cfg_label}'")

    # 3) Bypass guards so get_app_config() will work
    global_apps.ready        = True
    global_apps.apps_ready   = True
    global_apps.models_ready = True
    global_apps.loading      = False

    # 4) **Reset** the registry from INSTALLED_APPS
    print("[DEBUG] resetting global registry from INSTALLED_APPS…")
    from django.apps import apps
    apps.set_installed_apps(settings.INSTALLED_APPS)
    print(f"[DEBUG] registry now contains: {list(apps.app_configs.keys())}")