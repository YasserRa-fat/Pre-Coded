from urllib.parse import parse_qs
from channels.auth import AuthMiddlewareStack
from django.db import close_old_connections
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import UntypedToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
import jwt
import logging
import asyncio
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

class JWTAuthMiddleware:
    """
    Enhanced JWT authentication middleware for WebSocket connections.
    Handles token validation, user authentication, and database connections.
    """
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope):
        # Close any stale database connections
        close_old_connections()
        
        try:
            # Extract token from query string
            query_string = scope.get('query_string', b"").decode()
            params = parse_qs(query_string)
            token_list = params.get('token')
            
            if not token_list:
                logger.warning("No token provided in WebSocket connection")
                scope['user'] = AnonymousUser()
                return await self.inner(scope)
                
            token = token_list[0]
            
            try:
                # Validate token
                UntypedToken(token)
                
                # Decode token
                decoded_data = jwt.decode(
                    token,
                    settings.SIMPLE_JWT['SIGNING_KEY'],
                    algorithms=[settings.SIMPLE_JWT['ALGORITHM']],
                )
                
                # Get user from database
                User = get_user_model()
                try:
                    user = await sync_to_async(User.objects.get)(id=decoded_data.get('user_id'))
                    
                    # Get project_id from URL path
                    path = scope.get('path', '')
                    import re
                    match = re.match(r'^/ws/projects/(?P<project_id>\d+)', path)
                    if match:
                        project_id = match.group('project_id')
                        project_db = f'project_{project_id}'
                        
                        # Try to get user from project database
                        try:
                            project_user = await sync_to_async(User.objects.using(project_db).get)(id=user.id)
                            project_user._state.db = project_db
                            scope['user'] = project_user
                            scope['project_db'] = project_db
                            logger.info(f"Authenticated user {user.username} for project {project_id}")
                        except User.DoesNotExist:
                            # User doesn't exist in project database, sync from default
                            project_user = User(
                                id=user.id,
                                username=user.username,
                                email=user.email,
                                password=user.password,
                                is_active=user.is_active,
                                is_staff=user.is_staff,
                                is_superuser=user.is_superuser,
                                date_joined=user.date_joined,
                                last_login=user.last_login
                            )
                            await sync_to_async(project_user.save)(using=project_db)
                            project_user._state.db = project_db
                            scope['user'] = project_user
                            scope['project_db'] = project_db
                            logger.info(f"Synced user {user.username} to project {project_id}")
                    else:
                        scope['user'] = user
                        logger.info(f"Authenticated user {user.username} (no project context)")
                        
                except User.DoesNotExist:
                    logger.error(f"User {decoded_data.get('user_id')} not found")
                    scope['user'] = AnonymousUser()
                    
            except (InvalidToken, TokenError, jwt.PyJWTError) as e:
                logger.error(f"Token validation error: {str(e)}")
                scope['user'] = AnonymousUser()
            except Exception as e:
                logger.error(f"Authentication error: {str(e)}")
                scope['user'] = AnonymousUser()
                
        except Exception as e:
            logger.error(f"Middleware error: {str(e)}")
            scope['user'] = AnonymousUser()
            
        finally:
            # Ensure database connections are properly managed
            close_old_connections()
            
        return await self.inner(scope)


def JWTAuthMiddlewareStack(inner):
    """
    Combines JWT authentication with the standard AuthMiddlewareStack.
    Provides both token-based and session-based authentication support.
    """
    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
