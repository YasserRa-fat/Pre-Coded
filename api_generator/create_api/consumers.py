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
from core.services.ai_editor import make_ai_api_call
from core.services.ai_editor import sanitize_ai_response
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
import re
from core.services.json_validator import JSONValidator

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
        self.retry_delay = 1  # seconds - Add retry_delay for message queue
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
        """Process messages in the queue with improved error handling and reconnection"""
        while not self.is_closing:
            try:
                if not self.is_connected:
                    # Wait for reconnection
                    await asyncio.sleep(self.retry_delay)
                    continue
                    
                try:
                    # Get message with timeout
                    message = await asyncio.wait_for(
                        self.message_queue.get(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue
                    
                # Try to send the message with retries
                max_retries = 3
                retry_delay = 1  # seconds
                
                for attempt in range(max_retries):
                    try:
                        if not self.is_connected or self.is_closing:
                            logger.warning(f"Connection lost during message processing (attempt {attempt + 1})")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                            continue
                            
                        await self.send(text_data=json.dumps(message))
                        logger.debug(f"Successfully sent queued message of type: {message.get('type')}")
                        self.message_queue.task_done()
                        break  # Message sent successfully
                        
                    except (ConnectionClosedOK, ConnectionClosedError) as e:
                        logger.warning(f"Connection closed while sending queued message (attempt {attempt + 1}): {str(e)}")
                        self.is_connected = False
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            
                    except Exception as e:
                        logger.error(f"Error sending queued message (attempt {attempt + 1}): {str(e)}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                
                # If all retries failed, requeue the message unless shutting down
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

                # First call to analyze which files need to be modified - with stronger guidance
                analysis_prompt = (
                    f"Analyze which existing files need to be modified for this request. "
                    f"Consider the project structure and app context. Request: {text}\n\n"
                    f"Project Context:\n"
                    f"- Project ID: {self.project_id}\n"
                    f"- Apps: {', '.join(app['name'] for app in project_context['apps'])}\n\n"
                    f"Available files:\n" + 
                    "\n".join(f"- {path} (type: {info['type']}, app: {info['app']})" for path, info in project_files.items()) +
                    "\n\nIMPORTANT NOTES:\n"
                    "1. KEEP ALL EXISTING FILE STRUCTURE - do not remove {% extends %} tags or other structural elements\n"
                    "2. DO NOT add markdown tags like ```html in the actual file content\n"
                    "3. Respect the app structure - 'posts' app contains post-related views and models\n"
                    "4. All HTML templates should preserve their existing structure\n"
                    "5. Consider app context and dependencies when selecting files."
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
                    
                    # Log detailed information for debugging
                    logger.debug(f"Looking up file: '{file_path}', normalized to '{normalized_path}'")
                    logger.debug(f"Available project files: {list(project_files.keys())}")
                    
                    # Try different path variations
                    variations = [
                        normalized_path,
                        f"{project_files[normalized_path]['type']}/{normalized_path}" if normalized_path in project_files else None,
                        normalized_path[normalized_path.find('/')+1:] if '/' in normalized_path else None
                    ]
                    
                    # Add additional path variations for more flexibility
                    if '/' in normalized_path:
                        app_name, rest = normalized_path.split('/', 1)
                        variations.append(rest)  # Try without app prefix
                        if rest == 'views.py':
                            variations.append(f"{app_name}/views.py")  # Try explicit form for views.py
                    
                    logger.debug(f"Trying path variations: {variations}")
                    
                    for path in variations:
                        if path and path in project_files:
                            file_info = project_files[path]
                            normalized_path = path
                            logger.debug(f"Found match with variation: '{path}'")
                            break
                    
                    if not file_info:
                        # Use FileIndexer's full power to find the file - it has more robust path handling
                        from core.services.file_indexer import FileIndexer
                        logger.debug(f"Initial lookup for '{file_path}' failed, trying FileIndexer directly")
                        
                        # Add extensive debugging to understand what files are available
                        candidates = FileIndexer.get_candidates(self.project_id)
                        logger.debug(f"All available file candidates: {candidates}")
                        
                        # Get exact normalized search path for verbose logging
                        search_path = FileIndexer._normalize_path(file_path)
                        logger.debug(f"Normalized search path: '{search_path}'")
                        
                        # Try to find the file using the more robust FileIndexer.find_file method
                        file_instance = FileIndexer.find_file(self.project_id, file_path)
                        
                        if file_instance:
                            file_content = file_instance.content
                            
                            # If we found the file, create the file_info structure
                            logger.info(f"Found file '{file_path}' via FileIndexer direct lookup")
                            model_class_name = file_instance.__class__.__name__
                            
                            # Determine file type
                            file_type = None
                            if model_class_name == 'ViewFile':
                                file_type = 'views'
                            elif model_class_name == 'ModelFile':
                                file_type = 'models'
                            elif model_class_name == 'FormFile':
                                file_type = 'forms'
                            elif model_class_name == 'TemplateFile':
                                file_type = 'templates'
                            elif model_class_name == 'StaticFile':
                                file_type = 'static'
                            else:
                                file_type = 'generic_code'
                            
                            # Create app structure 
                            app_name = None
                            app_id = None
                            if hasattr(file_instance, 'app_id') and file_instance.app_id:
                                from create_api.models import App
                                try:
                                    app_obj = App.objects.using('default').get(id=file_instance.app_id)
                                    app_name = app_obj.name
                                    app_id = app_obj.id
                                except Exception as e:
                                    logger.error(f"Error getting app info: {e}")
                            
                            # Create file info structure
                            file_info = {
                                'content': file_content,
                                'type': file_type,
                                'name': file_path.split('/')[-1],
                                'app': app_name,
                                'app_id': app_id
                            }
                            
                            # Set the normalized_path to the actual file path
                            normalized_path = file_path
                        else:
                            logger.warning(f"File '{file_path}' not found even with direct FileIndexer lookup")
                            continue
                    
                    # Make sure we have a valid file_info before proceeding
                    if not file_info:
                        logger.error(f"Failed to find file '{file_path}' using all lookup methods")
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
        """Create or get conversation for project with improved error handling and fallback"""
        try:
            project = Project.objects.using('default').get(id=project_id)
            
            # First try to get an active conversation to avoid new creation
            conversation = AIConversation.objects.using('default').filter(
                project=project,
                user_id=user.id,  # Use user_id foreign key directly
                app_name=app_name,
                file_path=file_path,
                status='active'
            ).first()
            
            if conversation:
                return conversation
                
            # If no active conversation exists, create a new one with error handling
            try:
                # Try to create with the project's user instance
                conversation = AIConversation.objects.using('default').create(
                    project=project,
                    user_id=user.id,  # Use user_id instead of user object
                    app_name=app_name,
                    file_path=file_path,
                    status='active'
                )
                return conversation
            except Exception as db_error:
                logger.warning(f"Primary creation method failed: {str(db_error)}")
                
                # Fallback: Create temporary conversation object in memory
                # This allows the websocket connection to work but won't persist conversations
                from django.utils import timezone
                
                class TemporaryConversation:
                    def __init__(self):
                        self.id = f"temp_{int(time.time())}"
                        self.project_id = project_id
                        self.user_id = user.id
                        self.app_name = app_name
                        self.file_path = file_path
                        self.status = 'active'
                        self.created_at = timezone.now()
                
                logger.info(f"Created temporary conversation {project_id} for user {user.username}")
                return TemporaryConversation()
            
        except Project.DoesNotExist:
            logger.error(f"Project {project_id} not found")
            return None
        except Exception as e:
            logger.error(f"Error creating conversation: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Return a minimal temporary conversation object to allow connection
            from django.utils import timezone
            
            class TemporaryConversation:
                def __init__(self):
                    self.id = f"temp_{int(time.time())}"
                    self.project_id = project_id
                    self.user_id = user.id if user else None
                    self.app_name = app_name
                    self.file_path = file_path
                    self.status = 'active'
                    self.created_at = timezone.now()
            
            logger.info(f"Created fallback temporary conversation for project {project_id}")
            return TemporaryConversation()

    @database_sync_to_async
    def save_message(self, conversation_id, sender, text):
        """Save message to conversation with support for temporary conversations"""
        # Check if we're using a temporary conversation (non-numeric ID)
        if hasattr(self.conversation, 'id') and isinstance(self.conversation.id, str) and self.conversation.id.startswith('temp_'):
            logger.info(f"Message for temporary conversation {conversation_id} not persisted to database")
            # Create a minimal message object to satisfy the interface
            from django.utils import timezone
            
            class TemporaryMessage:
                def __init__(self):
                    self.id = f"temp_msg_{int(time.time())}"
                    self.conversation_id = conversation_id
                    self.sender = sender
                    self.text = text
                    self.created_at = timezone.now()
            
            return TemporaryMessage()
        
        try:
            # Normal flow for database-backed conversations
            conversation = AIConversation.objects.using('default').get(id=conversation_id)
            return AIMessage.objects.using('default').create(
                conversation=conversation,
                sender=sender,
                text=text
            )
        except Exception as e:
            logger.error(f"Error saving message: {str(e)}")
            # Return a placeholder message object
            from django.utils import timezone
            
            class TemporaryMessage:
                def __init__(self):
                    self.id = f"temp_msg_{int(time.time())}"
                    self.conversation_id = conversation_id
                    self.sender = sender
                    self.text = text
                    self.created_at = timezone.now()
            
            return TemporaryMessage()

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
        """Create change request with temporary conversation handling"""
        try:
            # Handle temporary conversations
            if isinstance(conversation_id, str) and conversation_id.startswith('temp_'):
                logger.info(f"Creating change request for temporary conversation {conversation_id}")
                project = Project.objects.using('default').get(id=project_id)
                
                # Create a change request without conversation link
                change_request = AIChangeRequest.objects.using('default').create(
                    project=project,
                    file_type=file_type,
                    diff=diff,
                    files=files,
                    app_name=app_name,
                    file_path=file_path,
                    status='pending'
                )
                return change_request
            
            # Normal flow for database-backed conversations
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
        except Exception as e:
            logger.error(f"Error creating change request: {str(e)}")
            logger.error(traceback.format_exc())
            
            # Return a minimal temporary change request object
            from django.utils import timezone
            
            class TemporaryChangeRequest:
                def __init__(self):
                    self.id = f"temp_change_{int(time.time())}"
                    self.project_id = project_id
                    self.file_type = file_type
                    self.diff = diff
                    self.files = files
                    self.app_name = app_name
                    self.file_path = file_path
                    self.status = 'pending'
                    self.created_at = timezone.now()
            
            logger.info(f"Created temporary change request for project {project_id}")
            return TemporaryChangeRequest()

    async def send_diff_modal(self, change_id, diff, files, preview_content=None):
        """Send diff modal with marker areas to guide backend implementation"""
        try:
            # Parse the JSON data if needed
            diff_data = json.loads(diff) if isinstance(diff, str) else diff
            
            # Format files data for the frontend
            formatted_files = []
            for file_path, file_data in diff_data['files'].items():
                # Get original and modified content
                before_content = file_data.get('before', '')
                after_content = file_data.get('after', '')
                
                # Ensure proper formatting and cleanup
                if isinstance(before_content, str):
                    before_content = before_content.replace('\\n', '\n').replace('\\"', '"')
                if isinstance(after_content, str):
                    after_content = after_content.replace('\\n', '\n').replace('\\"', '"')
                    # Remove any markdown code block markers
                    after_content = re.sub(r'```[a-z]*\n', '', after_content)
                    after_content = re.sub(r'```', '', after_content)
                
                # Include metadata about markers
                has_markers = '<!-- DJANGO-AI-ADD-START -->' in after_content or \
                            '<!-- DJANGO-AI-REMOVE-START -->' in after_content or \
                            '# DJANGO-AI-ADD-START' in after_content or \
                            '# DJANGO-AI-REMOVE-START' in after_content
                
                formatted_files.append({
                    'filePath': file_path,
                    'before': before_content,
                    'after': after_content,
                    'projectId': self.project_id,
                    'changeId': change_id,
                    'fileType': file_data.get('file_type'),
                    'isNew': file_data.get('is_new', False),
                    'hasMarkers': has_markers
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

            # Try to send message with retries
            max_retries = 3
            retry_delay = 1
            
            for attempt in range(max_retries):
                try:
                    if self.is_connected and not self.is_closing:
                        await self.send(text_data=json.dumps(message_data))
                        logger.info("Diff modal sent successfully")
                        return
                    else:
                        logger.warning(f"Connection not ready (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                except (ConnectionClosedOK, ConnectionClosedError) as e:
                    logger.warning(f"Connection closed while sending diff modal (attempt {attempt + 1}): {str(e)}")
                    self.is_connected = False
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                except Exception as e:
                    logger.error(f"Error sending diff modal (attempt {attempt + 1}): {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)

            # If all retries failed, queue the message
            logger.info("All send attempts failed, queueing diff modal message")
            await self.message_queue.put(message_data)

        except Exception as e:
            logger.error(f"Error preparing diff modal: {str(e)}")
            logger.error(traceback.format_exc())
            # Ensure message_data is defined before attempting to queue it
            if 'message_data' in locals() and not self.is_closing:
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
        """Transform data using dynamic rules"""
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
        """Apply transformation rules dynamically"""
        try:
            result = {}
            
            # Get field type information if available
            field_types = {}
            if hasattr(item, '_meta'):
                for field in item._meta.fields:
                    field_types[field.name] = field.get_internal_type()

            for field, rule in transform_rules.items():
                if field not in item:
                    continue
                    
                value = item[field]
                if value is None:
                    result[field] = None
                    continue

                # Get rule type, falling back to inferring from field type
                rule_type = rule.get('type')
                if not rule_type and field in field_types:
                    django_type = field_types[field]
                    if 'Date' in django_type or 'Time' in django_type:
                        rule_type = 'date'
                    elif any(numeric in django_type for numeric in ['Integer', 'Float', 'Decimal']):
                        rule_type = 'number'

                # Apply transformation based on type
                if rule_type == 'date':
                    if hasattr(value, 'isoformat'):
                        result[field] = value.isoformat()
                    else:
                        result[field] = str(value)
                elif rule_type == 'number':
                    try:
                        result[field] = float(value)
                    except (ValueError, TypeError):
                        result[field] = 0
                else:
                    result[field] = value

            return result
        except Exception as e:
            logger.error(f"Error applying transform: {str(e)}")
            return None

    @database_sync_to_async
    def _get_model_sample_data(self, model, limit=10):
        """Get sample data for a model dynamically"""
        try:
            # Get model fields to determine what to filter by
            fields = [f.name for f in model._meta.fields]
            
            # Build query filters dynamically
            filters = {}
            
            # Add user filter if model has user field and we have a user
            if 'user' in fields and self.user:
                filters['user'] = self.user
                
            # Add date filter if model has relevant date fields
            date_fields = [f for f in fields if f in ['created', 'created_at', 'date_created', 'modified', 'updated_at']]
            if date_fields:
                from django.utils import timezone
                from datetime import timedelta
                filters[f"{date_fields[0]}__gte"] = timezone.now() - timedelta(days=30)
                order_by = f"-{date_fields[0]}"
            else:
                order_by = '-id'

            # Get the data with dynamic filtering
            queryset = model.objects.filter(**filters).order_by(order_by)[:limit]
            
            # Get all field values
            return list(queryset.values())
            
        except Exception as e:
            logger.error(f"Error getting sample data: {str(e)}")
            return []

    @database_sync_to_async
    def get_project_models(self):
        """Get available models for project dynamically"""
        try:
            models = {}
            project_apps = {}
            
            # Get all apps for the project from the default database
            from create_api.models import App
            project_apps = App.objects.using('default').filter(
                project_id=self.project_id
            ).values('id', 'name')

            # For each app, try to get its models
            for app in project_apps:
                app_label = f'project_{self.project_id}_{app["name"]}'
                try:
                    # Get all models for this app
                    app_models = apps.all_models.get(app_label, {})
                    for model_name, model in app_models.items():
                        # Store with a descriptive key based on app and model name
                        key = f"{app['name']}_{model_name}".lower()
                        models[key] = model
                        logger.debug(f"Found model: {key} in app {app_label}")
                except Exception as e:
                    logger.warning(f"Error getting models for app {app_label}: {str(e)}")
                    continue
                
            return models
        except Exception as e:
            logger.error(f"Error getting project models: {str(e)}")
            return None

    async def send_error_safe(self, message, code=None):
        """Send error message with improved connection handling and retries"""
        try:
            error_data = {
                'type': 'error',
                'message': str(message),
                'timestamp': datetime.datetime.now().isoformat()
            }
            if code:
                error_data['code'] = code

            # Try to send with retries
            max_retries = 3
            retry_delay = 1  # seconds
            
            for attempt in range(max_retries):
                try:
                    if self.is_connected and not self.is_closing:
                        await self.send(text_data=json.dumps(error_data))
                        logger.debug("Error message sent successfully")
                        return
                    else:
                        logger.warning(f"Connection not ready for error message (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                except (ConnectionClosedOK, ConnectionClosedError) as e:
                    logger.warning(f"Connection closed while sending error (attempt {attempt + 1}): {str(e)}")
                    self.is_connected = False
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                except Exception as e:
                    logger.error(f"Error sending error message (attempt {attempt + 1}): {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
            
            # If all retries failed, queue the message
            logger.warning("Connection unavailable, queueing error message")
            await self.message_queue.put(error_data)

        except Exception as e:
            logger.error(f"Critical error in send_error_safe: {str(e)}")
            logger.error(traceback.format_exc())
            # Try to queue even in case of critical error
            try:
                if not self.is_closing:
                    await self.message_queue.put(error_data)
            except Exception as queue_error:
                logger.error(f"Failed to queue error message: {str(queue_error)}")

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
    def update_conversation_status(self, conversation_id, status: str) -> None:
        """Update the conversation status in the database with temporary ID support"""
        # Skip updates for temporary conversations
        if isinstance(conversation_id, str) and conversation_id.startswith('temp_'):
            logger.info(f"Skipped status update for temporary conversation {conversation_id}")
            return
            
        try:
            conversation = AIConversation.objects.using('default').get(id=conversation_id)
            conversation.status = status
            conversation.save(using='default')  # Explicitly use default database
            logger.info(f"Updated conversation {conversation_id} status to {status}")
        except Exception as e:
            logger.error(f"Error updating conversation status: {str(e)}")
            logger.error(traceback.format_exc())

    async def process_ai_response(self, response):
        """Process AI response and send changes to client with dynamic handling"""
        try:
            # Extract response data
            logger.debug(f"Processing AI response: {str(response)[:200]}...")
            
            # Use the improved JSON validator
            is_valid, json_data, error = await JSONValidator.validate_and_parse(response)
            
            if not is_valid or not json_data:
                logger.error(f"Invalid AI response: {error}")
                await self.send_error_safe("Invalid response from AI service")
                return

            if not isinstance(json_data, dict) or 'files' not in json_data:
                logger.error("AI response does not contain 'files' key")
                await self.send_error_safe("Invalid response structure from AI")
                return

            files = json_data.get('files', {})
            if not files:
                logger.error("No files found in AI response")
                await self.send_error_safe("No file changes generated")
                return

            # Analyze the request to determine feature context
            feature_context = self._analyze_request_context(self.last_message) if hasattr(self, 'last_message') else {}
            logger.debug(f"Request feature context: {feature_context}")

            # Prepare diff data
            diff_data = {
                'files': {},
                'project_id': self.project_id
            }
            
            processed_files = []
            file_metadata = {}
            
            # Check for original file versions for diffing
            original_files = json_data.get('original_files', {})
            if original_files:
                logger.debug(f"Found {len(original_files)} original files for diffing")
            
            # Process each file in the response
            for file_path, file_content in files.items():
                is_new_file = False
                file_path = file_path.strip()
                
                # Check if the file exists
                try:
                    original_content = await self.get_file_content(file_path, self.project_id)
                    if original_content is None:
                        # File doesn't exist, mark as new
                        is_new_file = True
                        original_content = ""
                except Exception as e:
                    logger.warning(f"Error retrieving original content for {file_path}: {str(e)}")
                    original_content = original_files.get(file_path, "")
                    is_new_file = not await self.file_exists(self.project_id, file_path)
                
                # Normalize new content
                if isinstance(file_content, dict):
                    new_content = file_content.get('content', "")
                else:
                    new_content = file_content
                    
                # Skip files with no changes
                if original_content == new_content:
                    logger.debug(f"No changes detected for {file_path}, skipping")
                    continue

                # Add marker areas for additions/removals
                changes_with_markers = self._add_marker_areas(original_content, new_content, file_path)
                
                # Determine file type
                file_type = self._get_file_type(file_path)
                
                # Get the view file if this is a template file with features
                if file_path.endswith('.html') and ('analytics' in feature_context or 'graph' in feature_context):
                    try:
                        view_file = await self.get_view_file_for_template([file_path])
                        if view_file:
                            logger.debug(f"Found associated view file for template: {view_file.path}")
                            # Add the view file to the processed files if it's not already included
                            if view_file.path not in files:
                                # Generate appropriate view content based on template features
                                view_content = await self.update_view_content(view_file.content, feature_context)
                                
                                # Add to the processed files list
                                processed_files.append({
                                    'filePath': view_file.path,
                                    'content': view_content
                                })
                                
                                # Add to diff data
                                diff_data['files'][view_file.path] = {
                                    'before': view_file.content,
                                    'after': view_content,
                                    'file_type': 'python',
                                    'is_new': False,
                                    'is_supporting': True  # Mark as a supporting file for the template
                                }
                    except Exception as e:
                        logger.error(f"Error processing associated view file: {str(e)}")
                
                # Add to diff data
                diff_data['files'][file_path] = {
                    'before': original_content,
                    'after': changes_with_markers,  # Use the content with markers
                    'file_type': file_type,
                    'is_new': is_new_file
                }
                
                # Add to processed files list
                processed_files.append({
                    'filePath': file_path,
                    'content': new_content
                })
                
                # Add file metadata for better processing
                file_metadata[file_path] = {
                    'type': file_type,
                    'is_new': is_new_file,
                    'has_markers': True
                }

            if not diff_data['files']:
                logger.warning("No changes identified in AI response")
                await self.send_error_safe("No changes were identified")
                return
                
            for path in diff_data['files'].keys():
                logger.debug(f"Including in diff: {path}")

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
            logger.info(f"Created change request ID: {change_request.id}")

            # Send diff modal data with complete content
            await self.send_diff_modal(change_request.id, diff_data, processed_files)
            logger.info(f"Sent diff modal for change request {change_request.id}")

            # Send response with change request ID
            await self.send(text_data=json.dumps({
                'type': 'changes_generated',
                'change_id': change_request.id,
                'files': processed_files,
                'description': response.get('description', 'Generated code changes'),
                'timestamp': datetime.datetime.now().isoformat()
            }))

        except Exception as e:
            logger.error(f"Error processing AI response: {str(e)}")
            logger.error(traceback.format_exc())
            await self.send_error_safe(f"Error processing AI response: {str(e)}")

    def _add_marker_areas(self, original_content, new_content, file_path):
        """
        Add marker areas to indicate sections that should be added or removed.
        Format:
        <!-- DJANGO-AI-ADD-START -->
        new content
        <!-- DJANGO-AI-ADD-END -->
        
        <!-- DJANGO-AI-REMOVE-START -->
        content to remove
        <!-- DJANGO-AI-REMOVE-END -->
        """
        try:
            # Split content into lines for diffing
            original_lines = original_content.splitlines() if original_content else []
            new_lines = new_content.splitlines() if new_content else []
            
            # Generate unified diff
            diff = list(difflib.unified_diff(
                original_lines,
                new_lines,
                n=0,  # No context lines to get exact changes only
                lineterm=''
            ))
            
            # Skip the header lines (first 2 lines)
            diff = diff[2:] if len(diff) > 2 else diff
            
            result_lines = original_lines.copy()
            offset = 0  # Track line offset as we insert/remove lines
            
            current_block = []
            current_action = None
            current_line = 0
            
            for line in diff:
                if line.startswith('@@'):
                    # Parse the @@ line to get starting line numbers
                    # Format: @@ -start,count +start,count @@
                    parts = line.split(' ')
                    if len(parts) >= 3:
                        # Extract line numbers
                        old_start = int(parts[1].split(',')[0][1:])
                        if ',' in parts[1]:
                            old_count = int(parts[1].split(',')[1])
                        else:
                            old_count = 1
                        
                        new_start = int(parts[2].split(',')[0][1:]) 
                        if ',' in parts[2]:
                            new_count = int(parts[2].split(',')[1])
                        else:
                            new_count = 1
                        
                        current_line = old_start - 1  # Convert to 0-based index
                        
                        # Process any pending block before moving to new location
                        if current_block and current_action:
                            # Insert the current block with markers
                            if current_action == '+':
                                marker_start = "<!-- DJANGO-AI-ADD-START -->"
                                marker_end = "<!-- DJANGO-AI-ADD-END -->"
                            else:  # '-' action
                                marker_start = "<!-- DJANGO-AI-REMOVE-START -->"
                                marker_end = "<!-- DJANGO-AI-REMOVE-END -->"
                                
                            insert_pos = current_line + offset
                            result_lines.insert(insert_pos, marker_start)
                            offset += 1
                            
                            for i, content_line in enumerate(current_block):
                                if current_action == '+':
                                    result_lines.insert(insert_pos + i + offset, content_line[1:])
                                    offset += 1
                                # For removals, we don't need to do anything as the lines are already there
                                
                            result_lines.insert(insert_pos + len(current_block) + offset, marker_end)
                            offset += 1
                            
                            # Reset the block
                            current_block = []
                            current_action = None
                
                elif line.startswith('+') or line.startswith('-'):
                    # Store the line and action if it's in the same block
                    if not current_action:
                        current_action = line[0]
                        current_block.append(line)
                    elif line[0] == current_action:
                        current_block.append(line)
                    else:
                        # Different action, process the current block
                        if current_action == '+':
                            marker_start = "<!-- DJANGO-AI-ADD-START -->"
                            marker_end = "<!-- DJANGO-AI-ADD-END -->"
                        else:  # '-' action
                            marker_start = "<!-- DJANGO-AI-REMOVE-START -->"
                            marker_end = "<!-- DJANGO-AI-REMOVE-END -->"
                            
                        insert_pos = current_line + offset
                        result_lines.insert(insert_pos, marker_start)
                        offset += 1
                        
                        for i, content_line in enumerate(current_block):
                            if current_action == '+':
                                result_lines.insert(insert_pos + i + 1, content_line[1:])
                                offset += 1
                            # For removals, we don't need to do anything
                            
                        result_lines.insert(insert_pos + len(current_block) + 1, marker_end)
                        offset += 1
                        
                        # Reset and start new block
                        current_block = [line]
                        current_action = line[0]
                        
                    # Update current line for '-' lines (removals)
                    if line.startswith('-'):
                        current_line += 1
            
            # Process any remaining block
            if current_block and current_action:
                if current_action == '+':
                    marker_start = "<!-- DJANGO-AI-ADD-START -->"
                    marker_end = "<!-- DJANGO-AI-ADD-END -->"
                else:  # '-' action
                    marker_start = "<!-- DJANGO-AI-REMOVE-START -->"
                    marker_end = "<!-- DJANGO-AI-REMOVE-END -->"
                    
                insert_pos = current_line + offset
                result_lines.insert(insert_pos, marker_start)
                offset += 1
                
                for i, content_line in enumerate(current_block):
                    if current_action == '+':
                        result_lines.insert(insert_pos + i + 1, content_line[1:])
                        offset += 1
                    
                result_lines.insert(insert_pos + len(current_block) + 1, marker_end)
            
            # Apply special formatting for Python files
            if file_path.endswith('.py'):
                return self._format_python_markers("\n".join(result_lines))
            
            # For HTML templates
            if file_path.endswith('.html'):
                return self._format_html_markers("\n".join(result_lines))
                
            # Default case - return the result directly
            return "\n".join(result_lines)
        
        except Exception as e:
            logger.error(f"Error adding marker areas: {str(e)}")
            logger.error(traceback.format_exc())
            # Return original content as fallback
            return new_content

    def _format_python_markers(self, content):
        """Format markers in Python code with appropriate comments"""
        # Replace HTML-style markers with Python comments
        content = content.replace("<!-- DJANGO-AI-ADD-START -->", "# DJANGO-AI-ADD-START")
        content = content.replace("<!-- DJANGO-AI-ADD-END -->", "# DJANGO-AI-ADD-END")
        content = content.replace("<!-- DJANGO-AI-REMOVE-START -->", "# DJANGO-AI-REMOVE-START")
        content = content.replace("<!-- DJANGO-AI-REMOVE-END -->", "# DJANGO-AI-REMOVE-END")
        return content

    def _format_html_markers(self, content):
        """Format markers in HTML templates with appropriate comments"""
        # Already using HTML comments, just ensure proper formatting
        return content

    @database_sync_to_async
    def get_file_content(self, file_path, project_id):
        """Get the content of an existing file"""
        try:
            logger.info(f"Getting content for file {file_path} in project {project_id}")
            # Determine model class based on file path
            if file_path.endswith('.html') or '/templates/' in file_path:
                model_class = TemplateFile
                logger.debug(f"Using TemplateFile model for {file_path}")
            elif file_path.startswith('static/') or '/static/' in file_path:
                model_class = StaticFile
                logger.debug(f"Using StaticFile model for {file_path}")
            elif 'views.py' in file_path or file_path.endswith('/views.py'):
                model_class = ViewFile
                logger.debug(f"Using ViewFile model for {file_path}")
            elif 'models.py' in file_path or file_path.endswith('/models.py'):
                model_class = ModelFile
                logger.debug(f"Using ModelFile model for {file_path}")
            elif 'forms.py' in file_path or file_path.endswith('/forms.py'):
                model_class = FormFile
                logger.debug(f"Using FormFile model for {file_path}")
            else:
                model_class = AppFile
                logger.debug(f"Using AppFile model for {file_path}")

            # Try to find the file with the exact path
            file_obj = model_class.objects.using('default').filter(
                project_id=project_id,
                path=file_path
            ).first()

            # If not found, try alternative paths based on project structure
            if not file_obj:
                logger.debug(f"File not found with exact path {file_path}, trying alternatives")
                # Strip app prefix if present (e.g., 'posts/views.py' -> 'views.py')
                base_path = file_path.split('/')[-1] if '/' in file_path else file_path
                file_obj = model_class.objects.using('default').filter(
                    project_id=project_id,
                    path__endswith=base_path
                ).first()
                
                if file_obj:
                    logger.info(f"Found file using endswith match: {file_obj.path}")

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

    @database_sync_to_async
    def get_view_file_for_template(self, template_files):
        """Get the corresponding view file for template changes"""
        try:
            # Find the first template file
            template_file = next((f for f in template_files if f.endswith('.html')), None)
            if not template_file:
                logger.warning("No template file found in template_files")
                return None

            logger.info(f"Finding view file for template: {template_file}")
            # Get the app name dynamically based on context and request
            app_name = None
            
            # First try to get from project context
            project_context = self.get_project_context(self.project_id)
            if project_context and project_context.get('apps'):
                logger.debug(f"Project has {len(project_context['apps'])} apps")
                
                # Extract app name from template path if possible
                template_parts = template_file.split('/')
                template_app = None
                
                # Check for app name in template path
                if len(template_parts) > 1:
                    # Handle templates/app/file.html or app/templates/file.html format
                    if template_parts[0] == 'templates' and len(template_parts) > 2:
                        template_app = template_parts[1]
                        logger.debug(f"Template app from templates/app/: {template_app}")
                    else:
                        template_app = template_parts[0]
                        logger.debug(f"Template app from first path part: {template_app}")
                
                # Try several strategies to find the right app
                possible_apps = []
                
                # 1. Check if template matches any app
                if template_app:
                    for app in project_context['apps']:
                        if app['name'].lower() == template_app.lower():
                            possible_apps.append((app['name'], 5)) # High priority
                            logger.debug(f"Found app match by template path: {app['name']}")
                
                # 2. Check if app name is in user request
                if hasattr(self, 'last_message') and self.last_message:
                    for app in project_context['apps']:
                        if app['name'].lower() in self.last_message.lower():
                            possible_apps.append((app['name'], 4)) # Medium-high priority
                            logger.debug(f"Found app match in user request: {app['name']}")
                
                # 3. Check actual file references
                for view_file in project_context.get('views', []):
                    if 'path' in view_file and 'app' in view_file and view_file['app']:
                        possible_apps.append((view_file['app'], 3)) # Medium priority
                        logger.debug(f"Found potential app from view file: {view_file['app']}")
                
                # 4. Find apps that have views - using direct DB calls is okay since we're inside a sync_to_async method
                for app in project_context['apps']:
                    # Check if app has views
                    view_exists = ViewFile.objects.using('default').filter(
                        project_id=self.project_id,
                        path__contains=f"{app['name']}/views").exists()
                    
                    if view_exists:
                        possible_apps.append((app['name'], 2)) # Low priority
                        logger.debug(f"App has views: {app['name']}")
                
                # 5. Default to first app as fallback
                if project_context['apps']:
                    possible_apps.append((project_context['apps'][0]['name'], 1)) # Lowest priority
                    logger.debug(f"Using first app as fallback: {project_context['apps'][0]['name']}")
                
                # Sort by priority and pick the highest
                if possible_apps:
                    possible_apps.sort(key=lambda x: x[1], reverse=True)
                    app_name = possible_apps[0][0]
                    logger.info(f"Selected app: {app_name} (priority: {possible_apps[0][1]})")
            
            if app_name:
                # Look for views.py in multiple possible locations
                view_paths = [
                    f"{app_name}/views.py",
                    f"apps/{app_name}/views.py",
                    f"{app_name.lower()}/views.py"
                ]
                
                # Get all view files for debugging to see what paths are actually available
                all_view_files = list(ViewFile.objects.using('default').filter(
                    project_id=self.project_id
                ).values_list('path', flat=True))
                logger.debug(f"All view files in project: {all_view_files}")
                
                # Try to find the view file in any of these locations
                for view_path in view_paths:
                    logger.debug(f"Checking for view at: {view_path}")
                    
                    view_exists = ViewFile.objects.using('default').filter(
                        project_id=self.project_id, 
                        path=view_path
                    ).exists()
                    
                    if view_exists:
                        logger.info(f"Found view file: {view_path}")
                        return view_path
                    
                    # Also try with endswith in case the path structure varies
                    view_file = ViewFile.objects.using('default').filter(
                        project_id=self.project_id,
                        path__endswith=f"/{view_path}"
                    ).first()
                    
                    if view_file:
                        logger.info(f"Found view file by endswith: {view_file.path}")
                        return view_file.path
                    
                    # Try a more flexible search approach
                    for candidate_path in all_view_files:
                        if app_name.lower() in candidate_path.lower() and 'views.py' in candidate_path.lower():
                            logger.info(f"Found view file by flexible matching: {candidate_path}")
                            return candidate_path

            # Fallback to main views.py or any views.py
            logger.info("Using fallback view file search")
            
            # Get all view files again (should already have them from above)
            all_view_files = list(ViewFile.objects.using('default').filter(
                project_id=self.project_id
            ).values_list('path', flat=True))
            
            logger.debug(f"Fallback view search - all view files: {all_view_files}")
            
            # First try to find views.py directly
            view_file = ViewFile.objects.using('default').filter(
                project_id=self.project_id,
                path="views.py"
            ).first()
            
            if view_file:
                logger.info(f"Found root views.py file")
                return "views.py"
                
            # Then try to find any views.py file
            view_file = ViewFile.objects.using('default').filter(
                project_id=self.project_id,
                path__contains="views.py"
            ).first()
            
            if view_file:
                logger.info(f"Found fallback view file: {view_file.path}")
                return view_file.path
            
            # Last resort, specifically look for posts/views.py
            view_file = ViewFile.objects.using('default').filter(
                project_id=self.project_id,
                path__contains="posts/views.py"
            ).first()
            
            if view_file:
                logger.info(f"Found posts/views.py file: {view_file.path}")
                return view_file.path
                
            # If nothing found, return a default path
            logger.warning("No view file found, using default views.py")
            return "views.py"
        except Exception as e:
            logger.error(f"Error getting view file: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    async def update_view_content(self, current_content, diff_data):
        """Update view content to support template changes - fully dynamic version"""
        try:
            # Get project context for potential use in view updates
            project_context = await self.get_project_context(self.project_id)
            
            # Analyze the view content to find class definitions
            import ast
            try:
                tree = ast.parse(current_content)
                class_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
                
                if not class_nodes:
                    logger.debug("No class definitions found in view content")
                return current_content

                # Find the main view class - typically the last class in the file
                main_view_class = class_nodes[-1].name
                logger.info(f"Found main view class: {main_view_class}")
                
            except SyntaxError:
                logger.error("Failed to parse view content")
                return current_content
            
            # Scan diff data to determine what needs to be added
            template_features = set()
            
            # Analyze all files to determine required features
            for file_path, file_data in diff_data['files'].items():
                file_content = file_data.get('after', '')
                metadata = file_data.get('file_metadata', {})
                
                # Extract features from file content and path
                features = self._extract_features_from_content(file_path, file_content)
                template_features.update(features)
                
                if metadata.get('is_template', False):
                    # Analyze template content for additional features
                    template_features.update(self._analyze_template_features(file_content))
            
            logger.debug(f"Detected template features: {template_features}")
            
            # Let the AI service handle the actual code generation
            # This ensures no hardcoded assumptions about imports or context data
            return await self._generate_view_content(
                current_content=current_content,
                template_features=template_features,
                project_context=project_context,
                main_class_name=main_view_class
            )

        except Exception as e:
            logger.error(f"Error updating view content: {str(e)}")
            logger.error(traceback.format_exc())
            return current_content

    def _extract_features_from_content(self, file_path: str, content: str) -> set:
        """Extract features from file content without hardcoding"""
        features = set()
        
        # Use regex to find Django template tags and features
        import re
        
        # Look for common Django patterns
        patterns = {
            'analytics': r'analytics|stats|metrics|tracking',
            'chart': r'chart|graph|plot|visualization',
            'form': r'{%\s*form|FormView|ModelForm',
            'list': r'ListView|{%\s*for\b',
            'detail': r'DetailView|get_object',
            'create': r'CreateView|form_valid',
            'update': r'UpdateView|form_valid',
            'delete': r'DeleteView|delete',
            'user': r'user\.|request\.user|login|auth',
            'api': r'api|JsonResponse|REST|endpoint',
            'static': r'{%\s*static|staticfiles|css|js',
            'media': r'media|upload|file|image',
            'search': r'search|query|filter',
            'pagination': r'page|paginate|Paginator',
            'comments': r'comment|discussion|reply',
            'notification': r'notification|alert|message'
                }
                
        # Check both file path and content
        text_to_check = f"{file_path.lower()} {content.lower()}"
        
        for feature, pattern in patterns.items():
            if re.search(pattern, text_to_check, re.I):
                features.add(feature)
                
        return features

    def _analyze_template_features(self, content: str) -> set:
        """Analyze template content for features without hardcoding"""
        features = set()
        
        # Look for template-specific patterns
        patterns = {
            'includes': r'{%\s*include',
            'extends': r'{%\s*extends',
            'blocks': r'{%\s*block',
            'forms': r'{%\s*csrf_token|<form',
            'static': r'{%\s*static|{%\s*load\s+static',
            'conditions': r'{%\s*if|{%\s*else',
            'loops': r'{%\s*for|{%\s*while',
            'filters': r'{{\s*.*\|\w+}}',
            'urls': r'{%\s*url|href=',
            'media': r'src=|media/',
            'messages': r'{%\s*if\s+messages|{{\s*message'
        }
        
        for feature, pattern in patterns.items():
            if re.search(pattern, content):
                features.add(feature)
                
        return features

    async def _generate_view_content(self, current_content: str, template_features: set, 
                                   project_context: dict, main_class_name: str) -> str:
        """Generate view content using AI service"""
        try:
            # Prepare the request for the AI service
            request_data = {
                'current_content': current_content,
                'features': list(template_features),
                'project_context': project_context,
                'main_class_name': main_class_name,
                'request_type': 'view_update'
            }
            
            # Call AI service to generate the view content
            response = await call_ai_multi_file(
                self.conversation,
                json.dumps(request_data),
                {'type': 'view_update', 'data': request_data}
            )
            
            if response and isinstance(response, dict):
                try:
                    # Extract the updated view content from the response
                    files = response.get('files', {})
                    
                    # Process each file to handle escaping properly
                    for file_path, content in files.items():
                        if file_path.endswith('views.py'):
                            # Handle potential string escaping issues
                            if isinstance(content, str):
                                # Remove any raw string markers
                                content = content.replace('r"""', '"""').replace("r'''", "'''")
                    
                                # Fix any double-escaped newlines
                                content = content.replace('\\\\n', '\\n')
                                
                                # Unescape any escaped quotes
                                content = content.replace("\\'", "'").replace('\\"', '"')
                                
                                # Handle any remaining invalid escapes
                                try:
                                    # Try to interpret as string literal
                                    content = ast.literal_eval(f"'''{content}'''")
                                except (SyntaxError, ValueError):
                                    # If that fails, just use the content as is
                                    pass
                                    
                            return content
                    
                    logger.warning("No views.py file found in AI response")
                    return current_content
                    
                except Exception as e:
                    logger.error(f"Error processing AI response content: {str(e)}")
                    return current_content
            
            logger.warning("AI service did not return valid view content")
            return current_content

        except Exception as e:
            logger.error(f"Error generating view content: {str(e)}")
            return current_content

    def _analyze_request_context(self, request_text):
        """
        Analyze request text to determine feature context without hardcoding
        """
        if not request_text:
            return {}
            
        try:
            context = {
                'keywords': [],
                'file_types': [],
                'features': []
            }
            
            # Extract significant terms from the request
            text_lower = request_text.lower()
            
            # Check for file-related terms
            if any(term in text_lower for term in ['template', 'html', 'page', 'view']):
                context['file_types'].append('template')
            
            if any(term in text_lower for term in ['static', 'css', 'js', 'javascript', 'style']):
                context['file_types'].append('static')
            
            if any(term in text_lower for term in ['view', 'function', 'controller', 'endpoint']):
                context['file_types'].append('view')
            
            if any(term in text_lower for term in ['model', 'data', 'database', 'field']):
                context['file_types'].append('model')
                
            # Extract potential feature terms
            for potential_feature in ['analytics', 'graph', 'chart', 'dashboard', 'login', 'user', 
                                     'form', 'upload', 'search', 'sort', 'filter', 'pagination',
                                     'comment', 'notification', 'message', 'profile', 'settings']:
                if potential_feature in text_lower:
                    context['features'].append(potential_feature)
                    
            # Extract all significant words as keywords
            important_words = [word.lower() for word in request_text.split() 
                              if len(word) > 3 and word.lower() not in ['the', 'and', 'that', 'this', 'have', 'from']]
            context['keywords'] = important_words[:10]  # Limit to top 10
            
            return context
            
        except Exception as e:
            logger.error(f"Error analyzing request context: {str(e)}")
            return {}