# preview_registry.py
from pathlib import Path
import sys, types, os
from django.apps import AppConfig, apps as global_apps
from django.apps.registry import Apps
from django.conf import settings
from django.core.management import call_command
from django.db import connections
import shutil
from io import StringIO
import logging
import json
from typing import Dict, List, Optional
import importlib
import datetime as dt

logger = logging.getLogger(__name__)

# disable Django's registry-ready guards
Apps.check_apps_ready   = lambda self: None
Apps.check_models_ready = lambda self: None

# Add a safe cache clearing function
def safe_clear_cache(apps_obj):
    """Safely clear the app cache without relying on app_config.get_models"""
    if not apps_obj or not hasattr(apps_obj, 'app_configs'):
        return
    
    # Clear app models cache directly
    if hasattr(apps_obj, '_get_models_cache'):
        apps_obj._get_models_cache.clear()
    
    # Set models_ready to True to prevent checks
    apps_obj.models_ready = True
    apps_obj.ready = True

class PreviewManager:
    """Manages preview environments for projects"""
    
    def __init__(self):
        self.preview_root = Path(settings.PREVIEW_ROOT)
        self.dynamic_apps_dir = self.preview_root / "dynamic_apps_preview"
        self.dynamic_apps_dir.mkdir(parents=True, exist_ok=True)
        self.active_previews: Dict[str, Dict] = {}

    def get_preview_path(self, project_id: int, change_id: Optional[int] = None, mode: str = "after") -> Path:
        """Get the path for a preview environment"""
        preview_name = f"preview_{project_id}"
        if change_id:
            preview_name += f"_{mode}_{change_id}"
        return self.dynamic_apps_dir / preview_name

    async def setup_preview(self, project_id: int, change_id: Optional[int] = None, 
                          mode: str = "after", files: Optional[Dict[str, str]] = None) -> str:
        """
        Set up a preview environment for a project
        
        Args:
            project_id: The project ID
            change_id: Optional change request ID
            mode: 'before' or 'after'
            files: Optional dict of file paths to contents for the preview
            
        Returns:
            Preview alias string
        """
        preview_path = self.get_preview_path(project_id, change_id, mode)
        preview_alias = preview_path.name
        
        # Clean up existing preview if it exists
        if preview_path.exists():
            shutil.rmtree(preview_path)
        
        # Create preview directory with all required subdirectories
        preview_path.mkdir(parents=True, exist_ok=True)
        (preview_path / "templates").mkdir(exist_ok=True)
        (preview_path / "static").mkdir(exist_ok=True)
        (preview_path / "migrations").mkdir(exist_ok=True)
        (preview_path / "migrations" / "__init__.py").write_text("")
        (preview_path / "__init__.py").write_text("")  # Root __init__.py
        
        # Create the parent dynamic_apps package if not exists
        dynamic_apps_path = Path(settings.BASE_DIR) / "dynamic_apps"
        dynamic_apps_path.mkdir(exist_ok=True)
        (dynamic_apps_path / "__init__.py").write_text("")  # Ensure it's a proper package

        # Set up sys.path if needed
        import sys
        if str(dynamic_apps_path) not in sys.path:
            sys.path.insert(0, str(dynamic_apps_path))
        
        # Copy project files
        await self._copy_project_files(project_id, preview_path)
        
        # Apply changes if provided
        if files:
            await self._apply_changes(preview_path, files)
            
        try:
            # Register the preview app
            module_path, cfg_label, cfg = register_preview_app(
                alias=preview_alias,
                app_label=f"project_{project_id}",
                app_path=preview_path
            )
            
            try:
                # Refresh Django's app registry
                refresh_registry_with_preview(module_path, cfg_label, cfg)
            except Exception as e:
                logger.error(f"Error refreshing app registry: {str(e)}")
                logger.error("App registry refresh failed, preview may not be fully functional")
            
            # Store preview info regardless of registry refresh success
            self.active_previews[preview_alias] = {
                'project_id': project_id,
                'change_id': change_id,
                'mode': mode,
                'path': str(preview_path),
                'module_path': module_path,
                'cfg_label': cfg_label
            }
        except Exception as e:
            logger.error(f"Error setting up preview environment: {str(e)}")
            logger.error("Continuing with file changes but preview may not be fully functional")
            # Still store basic preview info for the diff modal
            self.active_previews[preview_alias] = {
                'project_id': project_id,
                'change_id': change_id,
                'mode': mode,
                'path': str(preview_path)
            }
        
        return preview_alias

    async def _copy_project_files(self, project_id: int, preview_path: Path) -> None:
        """Copy project files to preview directory"""
        from create_api.models import Project, ModelFile, ViewFile, TemplateFile, StaticFile
        
        project = await Project.objects.aget(id=project_id)
        
        # Copy model files
        model_content = "from django.db import models\n\n"
        async for model in ModelFile.objects.filter(project=project):
            # Ensure model content has proper imports and Meta class setting app_label
            model_content_processed = self._process_model_content(
                model.content, 
                f"project_{project_id}"
            )
            model_content += model_content_processed
            
        self._write_file(preview_path / "models.py", model_content)
            
        # Copy view files
        view_content = "from django.shortcuts import render\nfrom django.http import HttpResponse\n\n"
        async for view in ViewFile.objects.filter(project=project):
            view_content += view.content + "\n\n"
            
        self._write_file(preview_path / "views.py", view_content)
            
        # Copy templates
        async for template in TemplateFile.objects.filter(project=project):
            self._write_file(preview_path / "templates" / template.path, template.content)
            
        # Copy static files
        async for static in StaticFile.objects.filter(project=project):
            self._write_file(preview_path / "static" / static.path, static.content)
            
    def _process_model_content(self, content: str, app_label: str) -> str:
        """
        Process model content to ensure it has proper app_label
        """
        # Check if each model has a Meta class with app_label
        import re
        
        # Find all model class definitions
        model_pattern = re.compile(r'class\s+(?P<model>\w+)\((?:models\.)?Model\):')
        
        result = []
        for line in content.split('\n'):
            # For each model class definition, ensure it has a Meta class with app_label
            match = model_pattern.match(line)
            if match:
                # Add the original class definition line
                result.append(line)
                # Add the Meta class if not already present
                result.append(f"    class Meta:")
                result.append(f"        app_label = '{app_label}'")
            else:
                result.append(line)
                
        return "\n".join(result)

    def _write_file(self, path: Path, content: str) -> None:
        """Write content to file, creating parent directories if needed"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    async def _apply_changes(self, preview_path: Path, files: Dict[str, str]) -> None:
        """Apply file changes to preview environment"""
        for file_path, content in files.items():
            full_path = preview_path / file_path
            self._write_file(full_path, content)

    def get_preview_info(self, preview_alias: str) -> Optional[Dict]:
        """Get information about a preview environment"""
        return self.active_previews.get(preview_alias)

    async def cleanup_preview(self, preview_alias: str) -> None:
        """Clean up a preview environment"""
        if preview_alias in self.active_previews:
            preview_info = self.active_previews[preview_alias]
            preview_path = Path(preview_info['path'])
            
            # Remove from Django's app registry
            if preview_info['cfg_label'] in global_apps.app_configs:
                del global_apps.app_configs[preview_info['cfg_label']]
            
            # Remove the preview directory
            if preview_path.exists():
                shutil.rmtree(preview_path)
            
            # Remove from active previews
            del self.active_previews[preview_alias]

# Create a global preview manager instance
preview_manager = PreviewManager()

def register_preview_app(alias: str, app_label: str, app_path: Path):
    """Register a preview app with Django"""
    logger.debug(f"Registering preview app: alias={alias}, app_label={app_label}")
    
    # Create a unique module path to avoid conflicts
    module_path = f"dynamic_apps.{alias}_{int(dt.datetime.now().timestamp())}"
    cfg_label = f"project_{app_label}_{alias}"
    
    # Create needed files for proper app structure
    # 1) Create __init__.py
    (app_path / "__init__.py").write_text("")
    
    # 2) Create apps.py with proper configuration
    apps_py_content = f"""
