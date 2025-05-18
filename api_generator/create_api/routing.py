# create_api/routing.py

from django.urls import re_path
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from core.ws_auth import JWTAuthMiddlewareStack
from core.ws_db_middleware import DatabaseMiddleware
from .consumers import ProjectConsumer
import logging

logger = logging.getLogger(__name__)

# Define URL patterns for WebSocket connections with proper routing
websocket_urlpatterns = [
    re_path(r'^ws/projects/(?P<project_id>\d+)/ai/?$', ProjectConsumer.as_asgi()),
]

# Configure the ASGI application with middleware stack
application = ProtocolTypeRouter({
    "websocket": AllowedHostsOriginValidator(
        DatabaseMiddleware(
            JWTAuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
        )
    ),
})

# Log the registered URL patterns
logger.info("WebSocket URL patterns:")
for pattern in websocket_urlpatterns:
    logger.info(f"  - {pattern.pattern}")
