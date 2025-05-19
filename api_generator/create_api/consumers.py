import json
import logging
import traceback
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User, AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from .models import (AIConversation, AIMessage, AIChangeRequest, Project, 
                     App, TemplateFile, ModelFile, ViewFile, FormFile, StaticFile, AppFile, UserModel, URLFile, SettingsFile)
from core.services.ai_editor import call_ai_multi_file
from django.conf import settings
from .views import setup_preview_project
from asgiref.sync import sync_to_async
from .preview_registry import preview_manager
from .utils import chunk_api_request, process_chunked_response
import difflib
import asyncio
from django.db.models import Q
import os
import ast
import datetime
from core.services.file_indexer import FileIndexer
from core.services.code_validator import DjangoCodeValidator
from django.db import transaction
import time
from collections import deque
from core.thread_local import thread_local
from django.shortcuts import render, get_object_or_404, redirect, HttpResponse
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    DeleteView,
    UpdateView,
)

from django.urls import reverse, reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils.text import slugify
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta
from django.apps import apps
import aiofiles
from typing import Optional, List
from django.core.files.base import ContentFile

# Handle different WebSocket libraries
try:
    from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
except ImportError:
    # Define fallback classes if the specific ones aren't available
    class ConnectionClosedOK(Exception):
        pass
    class ConnectionClosedError(Exception):
        pass

logger = logging.getLogger(__name__)

# Add debug constants
DEBUG_CONSUMER = True
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY = 1  # seconds
MESSAGE_QUEUE_SIZE = 100

class BaseWebSocketConsumer(AsyncWebsocketConsumer):
    """Base WebSocket consumer with enhanced connection handling"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = None
        self.user = None
        self.pending_messages = deque()
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 1  # Initial delay in seconds
        self.last_heartbeat = None
        self.heartbeat_interval = 30  # Increased from 15 to 30 seconds for less overhead
        self.heartbeat_task = None
        self.heartbeat_timeout = 90  # 3x heartbeat interval
        self.is_closing = False
        self.processing_lock = asyncio.Lock()
        
    async def connect(self):
        """Handle WebSocket connection with minimal authentication"""
        try:
            # Get project ID from URL route
            self.project_id = self.scope["url_route"]["kwargs"]["project_id"]
            logger.info(f"Connection attempt for project {self.project_id}")
            
            # Set thread local context
            thread_local.project_id = int(self.project_id)
            thread_local.db_alias = f"project_{self.project_id}"
            
            # Basic token authentication
            query_string = self.scope.get("query_string", b"").decode()
            if "token=" in query_string:
                token = query_string.split("token=")[1].split("&")[0]
                self.user = await self.get_user_from_token(token)
            else:
                self.user = None
            
            if not self.user or isinstance(self.user, AnonymousUser):
                logger.error("Authentication failed")
                await self.close(code=4003)
                return
            
            # Create conversation
            self.conversation = await self.create_conversation(self.project_id, self.user)
            
            # Accept the connection
            await self.accept()
            logger.info(f"WebSocket connected for user {self.user.username}, project {self.project_id}")
            
            # Wait longer to ensure connection is stable before sending first message
            await asyncio.sleep(2)
            
            # Send success message
            success = await self.safe_send(json.dumps({
                'type': 'connection_established',
                'message': 'Connected successfully'
            }))
            
            if success:
                logger.info("Successfully sent connection_established message")
            else:
                logger.error("Failed to send connection_established message")
                await self.close(code=4005)
            
        except Exception as e:
            logger.error(f"Connection error: {str(e)}")
            logger.error(traceback.format_exc())
            await self.close(code=4000)
            
    async def disconnect(self, close_code):
        """
        Leave the room group and cleanup
        """
        logger.debug(f"WebSocket disconnecting with code {close_code}")
        
        # Set flags first to prevent race conditions
        self.is_closing = True
        self.is_connected = False
        
        try:
            # Cancel tasks
            tasks_to_cancel = []
            if hasattr(self, 'reconnect_task') and self.reconnect_task:
                tasks_to_cancel.append(self.reconnect_task)
            if hasattr(self, 'heartbeat_task') and self.heartbeat_task:
                tasks_to_cancel.append(self.heartbeat_task)
            if hasattr(self, 'message_processor') and self.message_processor:
                tasks_to_cancel.append(self.message_processor)
                
            for task in tasks_to_cancel:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        logger.info("Task cancelled successfully")
                    except Exception as e:
                        logger.error(f"Error cancelling task: {str(e)}")
            
            # Leave the room group
            if hasattr(self, 'room_group_name'):
                try:
                    await self.channel_layer.group_discard(
                        self.room_group_name,
                        self.channel_name
                    )
                except Exception as e:
                    logger.error(f"Error leaving channel group: {str(e)}")

            # Update conversation status
            if hasattr(self, 'conversation') and self.conversation:
                try:
                    await self.update_conversation_status(self.conversation.id, 'disconnected')
                except Exception as e:
                    logger.error(f"Error updating conversation status: {str(e)}")
                    
            logger.info(f"WebSocket disconnected for user {self.user.username if self.user else 'unknown'}, project {self.project_id if hasattr(self, 'project_id') else 'unknown'}")
                    
        except Exception as e:
            logger.error(f"Error during disconnect cleanup: {str(e)}")
            logger.error(traceback.format_exc())
            
    async def receive(self, text_data):
        """Handle incoming WebSocket messages with error handling"""
        try:
            if not text_data:
                return
                
            # Update heartbeat timestamp on any message
            self.last_heartbeat = time.time()
            
            # Handle heartbeat response
            try:
                message = json.loads(text_data)
                if message.get('type') == 'heartbeat':
                    # Just update timestamp for heartbeat messages
                    return
            except json.JSONDecodeError:
                logger.error("Invalid JSON message received")
                await self.send_error("Invalid message format")
                return
                
            # Process other message types
            message_type = message.get('type')
            if not message_type:
                await self.send_error("Message type not specified")
                return
                
            # Handle message
            handler = getattr(self, f"handle_{message_type}", None)
            if handler:
                await handler(message)
            else:
                await self.send_error(f"Unknown message type: {message_type}")
                
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            await self.send_error("Internal server error")
            
    async def send_error(self, message, code=None):
        """Send error message to client"""
        error_data = {
            'type': 'error',
            'message': message
        }
        if code:
            error_data['code'] = code
            
        await self.send(text_data=json.dumps(error_data))
        
    async def send_heartbeat(self):
        """Send periodic heartbeat to keep connection alive"""
        while not self.is_closing:
            try:
                if not self.is_connected:
                    await asyncio.sleep(self.heartbeat_interval)
                    continue

                await self.send(text_data=json.dumps({
                    'type': 'heartbeat',
                    'timestamp': datetime.datetime.now().isoformat()
                }))
                self.last_heartbeat = time.time()
                await asyncio.sleep(self.heartbeat_interval)
            except Exception as e:
                logger.error(f"Error sending heartbeat: {str(e)}")
                if not self.is_closing:
                    await asyncio.sleep(self.heartbeat_interval)

    @database_sync_to_async
    def get_project(self):
        """Get project with proper database routing"""
        try:
            return Project.objects.using(thread_local.db_alias).get(id=self.project_id)
        except Project.DoesNotExist:
            logger.error(f"Project {self.project_id} not found")
            return None
        except Exception as e:
            logger.error(f"Error getting project: {str(e)}")
            return None
            
    @database_sync_to_async
    def get_authenticated_user(self):
        """Get authenticated user with proper database routing"""
        try:
            if 'user' not in self.scope:
                return None
            user = self.scope['user']
            if not user.is_authenticated:
                return None
            # Ensure user exists in project database
            return User.objects.using(thread_local.db_alias).get(id=user.id)
        except User.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"Error getting authenticated user: {str(e)}")
            return None
            
    async def handle_reconnect(self, message):
        """Handle reconnection attempts"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            await self.send_error("Max reconnection attempts reached", code=4001)
            await self.close(code=4001)
            return
            
        self.reconnect_attempts += 1
        await asyncio.sleep(self.reconnect_delay * self.reconnect_attempts)
        
        try:
            # Attempt to reconnect
            await self.connect()
        except Exception as e:
            logger.error(f"Reconnection attempt failed: {str(e)}")
            await self.send_error("Reconnection failed")
            
