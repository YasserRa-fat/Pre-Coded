import sys
import importlib.abc
import importlib.util
import importlib.machinery
from django.apps import apps
import logging
import os

logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG to capture detailed logs
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)

# Function to sanitize content
def sanitize_content(content):
    return content.replace('\xa0', ' ')  # Replace non-breaking spaces with regular spaces

class DBModuleLoader(importlib.abc.Loader):
    def __init__(self, record):
        self.record = record

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        from django.apps import apps
        from django.db import models as dj_models
        from django.conf import settings

        # 1) Execute the raw source
        sanitized = sanitize_content(self.record.content)
        exec(sanitized, module.__dict__)

        # 2) Compute our dynamic app label
        label = f"project_{self.record.project_id}_{self.record.app.name}"

        # 3) Only relabel models *defined in* this module
        auth_model = apps.get_model(settings.AUTH_USER_MODEL)
        for attr in dir(module):
            cls = getattr(module, attr)
            if (
                isinstance(cls, type)
                and issubclass(cls, dj_models.Model)
                and cls is not dj_models.Model
                and cls.__module__ == module.__name__
            ):
                # a) relabel & rename the table
                cls._meta.app_label = label
                cls._meta.db_table   = f"{label}_{cls._meta.model_name}"

                # b) fix any string-based "User" → auth.User
                for field in cls._meta.get_fields():
                    rf = getattr(field, "remote_field", None)
                    if rf and isinstance(rf.model, str):
                        try:
                            apps.get_model(rf.model)
                        except LookupError:
                            if rf.model.rsplit(".", 1)[-1] == "User":
                                rf.model = auth_model

                # c) *turn off* the DB constraint for any FK/O2O to auth.User
                for field in cls._meta.local_fields:
                    rf = getattr(field, "remote_field", None)
                    if rf and rf.model is auth_model:
                        field.db_constraint = False

