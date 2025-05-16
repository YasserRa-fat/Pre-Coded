import sys
import importlib.abc
import importlib.util
import importlib.machinery
from django.apps import apps
import logging
import os
from core.importer_local import importer_local

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

def sanitize_content(content):
    return content.replace('\xa0', ' ')

class DBModuleLoader(importlib.abc.Loader):
    def __init__(self, record):
        self.record = record

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        from django.db import models as dj_models
        from django.conf import settings

        raw = self.record.content.replace('\xa0', ' ')
        import re
        def strip_reverse_accessors(code):
            pattern = re.compile(r"""
                (?P<prefix>\w+\s*=\s*models\.
                    (ForeignKey|OneToOneField)\(
                )
                (?P<args>.*?)
                \)
            """, re.VERBOSE)
            def replacer(m):
                args = re.sub(r"related_name\s*=\s*['\"].*?['\"]\s*,?", "", m.group("args"))
                return f"{m.group('prefix')}{args.rstrip(', ')}, related_name='+' )"
            return pattern.sub(replacer, code)

        sanitized = strip_reverse_accessors(raw)
        exec(sanitized, module.__dict__)
        label = f"project_{self.record.project_id}_{self.record.app.name}"

        for attr in dir(module):
            cls = getattr(module, attr)
            if (
                isinstance(cls, type)
                and issubclass(cls, dj_models.Model)
                and cls is not dj_models.Model
                and cls.__module__ == module.__name__
            ):
                for field in cls._meta.local_fields:
                    if isinstance(field, (dj_models.ForeignKey, dj_models.OneToOneField)):
                        field.remote_field.related_name = '+'
                        field.remote_field.related_query_name = None

        auth_model = apps.get_model(settings.AUTH_USER_MODEL)
        for attr in dir(module):
            cls = getattr(module, attr)
            if (
                isinstance(cls, type)
                and issubclass(cls, dj_models.Model)
                and cls is not dj_models.Model
                and cls.__module__ == module.__name__
            ):
                cls._meta.app_label = label
                cls._meta.db_table = f"{label}_{cls._meta.model_name}"
                origin = getattr(module.__spec__, 'origin', '') or ''
                if origin.startswith('db://'):
                    real = os.path.join(settings.BASE_DIR, "dynamic_apps")
                    if real not in sys.path:
                        sys.path.insert(0, real)
                    app_config = apps.get_app_config(label)
                    if cls._meta.model_name not in app_config.models:
                        try:
                            apps.register_model(label, cls)
                        except RuntimeError:
                            pass
                for field in cls._meta.get_fields():
                    rf = getattr(field, "remote_field", None)
                    if rf and isinstance(rf.model, str):
                        try:
                            apps.get_model(rf.model)
                        except LookupError:
                            if rf.model.rsplit(".", 1)[-1] == "User":
                                rf.model = auth_model
                for field in cls._meta.local_fields:
                    rf = getattr(field, "remote_field", None)
                    if rf and rf.model is auth_model:
                        field.db_constraint = False

