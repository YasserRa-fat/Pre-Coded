# core/db_static.py

from django.contrib.staticfiles.finders import BaseFinder
from django.contrib.staticfiles.storage import StaticFilesStorage
from django.core.files.base import ContentFile
from create_api.models import StaticFile

class DatabaseStaticStorage(StaticFilesStorage):
    """
    Storage backend that reads StaticFile.file out of the DB.
    """
    def _open(self, name, mode='rb'):
        try:
            record = StaticFile.objects.get(path=name)
        except StaticFile.DoesNotExist:
            raise FileNotFoundError(f"No static file in DB for {name!r}")
        return record.file

    def exists(self, name):
        return StaticFile.objects.filter(path=name).exists()

class DatabaseStaticFinder(BaseFinder):
    """
    Finder that looks up every requested static path in the DB.
    """
    storage = DatabaseStaticStorage()

    def find(self, path, all=False):
        """
        Return the “path” if we have it in the DB, otherwise let other finders run.
        """
        if self.storage.exists(path):
            return [path] if all else path
        return [] if all else None

    def list(self, ignore_patterns):
        """
        Yield (path, path) for every DB record so runserver or collectstatic can see them.
        """
        for record in StaticFile.objects.all():
            yield record.path, record.path
