import inspect
import re
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, SESSION_KEY, BACKEND_SESSION_KEY
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.views import LoginView
from django.views.generic import FormView
from django.contrib.auth import logout, SESSION_KEY, BACKEND_SESSION_KEY

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
    Patches registration and login views to scope auth to the proper DB.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        alias = getattr(request, 'project_db_alias', 'default')
        view_cls = getattr(view_func, 'view_class', None)

        # Avoid double-patching
        if not hasattr(view_cls, '_project_patched') and view_cls:
            # Patch RegisterView
            # Patch RegisterView: wrap both its form_class *and* form_valid so that
            # (1) username-uniqueness checks against project_<id> DB
            # (2) .save() writes into that DB
            # (3) session backend is set to ProjectDBBackend
            if view_cls.__name__ == 'RegisterView':
                # Wrap the view’s form to look at self.request.project_db_alias each time
                orig_form = getattr(view_cls, 'form_class', None)
                class ScopedRegisterForm(orig_form):
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        # attach the request so we can read alias dynamically
                        self.request = kwargs.get('request') or request
    
                    def clean_username(self):
                        alias = (
                            self.request.project_db_alias
                            or self.request.session.get('project_db_alias', 'default')
                        )
                        uname = self.cleaned_data.get('username')
                        from django.contrib.auth import get_user_model
                        User = get_user_model()
                        if User._default_manager.db_manager(alias).filter(username=uname).exists():
                            raise forms.ValidationError(
                                self.error_messages.get('duplicate_username',
                                                         'A user with that username already exists.'),
                                code='duplicate_username'
                            )
                        return uname
    
                    def save(self, commit=True):
                        alias = (
                            self.request.project_db_alias
                            or self.request.session.get('project_db_alias', 'default')
                        )
                        user = super().save(commit=False)
                        if commit:
                            user.save(using=alias)
                        return user
    
                    def validate_unique(self):
                        # don't run default-DB unique checks
                        pass
    
                view_cls.form_class = ScopedRegisterForm
    
                # And patch form_valid to log in from the same dynamic alias
                orig_valid = view_cls.form_valid
                def form_valid(self, form):
                    alias = (
                        self.request.project_db_alias
                        or self.request.session.get('project_db_alias', 'default')
                    )
                    user = form.save(commit=True)  # uses our save(using=alias)
    
                    # pick correct backend
                    backend = (
                        'core.backends.ProjectDBBackend'
                        if alias != 'default'
                        else 'django.contrib.auth.backends.ModelBackend'
                    )
                    user.backend = backend
    
                    login(self.request, user)
                    request.session[SESSION_KEY]         = user.pk
                    request.session[BACKEND_SESSION_KEY] = backend
                    if alias != 'default':
                        request.session['project_db_alias'] = alias
    
                    return orig_valid(self, form)
    
                view_cls.form_valid = form_valid
                view_cls._project_patched = True
                return None

            # Patch dynamic UserCreationForm on any FormView
            if issubclass(view_cls, FormView):
                form_cls = getattr(view_cls, 'form_class', None)
                if form_cls and issubclass(form_cls, UserCreationForm):
                    orig = view_cls.form_valid
                    class DynamicRegisterForm(form_cls):
                        def __init__(self, *args, **kwargs):
                            super().__init__(*args, **kwargs)
                            self.request = request
                        def clean_username(self):
                            uname = self.cleaned_data.get('username')
                            from django.contrib.auth.models import User as AuthUser
                            if AuthUser._default_manager.db_manager(alias).filter(username=uname).exists():
                                raise forms.ValidationError(self.error_messages.get('duplicate_username', 'Username taken'), code='duplicate_username')
                            return uname
                        def save(self, commit=True):
                            u = super().save(commit=False)
                            u.save(using=alias)
                            return u
                        def validate_unique(self):
                            pass
                    view_cls.form_class = DynamicRegisterForm
                    def form_valid(self, form):
                        resp = orig(self, form)
                        from django.contrib.auth.models import User as AuthUser
                        u = AuthUser._default_manager.db_manager(alias).get(pk=self.request.user.pk)
                        u.backend = 'django.contrib.auth.backends.ModelBackend'
                        login(self.request, u)
                        if alias != 'default':
                            request.session['project_db_alias'] = alias
                        return resp
                    view_cls.form_valid = form_valid
                    view_cls._project_patched = True
                    return None

            # Patch LoginView
            if issubclass(view_cls, LoginView):
                # Custom auth form to restrict default-DB users
                class ProjectAuthForm(AuthenticationForm):
                    def confirm_login_allowed(self, user):
                        current = getattr(self.request, 'project_db_alias', 'default')
                        user_db = getattr(user._state, 'db', 'default')
                        if current != 'default' and user_db == 'default':
                            raise forms.ValidationError('Invalid username or password', code='invalid_login')
                        super().confirm_login_allowed(user)
                view_cls.authentication_form = ProjectAuthForm

                # Patch form_valid to record alias
                orig_val = view_cls.form_valid
                def form_valid(self, form):
                    # before Django logs in, force the right backend
                    user = form.get_user()
                    backend = (
                        'core.backends.ProjectDBBackend'
                        if alias != 'default'
                        else 'django.contrib.auth.backends.ModelBackend'
                    )
                    user.backend = backend
                    # let Django do its normal login() now
                    resp = orig_val(self, form)
                    # now stash project alias
                    if alias != 'default':
                        self.request.session['project_db_alias'] = alias
                    return resp
                view_cls.form_valid = form_valid

                # Patch redirect under project path
                orig_url = view_cls.get_success_url
                def get_success_url(self):
                    nxt = self.request.POST.get('next') or self.request.GET.get('next')
                    if nxt:
                        return nxt
                    m = re.match(r'^/projects/(\d+)', self.request.path_info)
                    if m:
                        return f"/projects/{m.group(1)}/"
                    return orig_url(self)
                view_cls.get_success_url = get_success_url

                view_cls._project_patched = True
                return None

        return None


class ProjectSessionAuthMiddleware:
    """
    Ensures project pages only accept project-DB logins;
    logs out any default-DB user automatically.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.User = get_user_model()

    def __call__(self, request):
        alias = getattr(request, 'project_db_alias', 'default')
        user = request.user

        # If we’re under /projects/<id>/…, ignore whatever auth middleware loaded
        # and *always* re-load the user from that project's DB (or anon if not found).
        if alias.startswith('project_'):
            uid = request.session.get(SESSION_KEY)
            if uid:
                try:
                    u = self.User._default_manager.db_manager(alias).get(pk=uid)
                    u._state.db = alias
                    request.user = u
                except self.User.DoesNotExist:
                    logout(request)
                    request.user = AnonymousUser()
        return self.get_response(request)