class AIWebSocketConsumer(BaseWebSocketConsumer):
    """WebSocket consumer for AI-related operations"""
    
    async def handle_ai_request(self, message):
        """Handle AI service requests"""
        try:
            # Validate request
            if not self.validate_ai_request(message):
                await self.send_error("Invalid AI request format")
                return
                
            # Process request
            response = await self.process_ai_request(message)
            
            # Send response
            await self.send(text_data=json.dumps({
                'type': 'ai_response',
                'data': response
            }))
            
        except Exception as e:
            logger.error(f"Error processing AI request: {str(e)}")
            await self.send_error("Error processing AI request")
            
    def validate_ai_request(self, message):
        """Validate AI request format"""
        required_fields = ['action', 'data']
        return all(field in message for field in required_fields)
        
    @database_sync_to_async
    def process_ai_request(self, message):
        """Process AI request with database transaction"""
        with transaction.atomic(using=thread_local.db_alias):
            # Create conversation if needed
            conversation = AIConversation.objects.using(thread_local.db_alias).create(
                project=self.project,
                user=self.user
            )
            
            # Create message
            ai_message = AIMessage.objects.using(thread_local.db_alias).create(
                conversation=conversation,
                content=message['data'],
                message_type='user'
            )
            
            # Call AI service
            response = call_ai_multi_file(message['data'], self.project)
            
            # Create response message
            AIMessage.objects.using(thread_local.db_alias).create(
                conversation=conversation,
                content=response,
                message_type='assistant'
            )
            
            return response

class ProjectConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = None
        self.user = None
        self.conversation = None
        self.message_queue = asyncio.Queue()
        self.message_processor = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_connection_retries = 3  # Add max retries constant
        self.reconnect_delay = 2  # seconds
        self.last_heartbeat = None
        self.heartbeat_interval = 30
        self.heartbeat_task = None
        self.reconnect_task = None  # Add reconnect task attribute
        self.heartbeat_timeout = 90
        self.is_closing = False
        self.processing_lock = asyncio.Lock()
        self.is_processing = False

    async def connect(self):
        """
        Authenticate user with JWT token and connect to WebSocket
        """
        logger.info("WebSocket connection attempt")
        
        try:
            # Reset connection state
            self.is_connected = False
            self.is_closing = False
            self.connection_retries = 0
            self.last_error = None
            
            # Get token from query string
            query_string = self.scope.get("query_string", b"").decode()
            if "token=" not in query_string:
                logger.error("No token provided for WebSocket connection")
                await self.close(code=4003)
                return

            self.token = query_string.split("token=")[1].split("&")[0]
            
            # Authenticate with JWT
            self.user = await self.get_user_from_token(self.token)
            if not self.user or isinstance(self.user, AnonymousUser):
                logger.error(f"Invalid user for token: {self.token[:10]}...")
                await self.close(code=4003)
                return

            # Get project ID from URL
            try:
                self.project_id = self.scope['url_route']['kwargs']['project_id']
            except KeyError:
                logger.error("No project ID in URL route")
                await self.close(code=4004)
                return
            
            # Check if project exists and user has access
            project_exists = await self.check_project_access(self.project_id, self.user)
            if not project_exists:
                logger.error(f"User {self.user.username} attempted to access unauthorized project {self.project_id}")
                await self.close(code=4004)
                return

            # Join project group with retry
            self.room_group_name = f"project_{self.project_id}"
            joined = False
            
            for attempt in range(self.max_connection_retries):
                try:
                    await self.channel_layer.group_add(
                        self.room_group_name,
                        self.channel_name
                    )
                    joined = True
                    break
                except Exception as e:
                    logger.error(f"Error joining channel group (attempt {attempt + 1}): {str(e)}")
                    if attempt < self.max_connection_retries - 1:
                        await asyncio.sleep(self.retry_delay)
                    
            if not joined:
                logger.error("Failed to join channel group after retries")
                await self.close(code=4005)
                return

            # Get app_name and file_path from query string if present
            app_name = None
            file_path = None
            if "app_name=" in query_string:
                app_name = query_string.split("app_name=")[1].split("&")[0]
            if "file_path=" in query_string:
                file_path = query_string.split("file_path=")[1].split("&")[0]
            
            # Create or get conversation
            try:
                self.conversation = await self.create_conversation(
                    project_id=self.project_id,
                    user=self.user,
                    app_name=app_name,
                    file_path=file_path
                )
            except Exception as e:
                logger.error(f"Error creating conversation: {str(e)}")
                await self.close(code=4005)
                return

            # Accept the connection
            await self.accept()
            self.is_connected = True
            
            # Start message queue processor and heartbeat
            self.reconnect_task = asyncio.create_task(self.process_message_queue())
            self.heartbeat_task = asyncio.create_task(self.send_heartbeat())
            
            logger.info(f"WebSocket connected for user {self.user.username}, project {self.project_id}")
            
            # Send connection success message
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'message': 'Connected successfully',
                'user': self.user.username,
                'project_id': self.project_id,
                'timestamp': datetime.datetime.now().isoformat()
            }))
            
        except Exception as e:
            error_message = f"Error in WebSocket connect: {str(e)}"
            logger.error(error_message)
            logger.error(traceback.format_exc())
            self.last_error = error_message
            await self.close(code=4000)

    async def send_heartbeat(self):
        """Send periodic heartbeat to keep connection alive"""
        while not self.is_closing:
            try:
                if not self.is_connected:
                    await asyncio.sleep(self.heartbeat_interval)
                    continue

                await self.send(text_data=json.dumps({
                    'type': 'heartbeat',
                    'timestamp': datetime.datetime.now().isoformat()
                }))
                self.last_heartbeat = time.time()
                await asyncio.sleep(self.heartbeat_interval)
            except Exception as e:
                logger.error(f"Error sending heartbeat: {str(e)}")
                if not self.is_closing:
                    await asyncio.sleep(self.heartbeat_interval)

    async def disconnect(self, close_code):
        """
        Leave the room group and cleanup
        """
        logger.debug(f"WebSocket disconnecting with code {close_code}")
        
        # Set flags first to prevent race conditions
        self.is_closing = True
        self.is_connected = False
        
        try:
            # Cancel tasks
            tasks_to_cancel = []
            if hasattr(self, 'reconnect_task') and self.reconnect_task:
                tasks_to_cancel.append(self.reconnect_task)
            if hasattr(self, 'heartbeat_task') and self.heartbeat_task:
                tasks_to_cancel.append(self.heartbeat_task)
            if hasattr(self, 'message_processor') and self.message_processor:
                tasks_to_cancel.append(self.message_processor)
                
            for task in tasks_to_cancel:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        logger.info("Task cancelled successfully")
                    except Exception as e:
                        logger.error(f"Error cancelling task: {str(e)}")
            
            # Leave the room group
            if hasattr(self, 'room_group_name'):
                try:
                    await self.channel_layer.group_discard(
                        self.room_group_name,
                        self.channel_name
                    )
                except Exception as e:
                    logger.error(f"Error leaving channel group: {str(e)}")

            # Update conversation status
            if hasattr(self, 'conversation') and self.conversation:
                try:
                    await self.update_conversation_status(self.conversation.id, 'disconnected')
                except Exception as e:
                    logger.error(f"Error updating conversation status: {str(e)}")
                    
            logger.info(f"WebSocket disconnected for user {self.user.username if self.user else 'unknown'}, project {self.project_id if hasattr(self, 'project_id') else 'unknown'}")
                    
        except Exception as e:
            logger.error(f"Error during disconnect cleanup: {str(e)}")
            logger.error(traceback.format_exc())

    async def process_message_queue(self):
        """Process messages in the queue with improved error handling"""
        while not self.is_closing:
            try:
                if not self.is_connected:
                    await asyncio.sleep(self.retry_delay)
                    continue
                    
                try:
                    message = await asyncio.wait_for(
                        self.message_queue.get(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue
                    
                try:
                    await self.send(text_data=json.dumps(message))
                    logger.debug(f"Successfully sent queued message of type: {message.get('type')}")
                    self.message_queue.task_done()
                except Exception as e:
                    logger.error(f"Error sending queued message: {str(e)}")
                    if not self.is_closing:
                        await self.message_queue.put(message)
                        await asyncio.sleep(self.retry_delay)
                    
            except asyncio.CancelledError:
                logger.info("Message queue processor cancelled")
                break
            except Exception as e:
                logger.error(f"Error in message queue processor: {str(e)}")
                if not self.is_closing:
                    await asyncio.sleep(self.retry_delay)

    async def handle_confirm_changes(self, data):
        """Handle confirmation of changes with cleanup"""
        try:
            change_id = data.get('change_id')
            if not change_id:
                await self.send_error_safe("No change ID provided")
                await self.send_chat_message_safe('assistant', "No change ID provided. Please try again.")
                return
                
            change_request = await self.get_change_request(change_id)
            if not change_request:
                await self.send_error_safe("Change request not found")
                await self.send_chat_message_safe('assistant', "Change request not found. Please try again.")
                return
                
            # Apply changes
            try:
                diffs = json.loads(change_request.diff)
                
                # Validate diff structure
                if not isinstance(diffs, dict) or 'files' not in diffs:
                    await self.send_error_safe("Invalid diff format")
                    await self.send_chat_message_safe('assistant', "Error: Invalid diff format in the change request.")
                    return
                    
                if not isinstance(diffs['files'], dict):
                    await self.send_error_safe("Invalid files format in diff")
                    await self.send_chat_message_safe('assistant', "Error: Invalid files format in the change request.")
                    return
                
                # Apply the changes with transaction
                async with transaction.atomic():
                    for file_path, file_data in diffs['files'].items():
                        # Get the new content from the 'after' field
                        if not isinstance(file_data, dict) or 'after' not in file_data:
                            await self.send_error_safe(f"Invalid file data format for {file_path}")
                            continue

                        content = file_data['after']
                        file_type = file_data.get('file_type')
                        is_new = file_data.get('is_new', False)

                        # Validate the file content before applying
                        validator = DjangoCodeValidator()
                        is_valid, issues = validator.validate_file(file_path, content)
                        
                        if not is_valid:
                            error_msg = f"Validation failed for {file_path}: {', '.join(issues)}"
                            await self.send_error_safe(error_msg)
                            await self.send_chat_message_safe('assistant', error_msg)
                            return
                            
                        # Apply changes to actual project files
                        success = await self.apply_file_change(change_request.project_id, file_path, content, file_type)
                        if not success:
                            raise Exception(f"Failed to apply changes to {file_path}")
                            
            except json.JSONDecodeError:
                await self.send_error_safe("Invalid JSON in change request")
                await self.send_chat_message_safe('assistant', "Error: Change request contains invalid JSON data.")
                return
            except Exception as e:
                await self.send_error_safe(f"Error applying changes: {str(e)}")
                await self.send_chat_message_safe('assistant', f"Error applying changes: {str(e)}")
                return
            
            # Update statuses
            await self.update_change_request_status(change_id, 'applied')
            await self.update_conversation_status(self.conversation.id, 'closed')
            
            # Cleanup previews
            before_alias = f"preview_{self.project_id}_before_{change_id}"
            after_alias = f"preview_{self.project_id}_after_{change_id}"
            try:
                await preview_manager.cleanup_preview(before_alias)
                await preview_manager.cleanup_preview(after_alias)
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up previews: {str(cleanup_error)}")
                # Continue despite preview cleanup errors
            
            # Send success message
            await self.send_chat_message_safe('assistant', "Changes have been applied successfully!")
            
        except Exception as e:
            error_msg = f"Error applying changes: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            await self.send_error_safe(error_msg)
            await self.send_chat_message_safe('assistant', f"Error applying changes: {str(e)}")

    async def send_chat_message_safe(self, sender, text):
        """
        Send a chat message to the WebSocket with improved error handling and connection state check
        """
        if not self.is_connected or self.is_closing:
            logger.warning(f"Skipping chat message - connection closed: {text[:50]}...")
            await self.message_queue.put({
                "type": "chat_message",
                "sender": sender,
                "text": text,
                "timestamp": datetime.datetime.now().isoformat()
            })
            return
            
        try:
            if not hasattr(self, 'channel_name') or not self.channel_name:
                logger.warning("Cannot send chat message - no channel name")
                return
            
            if not hasattr(self, 'channel_layer'):
                logger.warning("Cannot send chat message - no channel layer")
                return
            
            # Check if we're still processing before sending
            async with self.processing_lock:
                if not self.is_processing:
                    logger.warning("Message processing completed, not sending response")
                    return
            
            # Send directly instead of using channel layer
            await self.send(text_data=json.dumps({
                "type": "chat_message",
                "sender": sender,
                "text": text,
                "timestamp": datetime.datetime.now().isoformat()
            }))
            
        except (ConnectionClosedOK, ConnectionClosedError) as e:
            logger.warning(f"Cannot send chat message - connection closed: {str(e)}")
            self.is_connected = False
            await self.message_queue.put({
                "type": "chat_message",
                "sender": sender,
                "text": text,
                "timestamp": datetime.datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error sending chat message: {str(e)}")
            logger.error(traceback.format_exc())
            self.is_connected = False

    async def chat_message(self, event):
        """
        Handler for chat.message type events
        """
        try:
            await self.send(text_data=json.dumps({
                "type": "chat_message",
                "sender": event["sender"],
                "text": event["text"],
                "timestamp": event.get("timestamp", datetime.datetime.now().isoformat())
            }))
        except Exception as e:
            logger.error(f"Error in chat_message handler: {str(e)}")
            logger.error(traceback.format_exc())

    async def receive(self, text_data):
        """
        Receive message from WebSocket and process it
        """
        logger.debug(f"Received WebSocket message: {text_data}")
        try:
            # Save the raw input text for later use if needed
            self.last_message = text_data
            
            data = json.loads(text_data)
            message_type = data.get('type')
            
            # Set processing flag before handling message
            async with self.processing_lock:
                self.is_processing = True
                
            try:
                if message_type == 'send_message':
                    await self.handle_send_message(data)
                elif message_type == 'confirm_changes':
                    await self.handle_confirm_changes(data)
                elif message_type == 'chat_message':
                    await self.handle_chat_message(data)
                elif message_type == 'get_analytics':
                    await self.handle_analytics_request(data)
                else:
                    logger.warning(f"Unknown message type: {message_type}")
                    await self.send_error_safe("Unknown message type")
            finally:
                # Reset processing flag after handling message
                async with self.processing_lock:
                    self.is_processing = False
                
        except json.JSONDecodeError:
            logger.error("Failed to parse WebSocket message as JSON")
            await self.send_error_safe("Invalid JSON format")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {str(e)}")
            logger.error(traceback.format_exc())
            await self.send_error_safe(f"Error processing message: {str(e)}")
            # Reset processing flag on error
            async with self.processing_lock:
                self.is_processing = False

    async def handle_chat_message(self, data):
        """
        Redirect chat messages to code changes
        """
        if DEBUG_CONSUMER:
            logger.info("Chat message received - redirecting to code changes")
        # Simply forward the request to handle_send_message to ensure consistent handling
        await self.handle_send_message(data)

    async def handle_send_message(self, data):
        """Process a user message for code changes"""
        if not self.user or not self.conversation:
            await self.send_error_safe("Not authenticated")
            return
        
        text = data.get('text', '').strip()
        if not text:
            await self.send_error_safe("Empty message")
            return
        
        try:
            logger.info(f"Processing message from user {self.user.username}: {text}")
            
            # Set up thread local context
            thread_local.project_id = self.project_id
            thread_local.db_alias = f"project_{self.project_id}"
            
            # Get project files for context
            try:
                project_files = await self.get_project_files(self.project_id)
                logger.info(f"Retrieved {len(project_files)} project files")
                
                if not project_files:
                    await self.send_error_safe("No project files found")
                    return

                # Get project context
                project_context = await self.get_project_context(self.project_id)
                if not project_context:
                    await self.send_error_safe("Could not get project context")
                    return

                # Prepare file context for AI
                file_context = {
                    'project_files': {
                        path: {
                            'type': info['type'],
                            'name': info['name'],
                            'app': info['app'],
                            'app_id': info['app_id'],
                            'preview': info['content'][:500] + '...' if len(info['content']) > 500 else info['content']
                        }
                        for path, info in project_files.items()
                    },
                    'project_structure': {
                        'apps': project_context['apps'],
                        'templates': [p for p, info in project_files.items() if info['type'] == 'templates'],
                        'views': [p for p, info in project_files.items() if info['type'] == 'views'],
                        'models': [p for p, info in project_files.items() if info['type'] == 'models'],
                        'forms': [p for p, info in project_files.items() if info['type'] == 'forms'],
                        'static': [p for p, info in project_files.items() if info['type'] == 'static'],
                        'urls': [p for p, info in project_files.items() if info['type'] == 'urls']
                    }
                }

                # First call to analyze which files need to be modified
                analysis_prompt = (
                    f"Analyze which existing files need to be modified for this request. "
                    f"Consider the project structure and app context. Request: {text}\n\n"
                    f"Project Context:\n"
                    f"- Project ID: {self.project_id}\n"
                    f"- Apps: {', '.join(app['name'] for app in project_context['apps'])}\n\n"
                    f"Available files:\n" + 
                    "\n".join(f"- {path} (type: {info['type']}, app: {info['app']})" for path, info in project_files.items()) +
                    "\n\nNote: Consider app context and dependencies when selecting files."
                )

                request_analysis = await call_ai_multi_file(
                    self.conversation,
                    analysis_prompt,
                    {
                        'request': text,
                        'context': file_context,
                        'project_id': self.project_id,
                        'user_id': self.user.id,
                        'app_name': getattr(self, 'app_name', None),
                        'file_path': getattr(self, 'file_path', None),
                        'project_context': project_context
                    }
                )
                
                if not request_analysis or not isinstance(request_analysis, dict):
                    logger.error("Invalid response from request analysis")
                    await self.send_error_safe("Failed to analyze request")
                    return

                # Get relevant files based on AI analysis
                relevant_files = {}
                total_size = 0
                max_size = 32000  # Token limit
                
                selected_files = request_analysis.get('selected_files', [])
                logger.info(f"AI selected files: {selected_files}")
                
                # Only include files that actually exist
                for file_path in selected_files:
                    # Try both with and without type prefix
                    normalized_path = file_path.replace('\\', '/').lstrip('/')
                    file_info = None
                    
                    # Try different path variations
                    variations = [
                        normalized_path,
                        f"{project_files[normalized_path]['type']}/{normalized_path}" if normalized_path in project_files else None,
                        normalized_path[normalized_path.find('/')+1:] if '/' in normalized_path else None
                    ]
                    
                    for path in variations:
                        if path and path in project_files:
                            file_info = project_files[path]
                            normalized_path = path
                            break
                    
                    if not file_info:
                        logger.warning(f"Selected file {file_path} not found in project")
                        continue

                    content = file_info['content']
                    estimated_tokens = len(content) // 4
                    
                    if total_size + estimated_tokens <= max_size:
                        relevant_files[normalized_path] = {
                            'file_path': normalized_path,
                            'file_type': file_info['type'],
                            'app': file_info['app'],
                            'app_id': file_info['app_id'],
                            'change_desc': text,
                            'original_content': content
                        }
                        total_size += estimated_tokens
                        logger.info(f"Including file {normalized_path} for changes")
                    else:
                        logger.warning(f"Skipping {normalized_path} due to token limit")

                if not relevant_files:
                    logger.error("No relevant existing files found")
                    await self.send_error_safe("No relevant existing files found for the requested changes")
                    return

                # Second AI call to generate actual changes
                change_response = await call_ai_multi_file(
                    self.conversation,
                    text,
                    {
                        'files': relevant_files,
                        'project_context': project_context,
                        'request_analysis': request_analysis
                    }
                )

                if not change_response:
                    logger.error("No response from change generation AI call")
                    await self.send_error_safe("Failed to generate changes")
                    return

                # Process the response
                await self.process_ai_response(change_response)

            except Exception as e:
                logger.error(f"Error getting project files: {str(e)}")
                await self.send_error_safe("Failed to retrieve project files")
                return

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            logger.error(traceback.format_exc())
            await self.send_error_safe(f"Failed to generate code changes: {str(e)}")
            
        finally:
            # Clear thread local context
            thread_local.clear()
            
            # Ensure processing flag is reset
            async with self.processing_lock:
                self.is_processing = False

    def _get_file_type(self, file_path: str) -> str:
        """Helper method to determine file type from path"""
        if file_path.endswith('.py'):
            if any(x in file_path for x in ['/views/', 'views.py']):
                return 'view'
            elif any(x in file_path for x in ['/models/', 'models.py']):
                return 'model'
            elif any(x in file_path for x in ['/forms/', 'forms.py']):
                return 'form'
            elif 'urls.py' in file_path:
                return 'urls'
            return 'python'
        elif file_path.endswith('.html'):
            return 'template'
        elif file_path.endswith('.js'):
            return 'javascript'
        elif file_path.endswith('.css'):
            return 'css'
        elif file_path.endswith('.json'):
            return 'json'
        return 'generic'

    @database_sync_to_async
    def get_project(self):
        """Get project with proper database routing"""
        try:
            return Project.objects.using(thread_local.db_alias).get(id=self.project_id)
        except Project.DoesNotExist:
            logger.error(f"Project {self.project_id} not found")
            return None
        except Exception as e:
            logger.error(f"Error getting project: {str(e)}")
            return None

    @database_sync_to_async
    def get_user_from_token(self, token):
        """Get user from JWT token"""
        try:
            # Clean the token string
            token = token.strip()
            access_token = AccessToken(token)
            
            # Get user ID from token payload
            user_id = access_token.payload.get('user_id')
            if not user_id:
                logger.error("No user_id in token payload")
                return None
                
            # Get user from database
            user = User.objects.select_related().get(id=user_id)
            return user
            
        except (TokenError, InvalidToken) as e:
            logger.error(f"Token validation error: {str(e)}")
            return None
        except User.DoesNotExist:
            logger.error(f"User not found for token")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in token validation: {str(e)}")
            return None

    @database_sync_to_async
    def check_project_access(self, project_id, user):
        """Check if user has access to project"""
        try:
            # Always use the default DB for Project
            has_access = Project.objects.using('default').filter(
                id=project_id
            ).filter(
                Q(user=user) | Q(visibility='public')
            ).exists()
            
            if DEBUG_CONSUMER:
                logger.info(f"Project access check for user {user.username}, project {project_id}: {has_access}")
                
            return has_access
        except Exception as e:
            logger.error(f"Error checking project access: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    @database_sync_to_async
    def create_conversation(self, project_id, user, app_name=None, file_path=None):
        """Create or get conversation for project"""
        try:
            project = Project.objects.using('default').get(id=project_id)
            
            # Get user from the same database as the project
            project_user = User.objects.using('default').get(id=user.id)
            
            # First try to get an active conversation
            conversation = AIConversation.objects.using('default').filter(
                project=project,
                user=project_user,
                app_name=app_name,
                file_path=file_path,
                status='active'
            ).first()
            
            if conversation:
                return conversation
                
            # If no active conversation exists, create a new one
            conversation = AIConversation.objects.using('default').create(
                project=project,
                user=project_user,
                app_name=app_name,
                file_path=file_path,
                status='active'
            )
            
            return conversation
            
        except Project.DoesNotExist:
            logger.error(f"Project {project_id} not found")
            return None
        except Exception as e:
            logger.error(f"Error creating conversation: {str(e)}")
            return None

    @database_sync_to_async
    def save_message(self, conversation_id, sender, text):
        """Save message to conversation"""
        conversation = AIConversation.objects.get(id=conversation_id)
        return AIMessage.objects.create(
            conversation=conversation,
            sender=sender,
            text=text
        )

    @database_sync_to_async
    def get_change_request(self, change_id):
        """Get change request by ID"""
        return AIChangeRequest.objects.using('default').get(id=change_id)

    @database_sync_to_async
    def update_change_request_status(self, change_id, status):
        """Update change request status"""
        change = AIChangeRequest.objects.using('default').get(id=change_id)
        change.status = status
        change.save(using='default')
        return change

    @database_sync_to_async
    def get_project_files(self, project_id):
        """Get all files for project with proper content handling using FileIndexer, using canonical DB paths."""
        try:
            thread_local.project_id = project_id
            thread_local.db_alias = f"project_{project_id}"
            
            FileIndexer.load_index(project_id) # Ensure index is loaded for the project
            
            candidates = FileIndexer.get_candidates(project_id)
            files = {}
            
            # Mapping from model class name to simple file type string
            model_name_to_file_type = {
                'TemplateFile': 'templates',
                'StaticFile': 'static',
                'ModelFile': 'models',
                'ViewFile': 'views',
                'FormFile': 'forms',
                'AppFile': 'app_code', 
                'ProjectFile': 'project_code',
                'URLFile': 'urls',
                'SettingsFile': 'settings',
                # Add other specific model mappings if they exist
            }

            for canonical_path in candidates:
                content = FileIndexer.get_content(project_id, canonical_path)
                file_instance = FileIndexer.find_file(project_id, canonical_path)
                
                file_type_str = 'unknown'
                app_name_str = None
                app_id_int = None

                if file_instance:
                    model_class_name = file_instance.__class__.__name__
                    file_type_str = model_name_to_file_type.get(model_class_name, 'unknown')
                    
                    # Handle App relationship by fetching explicitly from default database
                    if hasattr(file_instance, 'app_id') and file_instance.app_id:
                        from create_api.models import App
                        try:
                            # Explicitly use default database for App lookup
                            app_obj = App.objects.using('default').get(id=file_instance.app_id)
                            app_name_str = app_obj.name
                            app_id_int = app_obj.id
                        except Exception as e:
                            logging.error(f"Error fetching App with ID {file_instance.app_id}: {str(e)}")
                            app_name_str = None
                            app_id_int = None
                    # Don't use file_instance.app directly as it may try to use the wrong database
                else:
                    # Fallback if instance not found - this should ideally not happen if path is from candidates
                    logger.warning(f"[ProjectConsumer] File instance not found for candidate path: {canonical_path}. Attempting to infer type from path.")
                    if '/' in canonical_path:
                        # Basic inference based on known prefixes
                        prefix = canonical_path.split('/')[0]
                        if prefix in ['templates', 'static', 'models', 'views', 'forms', 'apps', 'urls']:
                            file_type_str = prefix
                        elif any(keyword in canonical_path.lower() for keyword in ['.py', '.html', '.css', '.js']):
                             file_type_str = 'generic_code' # A generic type if prefix doesn't match but looks like code
                    elif '.' in canonical_path: # e.g. manage.py, README.md
                         file_type_str = 'project_code'


                files[canonical_path] = {
                    'content': content,
                    'type': file_type_str,
                    'name': canonical_path.split('/')[-1], # Get filename
                    'app': app_name_str,
                    'app_id': app_id_int
                }
                # Use a distinct logger name or add more context to differentiate consumer logs from indexer logs
                logging.debug(f"[ProjectConsumer] Processed file: {canonical_path} (Assigned Type: {file_type_str}, App: {app_name_str})")
            
            logging.info(f"[ProjectConsumer] Total files processed for project {project_id}: {len(files)}")
            return files
        except Exception as e:
            logging.error(f"[ProjectConsumer] Critical error in get_project_files for project {project_id}: {str(e)}")
            logging.error(traceback.format_exc()) 
            return {}

    @database_sync_to_async
    def get_project_context(self, project_id):
        """Get project context for validation"""
        try:
            project = Project.objects.using('default').get(id=project_id)
            return {
                'project_id': project.id,
                'project_name': project.name,
                'apps': list(App.objects.using('default').filter(project=project).values('id', 'name')),
                'models': list(ModelFile.objects.using('default').filter(project=project).values('id', 'name', 'path')),
                'views': list(ViewFile.objects.using('default').filter(project=project).values('id', 'name', 'path')),
                'forms': list(FormFile.objects.using('default').filter(project=project).values('id', 'name', 'path')),
                'templates': list(TemplateFile.objects.using('default').filter(project=project).values('id', 'name', 'path')),
            }
        except Project.DoesNotExist:
            logger.error(f"Project {project_id} not found")
            return {}
        except Exception as e:
            logger.error(f"Error getting project context: {str(e)}")
            return {}

    async def prepare_preview_content(self, files):
        """Prepare preview content for the diff modal"""
        try:
            preview_content = {}
            for file_path, content in files.items():
                # Add file metadata
                preview_content[file_path] = {
                    'content': content,
                    'language': self._get_file_language(file_path),
                    'size': len(content),
                    'modified': datetime.datetime.now().isoformat()
                }
            return preview_content
        except Exception as e:
            logger.error(f"Error preparing preview content: {str(e)}")
            return None
            
    def _get_file_language(self, file_path: str) -> str:
        """Get language for syntax highlighting"""
        if file_path.endswith('.py'):
            return 'python'
        elif file_path.endswith('.html'):
            return 'html'
        elif file_path.endswith('.js'):
            return 'javascript'
        elif file_path.endswith('.css'):
            return 'css'
        elif file_path.endswith('.json'):
            return 'json'
        return 'plaintext'

    @database_sync_to_async
    def create_change_request(self, conversation_id, project_id, file_type, diff, files, app_name=None, file_path=None):
        """Create change request"""
        conversation = AIConversation.objects.using('default').get(id=conversation_id)
        project = Project.objects.using('default').get(id=project_id)
        return AIChangeRequest.objects.using('default').create(
            conversation=conversation,
            project=project,
            file_type=file_type,
            diff=diff,
            files=files,
            app_name=app_name,
            file_path=file_path,
            status='pending'
        )

    async def send_diff_modal(self, change_id, diff, files, preview_content=None):
        """Send diff modal with improved error handling"""
        try:
            # Parse the JSON data if needed
            diff_data = json.loads(diff) if isinstance(diff, str) else diff
            
            # Format files data for the frontend
            formatted_files = []
            for file_path, file_data in diff_data['files'].items():
                formatted_files.append({
                    'filePath': file_path,
                    'before': file_data.get('before', ''),
                    'after': file_data.get('after', ''),
                    'projectId': self.project_id,
                    'changeId': change_id,
                    'fileType': file_data.get('file_type'),
                    'isNew': file_data.get('is_new', False)
                })

            # Generate preview URLs
            preview_map = {
                'before': f"/projects/{self.project_id}/",
                'after': f"/projects/{self.project_id}/preview/{change_id}/"
            }

            # Prepare message data
            message_data = {
                'type': 'show_diff_modal',
                'change_id': change_id,
                'files': formatted_files,
                'previewMap': preview_map,
                'timestamp': datetime.datetime.now().isoformat()
            }

            # Send or queue the message
            if self.is_connected and not self.is_closing:
                await self.send(text_data=json.dumps(message_data))
                logger.info("Diff modal sent successfully")
            else:
                logger.warning("Connection not ready, queueing diff modal")
                await self.message_queue.put(message_data)

        except Exception as e:
            logger.error(f"Error sending diff modal: {str(e)}")
            logger.error(traceback.format_exc())
            if not self.is_closing:
                await self.message_queue.put(message_data)

    async def handle_analytics_request(self, data):
        """Handle analytics data request with direct AI calls for each model type"""
        try:
            if not self.user or not self.project_id:
                await self.send_error_safe("Not authenticated or missing project context")
                return

            # Get project models
            models = await self.get_project_models()
            if not models:
                await self.send_error_safe("No models found for analytics")
                return

            # Process each model type separately with AI-generated files
            analytics_data = {}
            processed_files = set()  # Track processed files to avoid duplicates

            for model_type, model in models.items():
                try:
                    # Skip if we've already processed this model type
                    if model_type in processed_files:
                        continue

                    # Get sample data for AI context
                    sample_data = await self._get_model_sample_data(model)
                    
                    # Get analytics with AI-generated files for this model type
                    model_analytics = await self._get_model_analytics_direct(
                        {
                            'name': model.__name__,
                            'app_label': model._meta.app_label,
                            'model_name': model._meta.model_name,
                            'fields': [f.name for f in model._meta.fields]
                        },
                        sample_data,
                        timezone.now() - timedelta(days=data.get('days', 10)),
                        timezone.now(),
                        model_type
                    )
                    
                    if model_analytics:
                        analytics_data[model_type] = model_analytics
                        processed_files.add(model_type)
                except Exception as e:
                    logger.error(f"Error processing {model_type} analytics: {str(e)}")
                    continue

            # Send analytics data only if we have data to send
            if analytics_data:
                try:
                    await self.send(text_data=json.dumps({
                        'type': 'analytics_update',
                        'data': analytics_data
                    }))
                except Exception as e:
                    logger.error(f"Error sending analytics data: {str(e)}")
                    await self.send_error_safe("Error updating analytics display")
            else:
                await self.send_error_safe("No analytics data available")

        except Exception as e:
            logger.error(f"Error processing analytics request: {str(e)}")
            await self.send_error_safe(f"Error processing analytics request: {str(e)}")

    async def _get_model_analytics_direct(self, model_info, sample_data, start_date, end_date, model_name):
        """Make a direct AI call for a specific model type with dynamic file generation"""
        try:
            # Prepare request for AI
            analytics_request = {
                'type': 'analytics_request',
                'model_info': model_info,
                'sample_data': sample_data,
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'request_type': 'analytics_files',
                'required_files': [
                    'static/css/analytics.css',
                    'static/js/analytics.js'
                ]
            }

            # Get AI response with generated files
            ai_response = await self.call_ai_service({
                'task': 'generate_analytics',
                'context': analytics_request,
                'generate_files': True
            })

            if not ai_response or not isinstance(ai_response, dict):
                raise ValueError("Invalid AI response format")

            # Process the AI-generated files and data
            if 'files' in ai_response and isinstance(ai_response['files'], dict):
                for file_path, content in ai_response['files'].items():
                    if not isinstance(content, str):
                        logger.warning(f"Invalid content type for {file_path}: {type(content)}")
                        continue

                    try:
                        # Validate file content before saving
                        validator = DjangoCodeValidator()
                        is_valid, issues = validator.validate_file(file_path, content)
                        
                        if not is_valid:
                            logger.error(f"Validation failed for {file_path}: {issues}")
                            continue

                        # Apply validated changes
                        await self.apply_file_change(self.project_id, file_path, content)
                        logger.info(f"Successfully applied changes to {file_path}")
                    except Exception as e:
                        logger.error(f"Error applying changes to {file_path}: {str(e)}")
                        continue

            # Return the analytics data
            return ai_response.get('data')

        except Exception as e:
            logger.error(f"Error getting analytics for {model_name}: {str(e)}")
            return None

    @database_sync_to_async
    def _get_model_data(self, model, processor):
        """Get data for a specific model using the AI-generated processor"""
        try:
            query = processor.get('query', {})
            filters = query.get('filters', {})
            annotations = query.get('annotations', {})
            
            queryset = model.objects.filter(**filters)
            if annotations:
                queryset = queryset.annotate(**annotations)
            
            return list(queryset.values(*processor.get('fields', [])))
        except Exception as e:
            logger.error(f"Error getting model data: {str(e)}")
            return None

    async def _transform_data(self, data, processor):
        """Transform data using AI-generated processor rules"""
        try:
            transform_rules = processor.get('transform_rules', {})
            if not transform_rules:
                return data

            transformed_data = []
            for item in data:
                transformed_item = await self._apply_transform(item, transform_rules)
                if transformed_item:
                    transformed_data.append(transformed_item)

            return {
                'data': transformed_data,
                'config': processor.get('config', {})
            }

        except Exception as e:
            logger.error(f"Error transforming data: {str(e)}")
            return None

    async def _apply_transform(self, item, transform_rules):
        """Apply transformation rules to a data item"""
        try:
            result = {}
            for field, rule in transform_rules.items():
                if field in item:
                    if rule.get('type') == 'date':
                        result[field] = item[field].isoformat() if item[field] else None
                    elif rule.get('type') == 'number':
                        result[field] = float(item[field]) if item[field] is not None else 0
                    else:
                        result[field] = item[field]
            return result
        except Exception as e:
            logger.error(f"Error applying transform: {str(e)}")
            return None

    @database_sync_to_async
    def _get_model_sample_data(self, model, limit=10):
        """Get sample data for a model to provide context to AI"""
        try:
            return list(model.objects.filter(
                user=self.user,
                created__gte=timezone.now() - timedelta(days=30)
            ).order_by('-created')[:limit].values())
        except Exception as e:
            logger.error(f"Error getting sample data: {str(e)}")
            return []

    @database_sync_to_async
    def get_project_models(self):
        """Get available models for project"""
        try:
            models = {}
            app_label = f'project_{self.project_id}_posts'
            
            # Try to get available models
            try:
                models['posts'] = apps.get_model(app_label, 'Post')
            except LookupError:
                logger.warning(f"Post model not found for {app_label}")
                
            try:
                models['comments'] = apps.get_model(app_label, 'Comment')
            except LookupError:
                logger.warning(f"Comment model not found for {app_label}")
                
            return models
        except Exception as e:
            logger.error(f"Error getting project models: {str(e)}")
            return None

    async def send_error_safe(self, message, code=None):
        """Send error message with improved connection handling"""
        try:
            error_data = {
                'type': 'error',
                'message': str(message)
            }
            if code:
                error_data['code'] = code

            if self.is_connected and not self.is_closing:
                try:
                    await self.send(text_data=json.dumps(error_data))
                except Exception as e:
                    logger.error(f"Error sending error message: {str(e)}")
                    await self.message_queue.put(error_data)
            else:
                logger.warning("Connection closed, queueing error message")
                await self.message_queue.put(error_data)

        except Exception as e:
            logger.error(f"Error in send_error_safe: {str(e)}")
            # At this point, we can't do much more than log the error

    async def update_template_file(self, path, content):
        """Update or create a template file with AI-generated content"""
        try:
            # Get the full path for the template
            template_dir = os.path.join(settings.BASE_DIR, 'templates')
            full_path = os.path.join(template_dir, path)

            # Create directories if they don't exist
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # Write the template content
            async with aiofiles.open(full_path, 'w') as f:
                await f.write(content)

        except Exception as e:
            logger.error(f"Error updating template file {path}: {str(e)}")
            raise

    async def update_processor_file(self, path, content):
        """Update or create a processor file with AI-generated content"""
        try:
            # Get the full path for the processor
            processor_dir = os.path.join(settings.BASE_DIR, 'processors')
            full_path = os.path.join(processor_dir, path)

            # Create directories if they don't exist
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # Write the processor content
            async with aiofiles.open(full_path, 'w') as f:
                await f.write(content)

        except Exception as e:
            logger.error(f"Error updating processor file {path}: {str(e)}")
            raise

    @database_sync_to_async
    def apply_file_change(self, project_id, file_path, content, file_type=None):
        """Apply file change to the database"""
        try:
            project = Project.objects.using('default').get(id=project_id)
            
            # Determine the file type based on the path
            model_class = None
            if file_path.startswith('templates/') or file_path.endswith('.html'):
                model_class = TemplateFile
            elif file_path.startswith('views/') or file_path.endswith('.py'):
                model_class = ViewFile
            elif file_path.startswith('models/'):
                model_class = ModelFile
            elif file_path.startswith('forms/'):
                model_class = FormFile
            elif file_path.startswith('static/'):
                model_class = StaticFile
            else:
                model_class = AppFile

            # Try to find the file
            file_obj = model_class.objects.using('default').filter(project=project, path=file_path).first()
            
            if file_obj:
                # Update existing file
                file_obj.content = content
                if hasattr(file_obj, 'file_type') and file_type:
                    file_obj.file_type = file_type
                file_obj.save(using='default')
                logger.info(f"Updated file: {file_path}")
            else:
                # Create new file
                # Determine if this file belongs to an app
                app = None
                for app_obj in App.objects.using('default').filter(project=project):
                    if app_obj.name.lower() in file_path.lower():
                        app = app_obj
                        break

                # Create file with proper attributes
                create_kwargs = {
                    'project': project,
                    'path': file_path,
                    'name': os.path.basename(file_path),
                    'content': content
                }

                # Add app reference if model supports it and app was found
                if hasattr(model_class, 'app') and app:
                    create_kwargs['app'] = app

                # Add file_type for StaticFile
                if model_class == StaticFile and file_type:
                    create_kwargs['file_type'] = file_type
                    # Create ContentFile for the file field
                    create_kwargs['file'] = ContentFile(content.encode(), name=os.path.basename(file_path))

                file_obj = model_class.objects.using('default').create(**create_kwargs)
                logger.info(f"Created new file: {file_path}")

            return True
        except Exception as e:
            logger.error(f"Error applying file change: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    @database_sync_to_async
    def update_conversation_status(self, conversation_id: int, status: str) -> None:
        """Update the conversation status in the database"""
        try:
            conversation = AIConversation.objects.using('default').get(id=conversation_id)
            conversation.status = status
            conversation.save(using='default')  # Explicitly use default database
            logger.info(f"Updated conversation {conversation_id} status to {status}")
        except Exception as e:
            logger.error(f"Error updating conversation status: {str(e)}")
            logger.error(traceback.format_exc())

    async def process_ai_response(self, response):
        """Process AI response and create change request"""
        try:
            if not response or not isinstance(response, dict):
                await self.send_error_safe("Invalid AI response format")
                return

            # Extract files and changes
            files = response.get('files', {})
            if not isinstance(files, dict):
                await self.send_error_safe("Invalid files format in AI response")
                return

            if not files:
                await self.send_error_safe("No file changes generated")
                return

            # Process each file - but don't create them yet, just prepare the diff
            processed_files = []
            diff_data = {'files': {}}
            
            for file_path, content in files.items():
                # Check if file exists
                file_exists = await self.file_exists(self.project_id, file_path)
                
                # Get file type for static files
                file_type = None
                if file_path.startswith('static/'):
                    if file_path.endswith('.js'):
                        file_type = 'js'
                    elif file_path.endswith('.css'):
                        file_type = 'css'
                    elif any(file_path.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']):
                        file_type = 'img'
                    else:
                        file_type = 'other'

                # Get original content if file exists
                original_content = ''
                if file_exists:
                    original_content = await self.get_file_content(self.project_id, file_path)

                # Add to diff data
                diff_data['files'][file_path] = {
                    'before': original_content,
                    'after': content,
                    'file_type': file_type,
                    'is_new': not file_exists
                }
                processed_files.append(file_path)

            # Create change request with the complete diff data
            change_request = await self.create_change_request(
                conversation_id=self.conversation.id,
                project_id=self.project_id,
                file_type='mixed',  # Since we can have multiple file types
                diff=json.dumps(diff_data),
                files=processed_files,
                app_name=getattr(self, 'app_name', None),
                file_path=getattr(self, 'file_path', None)
            )

            # Prepare preview content
            preview_content = await self.prepare_preview_content(files)

            # Send diff modal data
            await self.send_diff_modal(change_request.id, diff_data, processed_files, preview_content)

            # Send response with change request ID
            await self.send(text_data=json.dumps({
                'type': 'changes_generated',
                'change_id': change_request.id,
                'files': processed_files,
                'description': response.get('description', 'Generated code changes')
            }))

        except Exception as e:
            logger.error(f"Error processing AI response: {str(e)}")
            logger.error(traceback.format_exc())
            await self.send_error_safe(f"Error processing AI response: {str(e)}")

    @database_sync_to_async
    def get_file_content(self, project_id, file_path):
        """Get the content of an existing file"""
        try:
            # Determine model class based on file path
            if file_path.startswith('templates/') or file_path.endswith('.html'):
                model_class = TemplateFile
            elif file_path.startswith('static/'):
                model_class = StaticFile
            elif file_path.startswith('views/') or file_path.endswith('.py'):
                model_class = ViewFile
            elif file_path.startswith('models/'):
                model_class = ModelFile
            elif file_path.startswith('forms/'):
                model_class = FormFile
            else:
                model_class = AppFile

            file_obj = model_class.objects.using('default').filter(
                project_id=project_id,
                path=file_path
            ).first()

            return file_obj.content if file_obj else ''
        except Exception as e:
            logger.error(f"Error getting file content: {str(e)}")
            return ''

    @database_sync_to_async
    def file_exists(self, project_id, file_path):
        """Check if a file exists in the project"""
        try:
            # Determine model class based on file path
            if file_path.startswith('templates/') or file_path.endswith('.html'):
                model_class = TemplateFile
            elif file_path.startswith('static/'):
                model_class = StaticFile
            elif file_path.startswith('views/') or file_path.endswith('.py'):
                model_class = ViewFile
            elif file_path.startswith('models/'):
                model_class = ModelFile
            elif file_path.startswith('forms/'):
                model_class = FormFile
            else:
                model_class = AppFile

            return model_class.objects.using('default').filter(
                project_id=project_id,
                path=file_path
            ).exists()
        except Exception as e:
            logger.error(f"Error checking file existence: {str(e)}")
            return False