class DBModuleFinder(importlib.abc.MetaPathFinder):
    PREFIX = "projects"

    def _get_db_app_names(self, project_id):
        from create_api.models import App
        return set(App.objects.filter(project_id=project_id).values_list("name", flat=True))
    
    def find_spec(self, fullname, path, target=None):
        # Prevent model loading during app registry population
        if getattr(importer_local, 'populating', False):
            logging.debug(f"Skipping find_spec for {fullname} during app registry population")
            return None

        db_alias = getattr(importer_local, 'db_alias', 'default')
        if "migrations" in fullname.split(".") or "templatetags" in fullname.split("."):
            return None
        if fullname in sys.modules:
            return None
        parts = fullname.split(".")
        if not fullname.startswith(self.PREFIX):
            return None
        if len(parts) < 2:
            return None

        tag = parts[1]
        if tag.isdigit():
            project_id = int(tag)
        elif tag.startswith("project_") and tag.split("_", 1)[1].isdigit():
            project_id = int(tag.split("_", 1)[1])
        else:
            return None

        if len(parts) >= 4 and parts[2] == "apps":
            app_name = parts[3]
            if len(parts) == 4 or (len(parts) > 4 and parts[4] == "__init__"):
                Model = apps.get_model("create_api", "AppFile")
                for init_path in [
                    f"{app_name}/__init__.py",
                    f"apps/{app_name}/__init__.py",
                    f"{app_name}/{app_name}/__init__.py",
                    f"__init__.py"
                ]:
                    try:
                        record = Model.objects.using(db_alias).get(
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
                        spec.submodule_search_locations = [os.path.dirname(record.path)]
                        return spec
                    except Model.DoesNotExist:
                        continue
                logging.debug(f"No __init__.py found for app {app_name}")
                return None

        if len(parts) == 2:
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = []
            return spec

        if len(parts) == 3 and parts[2] == "apps":
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = []
            return spec

        elif len(parts) == 4 and parts[2] == "apps":
            from create_api.models import App
            app_name = parts[3]
            if App.objects.filter(project_id=project_id, name=app_name).exists():
                Model = apps.get_model("create_api", "AppFile")
                possible_paths = [
                    f"apps/{app_name}/__init__.py",
                    f"{app_name}/__init__.py",
                ]
                for init_path in possible_paths:
                    try:
                        record = Model.objects.using(db_alias).get(
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
                        spec.submodule_search_locations = [package_dir]
                        return spec
                    except Model.DoesNotExist:
                        continue
                spec = importlib.machinery.ModuleSpec(
                    fullname,
                    loader=None,
                    is_package=True,
                )
                spec.submodule_search_locations = []
                return spec
            return None

        if parts[2] == "urls" and len(parts) == 3:
            Model = apps.get_model("create_api", "URLFile")
            rel_path = "urls.py"
            filters = {"project_id": project_id, "app__isnull": True, "path": rel_path}
            try:
                record = Model.objects.using(db_alias).get(**filters)
                loader = DBModuleLoader(record)
                return importlib.util.spec_from_loader(
                    fullname,
                    loader,
                    origin=f"db://{fullname}"
                )
            except Model.DoesNotExist:
                logging.error(f"Module not found with filters: {filters}")
                return None

        elif len(parts) == 3:
            Model = apps.get_model("create_api", "ProjectFile")
            rel_path = f"{parts[2]}.py"
            filters = {"project_id": project_id, "path": rel_path}
            try:
                record = Model.objects.using(db_alias).get(**filters)
                loader = DBModuleLoader(record)
                return importlib.util.spec_from_loader(
                    fullname,
                    loader,
                    origin=f"db://{fullname}"
                )
            except Model.DoesNotExist:
                logging.error(f"Module not found with filters: {filters}")
                return None

        elif (
            (parts[2] == "apps" and len(parts) >= 4)
            or (len(parts) >= 4 and parts[2] in self._get_db_app_names(project_id))
        ):
            if parts[2] == "apps":
                app_name, module_parts = parts[3], parts[4:]
            else:
                app_name, module_parts = parts[2], parts[3:]
            possible_paths = [
                f"{'/'.join(module_parts)}.py",
                f"{app_name}/{'/'.join(module_parts)}.py",
                f"apps/{app_name}/{'/'.join(module_parts)}.py",
            ]
            for model_name in ("ModelFile", "ViewFile", "FormFile", "URLFile", "AppFile"):
                Model = apps.get_model("create_api", model_name)
                for path in possible_paths:
                    try:
                        record = Model.objects.using(db_alias).get(
                            project_id=project_id,
                            app__name=app_name,
                            path=path,
                        )
                        loader = DBModuleLoader(record)
                        return importlib.util.spec_from_loader(
                            fullname,
                            loader,
                            origin=f"db://{fullname}",
                            is_package=False,
                        )
                    except Model.DoesNotExist:
                        continue
            logging.error(f"Module not found for {fullname} with paths: {possible_paths}")
            return None
        return None

def install():
    sys.meta_path.insert(0, DBModuleFinder())