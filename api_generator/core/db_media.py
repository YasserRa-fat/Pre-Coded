# core/db_media.py

from django.core.files.storage import FileSystemStorage
from django.conf import settings
from create_api.models import MediaFile, Project

class HybridMediaStorage(FileSystemStorage):
    """
    • Writes files under MEDIA_ROOT as usual.
    • Then upserts a matching MediaFile record with the correct project FK.
    """

    def _save(self, name, content):
        # 1) Save to disk
        saved_name = super()._save(name, content)

        # 2) Derive project from the path: expect "projects/<project_id>/…"
        project = None
        parts = name.split("/")  # ALWAYS forward-slash here
        if len(parts) >= 2 and parts[0] == "projects" and parts[1].isdigit():
            try:
                project = Project.objects.get(id=int(parts[1]))
            except Project.DoesNotExist:
                project = None

        # 3) Upsert the MediaFile record
        MediaFile.objects.update_or_create(
            path=name,
            defaults={
                "file": saved_name,
                "project": project,
            }
        )

        return saved_name

    def delete(self, name):
        # delete from disk
        super().delete(name)
        # delete from DB
        MediaFile.objects.filter(path=name).delete()
