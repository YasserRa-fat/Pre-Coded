# core/backends.py

from django.contrib.auth.backends import BaseBackend
from django.contrib.auth import get_user_model

class ProjectDBBackend(BaseBackend):
    """
    Authenticate by loading the user from the project‐specific DB.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        # 1) figure out which DB to use
        alias = getattr(request, "project_db_alias", None) or request.session.get("project_db_alias")
        if not alias or alias == "default":
            return None

        User = get_user_model()
        try:
            # 2) fetch the user from that DB
            user = User._default_manager.db_manager(alias).get(username=username)
        except User.DoesNotExist:
            return None

        # 3) check password
        if user.check_password(password):
            # mark this instance as coming from that DB
            user._state.db = alias
            return user

        return None

    def get_user(self, user_id):
        # When Django needs to re‐load the user by ID (e.g. from session),
        # it calls get_user().  We’ll fall back to default DB here.
        User = get_user_model()
        try:
            return User._default_manager.get(pk=user_id)
        except User.DoesNotExist:
            return None
