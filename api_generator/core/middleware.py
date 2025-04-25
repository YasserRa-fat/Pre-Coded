# core/middleware.py

import inspect
import re
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.views.generic import FormView
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY


class ProjectDBMiddleware:
    """
    Reads /projects/<id>/ from the URL and sets request.project_db_alias.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        parts = request.path_info.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "projects" and parts[1].isdigit():
            request.project_db_alias = f"project_{parts[1]}"
        else:
            request.project_db_alias = "default"
        return self.get_response(request)


class PatchRegisterAndLoginMiddleware:
    """
    1) Monkey-patch the DB-loaded RegisterView so it sets user.backend before login().
    2) Patch any FormView+UserCreationForm to write into project DB and stash alias.
    3) Patch LoginView to authenticate against project DB, stash alias, fix recursion,
       and redirect under /projects/<id>/.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        # 1) Determine the project_<id> alias
        alias = getattr(request, "project_db_alias", "default")
        request.project_db_alias = alias

        view_cls = getattr(view_func, "view_class", None)

        # ── Monkey-patch the stored RegisterView itself ──
        if inspect.isclass(view_cls) and view_cls.__name__ == "RegisterView":
            orig_form_valid = view_cls.form_valid

            def form_valid(self, form):
                # *create* user via the stored code’s form.save()
                user = form.save()
                if user:
                    # tell Django which backend we’re using:
                    user.backend = 'django.contrib.auth.backends.ModelBackend'
                    login(self.request, user)
                    # record session keys for our session-auth middleware
                    request.session[SESSION_KEY] = str(user.pk)
                    request.session[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
                    request.session['project_db_alias'] = alias
                return orig_form_valid(self, form)

            view_cls.form_valid = form_valid

        # ── Now patch *any* on-the-fly RegisterView clones ──
        if inspect.isclass(view_cls) and issubclass(view_cls, FormView):
            form_cls = getattr(view_cls, "form_class", None)
            if form_cls and issubclass(form_cls, UserCreationForm):
                orig_valid = getattr(view_cls, "form_valid")

                class DynamicRegisterForm(form_cls):
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        self.request = request

                    def clean_username(self):
                        username = self.cleaned_data["username"]
                        mgr = User._default_manager.db_manager(alias)
                        if mgr.filter(username=username).exists():
                            raise forms.ValidationError(
                                self.error_messages["duplicate_username"],
                                code="duplicate_username"
                            )
                        return username

                    def save(self, commit=True):
                        user = super().save(commit=False)
                        user.save(using=alias)
                        return user

                    def validate_unique(self):
                        # skip the global DB’s uniqueness checks
                        pass

                view_cls.form_class = DynamicRegisterForm

                def form_valid(self, form):
                    response = orig_valid(self, form)
                    # re-fetch & log in from the correct DB
                    usr = User._default_manager.db_manager(alias).get(pk=self.request.user.pk)
                    usr.backend = 'django.contrib.auth.backends.ModelBackend'
                    login(self.request, usr)
                    request.session['project_db_alias'] = alias
                    return response

                view_cls.form_valid = form_valid

        # ── Patch LoginView ──
        if inspect.isclass(view_cls) and issubclass(view_cls, LoginView):
            # fix form_invalid recursion
            orig_invalid = view_cls.form_invalid
            def form_invalid(self, form):
                messages.error(self.request, "Invalid username or password")
                return orig_invalid(self, form)
            view_cls.form_invalid = form_invalid

            # stash alias on successful login
            orig_valid = view_cls.form_valid
            def form_valid(self, form):
                resp = orig_valid(self, form)
                request.session['project_db_alias'] = alias
                return resp
            view_cls.form_valid = form_valid

            # redirect back under /projects/<id>/
            orig_get_success = view_cls.get_success_url
            def get_success_url(self):
                nxt = self.request.POST.get('next') or self.request.GET.get('next')
                if nxt:
                    return nxt
                m2 = re.match(r"^/projects/(?P<pid>\d+)", self.request.path_info)
                if m2:
                    return f"/projects/{m2.group('pid')}/"
                return orig_get_success(self)
            view_cls.get_success_url = get_success_url

        return None


class ProjectSessionAuthMiddleware:
    """
    After AuthMiddleware runs, re-fetch request.user from project_<id> DB
    if session contains our alias and user PK.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.User = get_user_model()

    def __call__(self, request):
        alias       = request.session.get('project_db_alias')
        user_id     = request.session.get(SESSION_KEY)
        backend_str = request.session.get(BACKEND_SESSION_KEY)

        if alias and user_id and backend_str:
            try:
                u = self.User._default_manager.db_manager(alias).get(pk=user_id)
                u._state.db = alias
                request.user = u
            except self.User.DoesNotExist:
                pass

        return self.get_response(request)
