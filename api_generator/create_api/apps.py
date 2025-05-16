# create_api/apps.py
from django.apps import AppConfig

class CreateApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'create_api'
    label = 'create_api'

    def __init__(self, app_name, app_module):
        super().__init__(app_name, app_module)
        self.models = {}

    def ready(self):
        # Ensure models is always a dictionary
        if self.models is None:
            self.models = {}
        # Import signals to register handlers
        import create_api.signals