class DBModuleFinder(importlib.abc.MetaPathFinder):
    PREFIX = "projects"

    def find_spec(self, fullname, path, target=None):
        # -------------------------------------------------------------
        # If this is a migrations or templatetags module, skip DB loader
        # so Django’s normal filesystem importer can handle it.
        if "migrations" in fullname.split(".") or "templatetags" in fullname.split("."):
            return None

        parts = fullname.split(".")

        # Must start with projects prefix
        if not fullname.startswith(self.PREFIX):
            return None

        # Extract project_id from the module path
        if len(parts) < 2:
            return None

        tag = parts[1]
        if tag.isdigit():
            project_id = int(tag)  # Convert to integer
        elif tag.startswith("project_") and tag.split("_", 1)[1].isdigit():
            project_id = int(tag.split("_", 1)[1])  # Convert to integer
        else:
            return None

        # Handle app package initialization (__init__.py)
        if len(parts) >= 4 and parts[2] == "apps":
            app_name = parts[3]
            # Check for __init__.py files
            if len(parts) == 4 or (len(parts) > 4 and parts[4] == "__init__"):
                Model = apps.get_model("create_api", "AppFile")
                try:
                    # Try multiple possible paths
                    for init_path in [
                        f"{app_name}/__init__.py",
                        f"apps/{app_name}/__init__.py",
                        f"{app_name}/{app_name}/__init__.py",
                        f"__init__.py"
                    ]:
                        try:
                            # print(f"Trying to load __init__.py for app {app_name} with path {init_path}")
                            record = Model.objects.get(
                                project_id=project_id,
                                app__name=app_name,
                                path=init_path,
                            )
                            loader = DBModuleLoader(record)
                            spec = importlib.util.spec_from_loader(
                                fullname,
                                loader,
                                origin=f"db://{fullname}",
                                is_package=True
                            )
                            # Tell Python where to look for submodules of this package:
                            spec.submodule_search_locations = [os.path.dirname(record.path)]
                            return spec
                        except Model.DoesNotExist:
                            print(f"__init__.py not found for app {app_name} with path {init_path}")
                            continue
                    logging.debug(f"No __init__.py found for app {app_name}")
                except Exception as e:
                    logging.error(f"Error loading __init__.py for {app_name}: {e}")
                    return None

        # extract project_id (bare digit or `project_<digits>`)
        tag = parts[1]
        if tag.isdigit():
            project_id = tag
        elif tag.startswith("project_") and tag.split("_", 1)[1].isdigit():
            project_id = tag.split("_", 1)[1]
        else:
            return None

        # 1) `projects.project_<id>` as namespace
        if len(parts) == 2:
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = []
            return spec

        # 2) `projects.project_<id>.apps` as namespace
        if len(parts) == 3 and parts[2] == "apps":
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = []
            return spec

        # 3) `projects.project_<id>.apps.<app_name>` as namespace
        elif len(parts) == 4 and parts[2] == "apps":
            from create_api.models import App
            app_name = parts[3]
            # In case 3 of find_spec (handling apps.<app_name>):
            if App.objects.filter(project_id=project_id, name=app_name).exists():
                Model = apps.get_model("create_api", "AppFile")
                possible_paths = [
                    f"apps/{app_name}/__init__.py",
                    f"{app_name}/__init__.py",
                ]
                for init_path in possible_paths:
                    try:
                        record = Model.objects.get(
                            project_id=project_id,
                            app__name=app_name,
                            path=init_path,
                        )
                        loader = DBModuleLoader(record)
                        package_dir = os.path.dirname(record.path)
                        spec = importlib.util.spec_from_loader(
                            fullname,
                            loader,
                            origin=f"db://{fullname}",
                            is_package=True,
                        )
                        # Set submodule_search_locations to the parent directory of __init__.py
                        spec.submodule_search_locations = [package_dir]
                        return spec
                    except Model.DoesNotExist:
                        continue
                # Fallback to namespace package if no __init__.py found
                spec = importlib.machinery.ModuleSpec(
                    fullname,
                    loader=None,
                    is_package=True,
                )
                spec.submodule_search_locations = []
                return spec
            return None

        # 4) load actual modules from DB
        # a) project-level URLs: `projects.project_<id>.urls`
        if parts[2] == "urls" and len(parts) == 3:
            Model = apps.get_model("create_api", "URLFile")
            rel_path = "urls.py"
            filters = {"project_id": project_id, "app__isnull": True, "path": rel_path}

        # b) other project-level modules: `projects.project_<id>.<module>`
        elif len(parts) == 3:
            Model = apps.get_model("create_api", "ProjectFile")
            rel_path = f"{parts[2]}.py"
            filters = {"project_id": project_id, "path": rel_path}

        # c) app-level modules: `projects.project_<id>.apps.<app_name>.<...>`
        elif parts[2] == "apps" and len(parts) >= 4:
            app_name = parts[3]
            module_parts = parts[4:]
            possible_paths = [
                f"apps/{app_name}/{'/'.join(module_parts)}.py",
                f"{app_name}/{'/'.join(module_parts)}.py",
            ]
            # Check all relevant models for the submodule
            for model_name in ("ModelFile", "ViewFile", "FormFile", "URLFile", "AppFile"):
                Model = apps.get_model("create_api", model_name)
                for path in possible_paths:
                    try:
                        # print(f"Trying {model_name} for {path}")
                        record = Model.objects.get(
                            project_id=project_id,
                            app__name=app_name,
                            path=path,
                        )
                        loader = DBModuleLoader(record)
                        return importlib.util.spec_from_loader(
                            fullname,
                            loader,
                            origin=f"db://{fullname}",
                            is_package=False,  # Submodules are not packages
                        )
                    except Model.DoesNotExist:
                        continue
            logging.error(f"Module not found for {fullname} with paths: {possible_paths}")
            return None
        else:
            return None

        # Debugging: Print the filters being used
        print(f"Using filters: {filters}")
        logging.debug(f"Using filters: {filters}")
        # handle filters (cases a and b)
        try:
            record = Model.objects.get(**filters)
        except Model.DoesNotExist:
            logging.error(f"Module not found with filters: {filters}")
            return None

        loader = DBModuleLoader(record)
        return importlib.util.spec_from_loader(
            fullname,
            loader,
            origin=f"db://{fullname}"
        )

# module-level installer
def install():
    sys.meta_path.insert(0, DBModuleFinder())
