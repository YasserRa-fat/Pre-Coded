# core/services/file_indexer.py
import threading
from collections import defaultdict
from django.apps import apps
from create_api.models import (
    TemplateFile, ModelFile, ViewFile, FormFile,
    AppFile, ProjectFile, StaticFile
)

class FileIndexer:
    """
    On first import, builds an in-memory index:
      - mapping app_name → list of files
      - mapping keywords → list of file paths
    """
    _lock = threading.Lock()
    _loaded = False
    app_to_files = defaultdict(list)
    path_to_instance = {}

    @classmethod
    def load_index(cls, project_id):
        with cls._lock:
            if cls._loaded:
                return
            # only index this project
            for model in (TemplateFile, ModelFile, ViewFile, FormFile, AppFile, ProjectFile, StaticFile):
                qs = model.objects.filter(project_id=project_id)
                for f in qs:
                    cls.app_to_files[f.app.name if hasattr(f, 'app') and f.app else None].append(f.path)
                    cls.path_to_instance[f.path] = f
            cls._loaded = True

    @classmethod
    def get_candidates(cls, project_id, app_name=None):
        cls.load_index(project_id)
        # if app_name known, return those; else return all
        if app_name:
            return cls.app_to_files.get(app_name, [])
        # fall back to all file paths
        return list(cls.path_to_instance.keys())

    @classmethod
    def get_content(cls, path):
        inst = cls.path_to_instance.get(path)
        return inst.content if inst else ""
