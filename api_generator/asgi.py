"""
ASGI config for api_generator project.
"""

import os
import sys
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from core.ws_auth import JWTAuthMiddlewareStack
from core.ws_db_middleware import DatabaseMiddleware
from create_api.routing import websocket_urlpatterns
import logging
from core.early import dynamic_register_databases_early

logger = logging.getLogger(__name__)

# Set up Django's settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api_generator.settings')

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Initialize Django
try:
    django.setup()
    logger.info("Django initialized successfully")
except Exception as e:
    logger.error(f"Error initializing Django: {str(e)}")
    raise

# Register project databases early
try:
    dynamic_register_databases_early()
    logger.info("Project databases registered successfully")
except Exception as e:
    logger.error(f"Error registering databases: {str(e)}")
    raise

async def lifespan(scope, receive, send):
    """
    Handle ASGI lifespan events with proper cleanup
    """
    if scope["type"] != "lifespan":
        raise ValueError(
            f"Got unexpected scope type {scope['type']} - expected 'lifespan'"
        )
        
    try:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                # Perform startup
                try:
                    logger.info("ASGI server starting up")
                    await send({"type": "lifespan.startup.complete"})
                except Exception as e:
                    logger.error(f"Error during startup: {str(e)}")
                    await send({"type": "lifespan.startup.failed"})
                    return
                    
            elif message["type"] == "lifespan.shutdown":
                # Perform cleanup
                try:
                    logger.info("ASGI server shutting down")
                    # Close database connections
                    from django.db import connections
                    connections.close_all()
                    await send({"type": "lifespan.shutdown.complete"})
                except Exception as e:
                    logger.error(f"Error during shutdown: {str(e)}")
                    await send({"type": "lifespan.shutdown.failed"})
                    return
                    
    except Exception as e:
        logger.error(f"Error in lifespan protocol: {str(e)}")
        raise

# Log ASGI configuration
logger.info("Configuring ASGI application with middleware stack")

# Configure ASGI application with enhanced middleware stack
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AllowedHostsOriginValidator(
        DatabaseMiddleware(
            JWTAuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
        )
    ),
    "lifespan": lifespan,
})

logger.info("ASGI application configured successfully") 