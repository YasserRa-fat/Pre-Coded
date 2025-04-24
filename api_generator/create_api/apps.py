# create_api/apps.py
from django.apps import AppConfig

class CreateApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'create_api'

    def ready(self):
        # This line makes sure Django registers your post_save handlers
        import create_api.signals  # noqa: F401
