# core/apps.py
from django.apps import AppConfig

class CoreConfig(AppConfig):
    name = 'core'

def ready(self):
        from core.db_importer import install as _install_db_finder
        _install_db_finder()
        from django.conf import settings
        try:
            from create_api.models import Project
            for proj in Project.objects.all():
                alias = f"project_{proj.pk}"
                if alias in settings.DATABASES:
                    continue
                settings.DATABASES[alias] = {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': settings.BASE_DIR / f"{alias}.sqlite3",
                }
        except Exception:
            # Skip ORM operations if database is not ready (e.g., during ASGI startup)
            pass
