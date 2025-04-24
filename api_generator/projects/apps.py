

from django.apps import AppConfig

class ProjectsConfig(AppConfig):
    # this is the *module path* Django will import for the app:
    name  = "projects"
    # this is the internal label Django will use
    label = "projects"