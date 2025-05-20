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
from urllib.parse import parse_qs
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

import json
from django.utils.deprecation import MiddlewareMixin
from create_api.models import AIChangeRequest


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
                # Grab the original form_class (may be None)
                orig_form = getattr(view_cls, 'form_class', None)
                if orig_form is None:
                    # nothing to patch if there's no form defined
                    return None

                # Safely subclass only when orig_form is a form class
                class ScopedRegisterForm(orig_form):
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        self.request = kwargs.get('request') or request

                    def clean_username(self):
                        alias = getattr(self.request, 'project_db_alias', 'default')
                        uname = self.cleaned_data.get('username')
                        User = get_user_model()
                        if User._default_manager.db_manager(alias).filter(username=uname).exists():
                            raise forms.ValidationError(
                                self.error_messages.get('duplicate_username',
                                                         'A user with that username already exists.'),
                                code='duplicate_username'
                            )
                        return uname

                    def save(self, commit=True):
                        alias = getattr(self.request, 'project_db_alias', 'default')
                        user = super().save(commit=False)
                        if commit:
                            user.save(using=alias)
                        return user

                    def validate_unique(self):
                        # skip default-DB unique checks
                        pass

                view_cls.form_class = ScopedRegisterForm

                # Now patch form_valid to use that same DB backend
                orig_valid = view_cls.form_valid
                def form_valid(self, form):
                    alias = getattr(self.request, 'project_db_alias', 'default')
                    user = form.save(commit=True)
                    backend = (
                        'core.backends.ProjectDBBackend'
                        if alias != 'default'
                        else 'django.contrib.auth.backends.ModelBackend'
                    )
                    user.backend = backend
                    login(self.request, user)
                    request.session[SESSION_KEY] = user.pk
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

                # Store original form_invalid
                orig_invalid = getattr(view_cls, 'form_invalid', None)
                if orig_invalid:
                    def form_invalid(self, form):
                        messages.error(self.request, "Invalid username or password")
                        return super(view_cls, self).form_invalid(form)
                    view_cls.form_invalid = form_invalid

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
    supports both session-based and JWT authentication with user syncing.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.User = get_user_model()
        self.jwt_auth = JWTAuthentication()

    def __call__(self, request):
        alias = getattr(request, 'project_db_alias', 'default')
        user = request.user

        # If we're under /projects/<id>/…, try to authenticate
        if alias.startswith('project_'):
            # First, try session-based authentication
            uid = request.session.get(SESSION_KEY)
            if uid:
                try:
                    u = self.User._default_manager.db_manager(alias).get(pk=uid)
                except self.User.DoesNotExist:
                    # if the session ID is bad, kick them out
                    logout(request)
                    request.user = AnonymousUser()
                    user = request.user
                else:
                    # simply attach them to the request—and set the backend—
                    # but do NOT call login() again
                    u._state.db = alias
                    u.backend = 'core.backends.ProjectDBBackend'
                    request.user = u
                    user = u 

            # If no session user, try JWT authentication
            if not request.user.is_authenticated:
                auth_header = request.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
                    try:
                        validated_token = self.jwt_auth.get_validated_token(token)
                        jwt_user = self.jwt_auth.get_user(validated_token)
                        # Check if user exists in project-specific database
                        try:
                            project_user = (self.User
                                            ._default_manager
                                            .db_manager(alias)
                                            .get(pk=jwt_user.pk))
                            project_user._state.db = alias
                            project_user.backend = 'core.backends.ProjectDBBackend'
                            request.user = project_user
                        except self.User.DoesNotExist:
                            # Sync user from default database to project database
                            default_user = self.User._default_manager.db_manager('default').get(pk=jwt_user.pk)
                            project_user = self.User(
                                id=default_user.id,
                                username=default_user.username,
                                email=default_user.email,
                                # Add other necessary fields
                            )
                            project_user.save(using=alias)
                            project_user._state.db = alias
                            request.user = project_user
                            project_user.backend = 'core.backends.ProjectDBBackend'
                    except (InvalidToken, TokenError) as e:
                        request.user = AnonymousUser()

        return self.get_response(request)
    