from django.apps import AppConfig

class Preview{alias.title().replace('_','')}Config(AppConfig):
    name = '{module_path}'
    label = '{cfg_label}'
    path = '{str(app_path).replace("\\\\", "/")}'
"""
    (app_path / "apps.py").write_text(apps_py_content)
    
    # 3) Ensure migrations directory exists with __init__.py
    migrations_dir = app_path / "migrations"
    migrations_dir.mkdir(exist_ok=True)
    (migrations_dir / "__init__.py").write_text("")
    
    # Create dummy module and register in sys.modules
    module = types.ModuleType(module_path)
    sys.modules[module_path] = module
    
    # Set the module's __file__ attribute to point to the directory
    module.__file__ = str(app_path / "__init__.py")
    
    # Import the app module to ensure Django can find it
    try:
        # Force reload of the module if it already exists
        if module_path in sys.modules:
            importlib.reload(sys.modules[module_path])
        else:
            importlib.import_module(module_path)
    except ModuleNotFoundError:
        # This is expected since we just created the module
        pass
    
    # Create app config using the same approach as dynamic apps
    ConfigClass = type(
        f"Preview{alias.title().replace('_','')}Config",
        (AppConfig,),
        {
            "name": module_path,
            "label": cfg_label,
            "path": str(app_path),
            "__module__": module_path,
            "ready": lambda self: None  # No-op ready method
        }
    )
    
    cfg = ConfigClass(module_path, module)
    # Explicitly set the path attribute again to ensure it's available
    cfg.path = str(app_path)
    logger.debug(f"Created AppConfig: {cfg} (label={cfg_label})")
    
    return module_path, cfg_label, cfg

def refresh_registry_with_preview(module_path: str, cfg_label: str, cfg: AppConfig) -> None:
    """Refresh Django's app registry with a preview app"""
    # 1) Register the module in INSTALLED_APPS if needed
    if module_path not in settings.INSTALLED_APPS:
        settings.INSTALLED_APPS.append(module_path)
        logger.debug(f"Added '{module_path}' to INSTALLED_APPS")

    # 2) Register the app config
    global_apps.app_configs[cfg_label] = cfg
    logger.debug(f"Injected preview config under '{cfg_label}'")

    # 3) Set up migration module path if needed
    if not hasattr(settings, "MIGRATION_MODULES"):
        settings.MIGRATION_MODULES = {}
    settings.MIGRATION_MODULES[cfg_label] = f"{module_path}.migrations"

    # 4) Reset Django's app registry state
    global_apps.ready = True
    global_apps.apps_ready = True
    global_apps.models_ready = True
    global_apps.loading = False
    
    # Use our safe cache clearing function instead of the direct call
    safe_clear_cache(global_apps)

    # 5) Force Django to reload apps with our new configuration
    try:
        from django.apps import apps
        apps.set_installed_apps(settings.INSTALLED_APPS)
        logger.debug(f"Registry now contains: {list(apps.app_configs.keys())}")
    except Exception as e:
        logger.error(f"Error refreshing app registry: {str(e)}")
        # Don't raise the exception, just log it to allow preview creation to continue
        logger.debug(f"Continuing preview setup despite app registry error")