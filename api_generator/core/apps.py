# core/apps.py
from django.apps import AppConfig

class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        # Install the DB→module importer
        from .db_importer import install
        install()
