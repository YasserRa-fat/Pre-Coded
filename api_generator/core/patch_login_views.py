# core/patch_login_views.py

import inspect
import importlib
from django.apps import apps
from django.contrib.auth.views import LoginView
from django.contrib import messages

def patch_dynamic_login_views():
    """
    Find every project_*/apps/*/views.py LoginView subclass
    and replace its form_invalid with one that:
      • Adds a friendly error message
      • Delegates to super().form_invalid(form)
    """
    for cfg in apps.get_app_configs():
        if not cfg.label.startswith("project_"):
            continue

        views_mod_name = f"{cfg.name}.views"
        try:
            mod = importlib.import_module(views_mod_name)
        except ImportError:
            continue

        for name, cls in vars(mod).items():
            if (
                inspect.isclass(cls)
                and issubclass(cls, LoginView)
                and cls is not LoginView
            ):
                # make a fresh form_invalid that captures cls in its closure
                def make_form_invalid(cls):
                    def form_invalid(self, form):
                        messages.error(self.request, "Invalid username or password")
                        return super(cls, self).form_invalid(form)
                    return form_invalid

                cls.form_invalid = make_form_invalid(cls)
