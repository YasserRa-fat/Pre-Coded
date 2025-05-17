# api_generator/asgi_ws.py

import os
import sys
import logging
import threading
import django
import asyncio
from django.core.asgi import get_asgi_application
from django.conf import settings
from django.apps import apps as global_apps
from asgiref.sync import sync_to_async
from django.core.management import call_command
from pathlib import Path

logger = logging.getLogger(__name__)
# === NEW: ignore reloads on our preview folder ===
from django.utils.autoreload import file_changed
def _ignore_preview_changes(sender, file_path, **kwargs):
    p = Path(file_path)
    if "dynamic_apps_preview" in p.parts and any(part.startswith(("before_","after_")) for part in p.parts):
        return True
    return False
file_changed.connect(_ignore_preview_changes)
# === end ignore hook ===
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api_generator.settings")
sys.path.insert(0, os.path.dirname(__file__))

from core.early import dynamic_register_databases_early, dynamic_register_apps_early
dynamic_register_databases_early()
dynamic_register_apps_early()

import core.apps as _core_apps
def _core_ready_minimal(self):
    from core.db_importer import install as _install_db_finder
    _install_db_finder()
_core_apps.CoreConfig.ready = _core_ready_minimal

django.setup()

file_write_lock = threading.Lock()

@sync_to_async
def dynamic_register_databases():
    from core.startup import dynamic_register_databases
    dynamic_register_databases()

@sync_to_async
def dynamic_register_and_dump():
    from core.startup import dynamic_register_and_dump
    with file_write_lock:
        dynamic_register_and_dump()
        logger.debug("App registry after dump: %s", list(global_apps.app_configs.keys()))

@sync_to_async
def generate_and_apply_migrations():
    from django.db import connections
    with file_write_lock:
        try:
            dynamic_apps = [label for label in global_apps.app_configs if label.startswith("project_")]
            for app_label in dynamic_apps:
                logger.debug(f"Generating migrations for {app_label}")
                call_command("makemigrations", app_label, interactive=False, no_input=True, verbosity=1)
            for db in settings.DATABASES:
                if db.startswith("project_"):
                    logger.debug(f"Applying migrations for database {db}")
                    call_command("migrate", database=db, fake_initial=True, no_input=True)
        except Exception:
            logger.exception("Migration error")

async def initialize_dynamic_apps():
    try:
        from core.db_importer import install as install_db_importer
        install_db_importer()

        await dynamic_register_databases()
        await dynamic_register_and_dump()

        settings.MIGRATION_MODULES = getattr(settings, "MIGRATION_MODULES", {})
        for cfg in global_apps.get_app_configs():
            if cfg.label.startswith("project_"):
                settings.MIGRATION_MODULES[cfg.label] = f"dynamic_apps.{cfg.label}.migrations"

        await generate_and_apply_migrations()
        logger.info("Dynamic apps initialized successfully.")
    except Exception:
        logger.exception("Dynamic initialization failed")
        raise

async def lifespan_handler(scope, receive, send):
    if scope["type"] != "lifespan":
        raise RuntimeError("Expected lifespan scope")

    try:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                logger.info("Received lifespan.startup")
                try:
                    await initialize_dynamic_apps()
                    await send({"type": "lifespan.startup.complete"})
                    logger.info("Lifespan startup complete")
                except Exception:
                    await send({"type": "lifespan.startup.failed"})
            elif message["type"] == "lifespan.shutdown":
                logger.info("Received lifespan.shutdown")
                await send({"type": "lifespan.shutdown.complete"})
                break
    except asyncio.CancelledError:
        logger.debug("Lifespan cancelled by reload; exiting lifespan_handler.")

from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import re_path
from core.middleware import QueryAuthMiddleware
from create_api.consumers import ProjectConsumer

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": QueryAuthMiddleware(
        URLRouter([
            re_path(r"^ws/projects/(?P<project_id>\d+)/ai/$", ProjectConsumer.as_asgi()),
        ])
    ),
    "lifespan": lifespan_handler,
})

# Add debug logging for WebSocket connections
import logging
logger = logging.getLogger(__name__)

class DebuggedProtocolTypeRouter(ProtocolTypeRouter):
    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            logger.debug(f"WebSocket connection attempt: {scope.get('path', '')}")
            logger.debug(f"Query string: {scope.get('query_string', b'').decode()}")
        
        try:
            return await super().__call__(scope, receive, send)
        except Exception as e:
            logger.error(f"Error in protocol router: {str(e)}")
            if scope["type"] == "websocket":
                await send({
                    "type": "websocket.close",
                    "code": 4000,
                })
            raise

# Use the debugged router
application = DebuggedProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": QueryAuthMiddleware(
        URLRouter([
            re_path(r"^ws/projects/(?P<project_id>\d+)/ai/$", ProjectConsumer.as_asgi()),
        ])
    ),
    "lifespan": lifespan_handler,
})

# Add logging configuration if not already present
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'api_generator': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}