from channels.middleware import BaseMiddleware
from urllib.parse import parse_qs
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
import logging

logger = logging.getLogger(__name__)

async def get_user_from_token(token):
    """
    Authenticate user from JWT token (async-compatible)
    """
    User = get_user_model()
    
    try:
        # Validate the token
        validated_token = AccessToken(token)
        
        # Get user from token
        user_id = validated_token.get('user_id')
        
        if not user_id:
            logger.error("No user_id in token payload")
            return AnonymousUser()
        
        # Get the user from database using sync_to_async
        try:
            user = await sync_to_async(User.objects.get)(id=user_id)
            return user
        except User.DoesNotExist:
            logger.error(f"User with ID {user_id} not found")
            return AnonymousUser()
            
    except (TokenError, InvalidToken) as e:
        logger.error(f"Token validation error: {str(e)}")
        return AnonymousUser()
    except Exception as e:
        logger.error(f"Unexpected error in get_user_from_token: {str(e)}")
        return AnonymousUser()

class QueryAuthMiddleware:
    """
    Custom middleware that takes a token from the query string and authenticates the user
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ["websocket", "http"]:
            return await self.app(scope, receive, send)

        # Get token from query string
        query_string = scope.get("query_string", b"").decode()
        query_params = parse_qs(query_string)
        
        # Check for token in query string
        token = query_params.get("token", [None])[0]
        
        if token:
            # Authenticate user from token
            user = await get_user_from_token(token)
            if user and user.is_authenticated:
                logger.info(f"User authenticated via token: {user.username}")
                scope["user"] = user
                return await self.app(scope, receive, send)
            else:
                logger.error(f"Authentication failed for token")
        else:
            logger.error("No token provided in query string")

        # No valid token/user - close connection with authentication error
        if scope["type"] == "websocket":
            return await self.close_websocket(send)
        else:
            return await self.app(scope, receive, send)

    async def close_websocket(self, send):
        """Helper to close websocket with auth failure"""
        await send({
            "type": "websocket.close",
            "code": 4003,  # Custom close code for auth failure
        })

class QueryAuthMiddlewareStack:
    """
    Wrapper for the QueryAuthMiddleware that handles the middleware stack
    """
    def __init__(self, inner):
        self.inner = inner

    def __call__(self, scope, receive, send):
        return QueryAuthMiddleware(self.inner)(scope, receive, send)

# core/middleware.py
import logging
from core.thread_local import thread_local
from django.template import engines
from django.contrib.auth import get_user_model
from create_api.models import AIChangeRequest, StaticFile, App
from django.apps import apps
from django.db.models import Count
User = get_user_model()
logger = logging.getLogger(__name__)

class PreviewDiffMiddleware(MiddlewareMixin):
    def process_request(self, request):
        preview_mode = request.GET.get("preview_mode")
        preview_change_id = request.GET.get("preview_change_id")
        if preview_mode == "after" and preview_change_id:
            try:
                change = AIChangeRequest.objects.get(pk=preview_change_id)
                thread_local.preview_diff = json.loads(change.diff or "{}")
                thread_local.preview_mode = "after"
                logger.debug(f"Set thread_local.preview_mode={thread_local.preview_mode}, "
                             f"has_preview_diff={thread_local.preview_diff is not None}, "
                             f"diff_content={json.dumps(thread_local.preview_diff)[:100]}")
                # Invalidate template cache for preview requests
                engine = engines['django']
                if hasattr(engine.engine, 'template_cache'):
                    engine.engine.template_cache.clear()
                    logger.debug(f"Template cache cleared for preview_mode=after, change_id={preview_change_id}")
                else:
                    logger.warning("Template cache not available for invalidation")
                # Dynamically set preview context
                if not hasattr(request, 'preview_context'):
                    request.preview_context = self._get_dynamic_context(request)
                logger.debug(f"Set preview_context: {request.preview_context}")
            except AIChangeRequest.DoesNotExist:
                thread_local.preview_diff = None
                thread_local.preview_mode = None
                logger.warning(f"AIChangeRequest {preview_change_id} not found")
        else:
            thread_local.preview_diff = None
            thread_local.preview_mode = preview_mode
            logger.debug(f"Set thread_local.preview_mode={thread_local.preview_mode}, no preview_diff")

    def _get_dynamic_context(self, request):
        # Extract project_id from the URL
        match = re.match(r'/projects/(\d+)/', request.path)
        if not match:
            logger.warning(f"Could not extract project_id from path: {request.path}")
            project_id = None
        else:
            project_id = int(match.group(1))
        logger.debug(f"Extracted project_id={project_id} for dynamic context")

        # Dynamically determine the model and context keys for the project
        model_class = None
        context_keys = {'recent': 'entries', 'popular': 'popular_entries'}  # Default keys
        try:
            if project_id is not None:
                apps = App.objects.filter(project_id=project_id)
                if apps.count() > 1:
                    logger.warning(f"Multiple App objects found for project_id={project_id}, using the first one")
                app = apps.first()  # Use first if multiple, to be replaced by schema fix
                if not app:
                    logger.warning(f"No App found for project_id={project_id}")
                else:
                    app_label = app.name
                    model_name = getattr(app, 'content_model', None)
                    if not model_name:
                        logger.warning(f"No content_model defined for App with project_id={project_id}")
                    else:
                        model_class = apps.get_model(app_label=app_label, model_name=model_name)
                        logger.debug(f"Loaded model {app_label}.{model_name} for project_id={project_id}")
                    # Check if App specifies custom context keys
                    context_keys = getattr(app, 'context_keys', context_keys) or context_keys
        except (App.DoesNotExist, LookupError) as e:
            logger.warning(f"Could not determine model for project_id={project_id}: {e}")
            model_class = None

        # Fetch data dynamically if a model is found
        try:
            if model_class and project_id is not None:
                # Dynamically determine filter and sort fields
                filter_field = None
                sort_field = None
                for field in model_class._meta.fields:
                    if field.is_relation and field.related_model == App:
                        filter_field = field.name
                    if field.get_internal_type() in ('DateField', 'DateTimeField'):
                        sort_field = field.name

                # Build query dynamically
                entries = model_class.objects.all()
                if filter_field and project_id is not None:
                    entries = entries.filter(**{f"{filter_field}_id": project_id})
                if sort_field:
                    entries = entries.order_by(f"-{sort_field}")
                entries = entries[:5]

                dynamic_entries = []
                for entry in entries:
                    entry_data = {}
                    for field in model_class._meta.fields:
                        field_name = field.name
                        if field.is_relation and field.related_model == User:
                            entry_data[field_name] = getattr(getattr(entry, field_name, None), 'username', '') if getattr(entry, field_name, None) else ''
                        elif field.get_internal_type() == 'ImageField':
                            entry_data[field_name] = {'url': getattr(entry, field_name).url if getattr(entry, field_name) else ''} if hasattr(entry, field_name) else {}
                        elif field.get_internal_type() in ('DateField', 'DateTimeField'):
                            entry_data[field_name] = getattr(entry, field_name).strftime('%Y-%m-%d') if getattr(entry, field_name) else ''
                        else:
                            entry_data[field_name] = getattr(entry, field_name, '')
                    if hasattr(entry, 'get_absolute_url'):
                        entry_data['get_absolute_url'] = entry.get_absolute_url()
                    dynamic_entries.append(entry_data)

                # Fetch popular entries dynamically
                popular_entries = model_class.objects.all()
                if filter_field and project_id is not None:
                    popular_entries = popular_entries.filter(**{f"{filter_field}_id": project_id})
                comment_relation = next((f for f in model_class._meta.fields if f.is_relation and f.related_model._meta.model_name == 'comment'), None)
                if comment_relation and sort_field:
                    popular_entries = popular_entries.annotate(comment_count=Count(comment_relation.name)).order_by('-comment_count')
                popular_entries = popular_entries[:3]

                dynamic_popular_entries = []
                for entry in popular_entries:
                    entry_data = {}
                    for field in model_class._meta.fields:
                        if field.name in ('title', 'name'):
                            entry_data[field.name] = getattr(entry, field.name, '')
                    if hasattr(entry, 'get_absolute_url'):
                        entry_data['get_absolute_url'] = entry.get_absolute_url()
                    dynamic_popular_entries.append(entry_data)

                context = {
                    context_keys['recent']: dynamic_entries,
                    context_keys['popular']: dynamic_popular_entries,
                    'request': request,
                    'user': request.user
                }
            else:
                context = {
                    context_keys['recent']: [],
                    context_keys['popular']: [],
                    'request': request,
                    'user': request.user
                }
        except Exception as e:
            logger.error(f"Error fetching dynamic context for project_id={project_id}: {e}")
            context = {
                context_keys['recent']: [],
                context_keys['popular']: [],
                'request': request,
                'user': request.user
            }

        return context

    def process_response(self, request, response):
        # Clean up thread-local storage
        if hasattr(thread_local, 'preview_diff'):
            del thread_local.preview_diff
        if hasattr(thread_local, 'preview_mode'):
            del thread_local.preview_mode
        return response

class ThemeInjectorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only inject for HTML responses under /projects/
        if (
            not request.path.startswith('/projects/')
            or not response.get('Content-Type', '').startswith('text/html')
        ):
            return response

        # Extract project_id from the URL
        match = re.match(r'/projects/(\d+)/', request.path)
        if not match:
            logger.warning(f"Could not extract project_id from path: {request.path}")
            return response

        project_id = int(match.group(1))
        logger.debug(f"Extracted project_id={project_id} from path: {request.path}")

        # Fetch the project's theme from the App model
        theme = None
        try:
            apps = App.objects.filter(project_id=project_id)
            if apps.count() > 1:
                logger.warning(f"Multiple App objects found for project_id={project_id}, using the first one")
            app = apps.first()  # Use first if multiple, to be replaced by schema fix
            if app:
                theme = getattr(app, 'theme', None)
        except App.DoesNotExist:
            logger.warning(f"No App found for project_id={project_id}")

        logger.debug(f"Using theme={theme} for project_id={project_id}")

        # Fetch static files for the project
        css_files = []
        js_files = []
        try:
            static_files = StaticFile.objects.filter(project_id=project_id)
            for static_file in static_files:
                if theme and not static_file.path.startswith(f'static/{theme}/'):
                    continue  # Skip files not matching the theme
                if static_file.path.endswith('.css'):
                    css_files.append(static_file.path)
                elif static_file.path.endswith('.js'):
                    js_files.append(static_file.path)
        except Exception as e:
            logger.error(f"Error fetching static files for project_id={project_id}: {e}")

        # Generate injection snippets
        head_inject = "\n".join(
            f'<link rel="stylesheet" href="/{css_file}">' for css_file in css_files
        )
        body_inject = "\n".join(
            f'<script src="/{js_file}"></script>' for js_file in js_files
        )

        logger.debug(f"Injecting CSS: {css_files}")
        logger.debug(f"Injecting JS: {js_files}")

        # Inject into the response
        content = response.content.decode(response.charset)
        if head_inject:
            content = content.replace('</head>', head_inject + '\n</head>')
        if body_inject:
            content = content.replace('</body>', body_inject + '\n</body>')

        response.content = content.encode(response.charset)
        response['Content-Length'] = len(response.content)

        return response