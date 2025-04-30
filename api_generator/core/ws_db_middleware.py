# core/ws_db_middleware.py
import re
from django.conf import settings
from pathlib import Path


class ProjectDBASGIMiddleware:
    """
    ASGI middleware: for each WebSocket or HTTP connect,
    ensure settings.DATABASES['project_<id>'] is registered.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Only run for websocket or http requests
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            m = re.match(r"^/ws/projects/(?P<project_id>\d+)", path)
            if m:
                alias = f"project_{m.group('project_id')}"
            else:
                # for HTTP you may also want to parse /projects/<id>/...
                parts = path.strip("/").split("/")
                if len(parts) >= 2 and parts[0] == "projects" and parts[1].isdigit():
                    alias = f"project_{parts[1]}"
                else:
                    alias = "default"

            # dynamically register if missing
            if alias != "default" and alias not in settings.DATABASES:
                db_path = Path(settings.BASE_DIR) / f"{alias}.sqlite3"
                settings.DATABASES[alias] = {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": str(db_path),
                }
            # stash for later (optional)
            scope["project_db_alias"] = alias

        # Pass through to the next app
        return await self.app(scope, receive, send)