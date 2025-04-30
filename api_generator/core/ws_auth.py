from urllib.parse import parse_qs
from channels.auth import AuthMiddlewareStack
from django.db import close_old_connections
from django.conf import settings
import jwt

class JWTAuthMiddleware:
    """
    Pulls `?token=<access_token>` from the WebSocket URL's query string,
    validates it via SimpleJWT, and sets `scope['user']` accordingly.
    """
    def __init__(self, inner):
        self.inner = inner

    def __call__(self, scope):
        # Lazy imports to avoid AppRegistryNotReady at startup
        from django.contrib.auth import get_user_model
        from rest_framework_simplejwt.tokens import UntypedToken
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

        # Extract token from query string
        query_string = scope.get('query_string', b"").decode()
        params = parse_qs(query_string)
        token_list = params.get('token')
        if token_list:
            token = token_list[0]
            try:
                # Validate token signature & expiration
                UntypedToken(token)
                # Decode to retrieve user_id
                data = jwt.decode(
                    token,
                    settings.SIMPLE_JWT['SIGNING_KEY'],
                    algorithms=[settings.SIMPLE_JWT['ALGORITHM']],
                )
                User = get_user_model()
                user = User.objects.get(id=data.get('user_id'))
                scope['user'] = user
                close_old_connections()
            except (InvalidToken, TokenError, jwt.PyJWTError, Exception):
                # Any error: leave as AnonymousUser
                pass
        return self.inner(scope)


def JWTAuthMiddlewareStack(inner):
    """
    A drop-in replacement for AuthMiddlewareStack that also
    handles JWT query-string authentication.
    """
    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
