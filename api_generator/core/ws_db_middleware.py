# core/ws_db_middleware.py
import re
import logging
import asyncio
from pathlib import Path
from django.conf import settings
from django.db import close_old_connections
from asgiref.sync import sync_to_async
from create_api.utils import get_current_project
from core.thread_local import thread_local
from django.core.exceptions import ObjectDoesNotExist
from create_api.models import TemplateFile

logger = logging.getLogger(__name__)

class DatabaseMiddleware:
    """
    ASGI middleware that manages database connections and project-specific databases.
    Ensures proper connection handling and cleanup for WebSocket connections.
    """
    def __init__(self, app):
        self.app = app
        self.connection_cleanup_interval = 300  # 5 minutes
        self.connection_timeout = 3600  # 1 hour
        self.active_connections = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        try:
            # Extract project ID from path
            path = scope.get("path", "")
            project_id = None
            
            # Try to match WebSocket path first
            ws_match = re.match(r"^/ws/projects/(?P<project_id>\d+)", path)
            if ws_match:
                project_id = ws_match.group('project_id')
            else:
                # Try HTTP path
                parts = path.strip("/").split("/")
                if len(parts) >= 2 and parts[0] == "projects" and parts[1].isdigit():
                    project_id = parts[1]
                    
            if project_id:
                alias = f"project_{project_id}"
                
                # Store project context in thread local
                thread_local.project_id = int(project_id)
                thread_local.db_alias = alias
                
                # Register database if not already registered
                if alias not in settings.DATABASES:
                    try:
                        # Get project settings
                        project = await sync_to_async(get_current_project)(project_id=int(project_id))
                        if project:
                            # Store project in thread local context
                            project._state.db = alias  # Ensure project knows its database
                            await sync_to_async(thread_local.set_context)('project', project)
                            
                            # Cache project templates
                            await self.cache_project_templates(project, alias)
                            
                            db_path = Path(settings.BASE_DIR) / f"{alias}.sqlite3"
                            settings.DATABASES[alias] = {
                                "ENGINE": "django.db.backends.sqlite3",
                                "NAME": str(db_path),
                                "CONN_MAX_AGE": self.connection_timeout,
                                "OPTIONS": {
                                    "timeout": 20,  # SQLite timeout in seconds
                                    "isolation_level": None,  # Autocommit mode
                                }
                            }
                            logger.info(f"Registered database {alias} at {db_path}")
                        else:
                            logger.error(f"Project not found: {project_id}")
                            await sync_to_async(thread_local.clear)()
                            return None
                    except Exception as e:
                        logger.error(f"Error registering database {alias}: {str(e)}")
                        await sync_to_async(thread_local.clear)()
                        return None
                else:
                    # Database already registered, but still need to get project for context
                    try:
                        project = await sync_to_async(get_current_project)(project_id=int(project_id))
                        if project:
                            # Store project in thread local context
                            project._state.db = alias  # Ensure project knows its database
                            await sync_to_async(thread_local.set_context)('project', project)
                            
                            # Cache project templates
                            await self.cache_project_templates(project, alias)
                        else:
                            logger.error(f"Project not found with ID: {project_id}")
                    except Exception as e:
                        logger.error(f"Error getting project for context: {str(e)}")
                    
                # Store database alias in scope
                scope["project_db_alias"] = alias
                
                # Track connection with more metadata
                connection_id = f"{scope['client'][0]}:{scope['client'][1]}"
                self.active_connections[connection_id] = {
                    'alias': alias,
                    'project_id': int(project_id),
                    'timestamp': asyncio.get_event_loop().time(),
                    'type': scope['type'],
                    'path': path
                }
                
                # Start connection cleanup task if not already running
                if not hasattr(self, 'cleanup_task'):
                    self.cleanup_task = asyncio.create_task(self.cleanup_old_connections())
                    
            # Wrap the receive function to handle disconnection
            original_receive = receive
            async def wrapped_receive():
                message = await original_receive()
                if message["type"] == "websocket.disconnect":
                    await self.handle_disconnect(scope)
                return message
                
            # Wrap the send function to handle errors
            original_send = send
            async def wrapped_send(message):
                if message["type"] == "websocket.close":
                    await self.handle_disconnect(scope)
                return await original_send(message)
                
            return await self.app(scope, wrapped_receive, wrapped_send)
            
        except Exception as e:
            logger.error(f"Error in DatabaseMiddleware: {str(e)}")
            # Ensure we clean up on error
            await self.handle_disconnect(scope)
            raise

    async def cache_project_templates(self, project, db_alias):
        """Cache project templates in thread local storage"""
        try:
            # Get all templates for the project
            templates = await sync_to_async(list)(TemplateFile.objects.using(db_alias).filter(project=project))
            logger.debug(f"Caching {len(templates)} templates for project {project.id}")
            
            # Create template cache with both name and path as keys
            template_cache = {}
            for t in templates:
                if not t.content:  # Skip templates with no content
                    logger.warning(f"Skipping empty template: name='{t.name}', path='{t.path}'")
                    continue
                    
                logger.debug(f"Template: name='{t.name}', path='{t.path}'")
                t._state.db = db_alias  # Ensure template knows its database
                
                # Cache all possible variations of the path
                template_cache[t.name] = t
                template_cache[t.path] = t
                template_cache[f"templates/{t.name}"] = t
                template_cache[f"templates/{t.path}"] = t
                template_cache[f"project_{project.id}/{t.name}"] = t
                template_cache[f"project_{project.id}/{t.path}"] = t
                template_cache[f"project_{project.id}/templates/{t.name}"] = t
                template_cache[f"project_{project.id}/templates/{t.path}"] = t
                
                # Cache base name for templates in subdirectories
                if '/' in t.path:
                    base_name = t.path.split('/')[-1]
                    if base_name not in template_cache:  # Don't override existing
                        template_cache[base_name] = t
                    
            # Store cache in thread local
            if template_cache:
                await sync_to_async(thread_local.set_context)('templates', template_cache)
                logger.debug(f"Template cache keys: {list(template_cache.keys())}")
            else:
                logger.warning(f"No valid templates found for project {project.id}")
                
        except Exception as e:
            logger.error(f"Error caching templates: {str(e)}")
            logger.error(f"Stack trace: {e.__traceback__}")
            # Clear template cache on error
            await sync_to_async(thread_local.clear_context)('templates')

    async def handle_disconnect(self, scope):
        """Handle WebSocket disconnection"""
        try:
            connection_id = f"{scope['client'][0]}:{scope['client'][1]}"
            if connection_id in self.active_connections:
                conn_info = self.active_connections[connection_id]
                logger.info(f"Cleaning up connection {connection_id} for project {conn_info['project_id']}")
                
                # Close database connections
                alias = conn_info['alias']
                await sync_to_async(close_old_connections)()
                
                # Remove from active connections
                del self.active_connections[connection_id]
            
            # Clear thread local
            await sync_to_async(thread_local.clear)()
                
        except Exception as e:
            logger.error(f"Error handling disconnect: {str(e)}")

    async def cleanup_old_connections(self):
        """Periodically clean up old connections"""
        while True:
            try:
                current_time = asyncio.get_event_loop().time()
                to_remove = []
                
                for conn_id, conn_info in self.active_connections.items():
                    if current_time - conn_info['timestamp'] > self.connection_timeout:
                        logger.info(f"Removing stale connection {conn_id}")
                        to_remove.append(conn_id)
                        
                for conn_id in to_remove:
                    if conn_id in self.active_connections:
                        del self.active_connections[conn_id]
                        
                # Close any stale database connections
                await sync_to_async(close_old_connections)()
                
            except Exception as e:
                logger.error(f"Error in connection cleanup: {str(e)}")
                
            await asyncio.sleep(self.connection_cleanup_interval)