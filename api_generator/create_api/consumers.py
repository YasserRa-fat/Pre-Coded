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
import time
from collections import deque
from core.thread_local import thread_local

# Configure logger
logger = logging.getLogger(__name__)

class BasicProjectConsumer(AsyncWebsocketConsumer):
    """
    Extremely simplified WebSocket consumer with no caching.
    Focused solely on delivering AI responses in development environment.
    """
    
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
            
            # Wait a short time to ensure connection is stable before sending first message
            await asyncio.sleep(1)
            
            # Send success message
            success = await self.safe_send(json.dumps({
                'type': 'connection_established',
                'message': 'Connected successfully'
            }))
            
            if success:
                logger.info("Successfully sent connection_established message")
            else:
                logger.error("Failed to send connection_established message")
            
        except Exception as e:
            logger.error(f"Connection error: {str(e)}")
            logger.error(traceback.format_exc())
            await self.close(code=4000)

    async def disconnect(self, close_code):
        """Handle disconnect with proper cleanup"""
        logger.info(f"WebSocket disconnecting with code {close_code}")
        try:
            # Update conversation status if exists
            if hasattr(self, 'conversation') and self.conversation:
                await self.update_conversation_status(self.conversation.id, 'disconnected')
                
            # Clear any pending tasks
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
                
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error canceling tasks: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error during disconnect: {str(e)}")
        finally:
            # Always clear thread local
            thread_local.clear()
            logger.debug("Cleared thread_local context")

    async def safe_send(self, text_data):
        """Send message with error handling for disconnected clients"""
        if not text_data:
            logger.warning("Attempted to send empty message")
            return False
            
        try:
            if not self.scope or not hasattr(self, 'channel_name'):
                logger.error("Cannot send: channel not established")
                return False
                
            # Add small delay before sending to ensure connection is ready    
            await asyncio.sleep(0.1)
            
            if self.scope and hasattr(self, 'channel_name'):
                await self.send(text_data=text_data)
                return True
            else:
                logger.error("Channel lost before sending")
                return False
                
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            logger.debug(traceback.format_exc())
            return False

    async def receive(self, text_data):
        """Process incoming messages with simplified error handling"""
        if not text_data:
            return
            
        try:
            # Parse the message
            data = json.loads(text_data)
            
            # Log the raw message for debugging
            logger.debug(f"Received raw message: {text_data[:200]}...")
            
            # Handle ping messages to keep connection alive
            if data.get('type') == 'ping':
                logger.debug("Received ping, sending pong")
                try:
                    await self.safe_send(json.dumps({
                        "type": "pong"
                    }))
                except Exception as e:
                    logger.error(f"Error responding to ping: {str(e)}")
                return
                
            # Handle chat messages (both send_message and chat_message types)
            if data.get('type') in ['chat_message', 'send_message']:
                message_text = data.get('text', '').strip()
                if message_text:
                    # Log the request
                    logger.info(f"Received message: {message_text[:100]}...")
                    
                    try:
                        # Save user message
                        await self.save_message(self.conversation.id, 'user', message_text)
                        
                        # Wait briefly before sending response to ensure stability
                        await asyncio.sleep(0.5)
                        
                        # Acknowledge receipt
                        await self.safe_send(json.dumps({
                            "type": "chat_message",
                            "sender": "system",
                            "text": "Processing your request..."
                        }))
                        
                        # Give a brief period for the acknowledgment to be processed
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(f"Error saving message or acknowledging: {str(e)}")
                        logger.error(traceback.format_exc())
                        # Try to send error but don't fail if this also fails
                        try:
                            await self.safe_send(json.dumps({
                                "type": "error",
                                "message": "Error processing initial request"
                            }))
                        except:
                            pass
                        return
                        
                    # Process the request in a try/except to handle errors gracefully
                    try:
                        # Get files directly (no caching)
                        files = await self.get_all_project_files(self.project_id)
                        logger.info(f"Retrieved {len(files)} files for processing")
                        
                        # Process the request
                        response = await call_ai_multi_file(
                            self.conversation,
                            message_text,
                            {'files': files, 'project_id': self.project_id}
                        )
                        
                        # Save and send the response (in separate try blocks)
                        try:
                            await self.save_message(self.conversation.id, 'assistant', response)
                        except Exception as e:
                            logger.error(f"Error saving assistant message: {str(e)}")
                        
                        # Brief delay before sending response
                        await asyncio.sleep(0.5)
                        
                        try:
                            await self.safe_send(json.dumps({
                                "type": "chat_message",
                                "sender": "assistant",
                                "text": response
                            }))
                            logger.info("Successfully sent AI response")
                        except Exception as e:
                            logger.error(f"Error sending response: {str(e)}")
                            logger.error(traceback.format_exc())
                            
                    except Exception as e:
                        logger.error(f"AI processing error: {str(e)}")
                        logger.error(traceback.format_exc())
                        # Try to send error but don't fail if this also fails
                        try:
                            await self.safe_send(json.dumps({
                                "type": "error",
                                "message": f"Error processing your request: {str(e)}"
                            }))
                        except Exception as send_error:
                            logger.error(f"Could not send error message: {str(send_error)}")
            else:
                logger.warning(f"Unsupported message type: {data.get('type')}")
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
        except Exception as e:
            logger.error(f"Error handling message: {str(e)}")
            logger.error(traceback.format_exc())
    
    @database_sync_to_async
    def get_user_from_token(self, token):
        """Simple token authentication"""
        try:
            # Validate token
            access_token = AccessToken(token)
            user_id = access_token.payload.get('user_id')
            
            # Get user
            user = User.objects.get(id=user_id)
            logger.info(f"Authenticated user: {user.username}")
            return user
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return None
    
    @database_sync_to_async
    def create_conversation(self, project_id, user):
        """Create a new conversation"""
        try:
            project = Project.objects.get(id=project_id)
            conversation = AIConversation.objects.create(
                project=project,
                user=user,
                status='active'
            )
            logger.info(f"Created conversation {conversation.id}")
            return conversation
        except Exception as e:
            logger.error(f"Error creating conversation: {str(e)}")
            raise
    
    @database_sync_to_async
    def save_message(self, conversation_id, sender, text):
        """Save a message to the conversation"""
        try:
            conversation = AIConversation.objects.get(id=conversation_id)
            message = AIMessage.objects.create(
                conversation=conversation,
                sender=sender,
                text=text
            )
            return message
        except Exception as e:
            logger.error(f"Error saving message: {str(e)}")
            raise
    
    @database_sync_to_async
    def update_conversation_status(self, conversation_id, status):
        """Update conversation status"""
        try:
            conversation = AIConversation.objects.get(id=conversation_id)
            conversation.status = status
            conversation.save()
            return conversation
        except Exception as e:
            logger.error(f"Error updating conversation: {str(e)}")
    
    @database_sync_to_async
    def get_all_project_files(self, project_id):
        """
        Get all project files with direct database access.
        No caching, no complex path normalization.
        """
        files = {}
        
        try:
            # Get template files
            for file in TemplateFile.objects.filter(project_id=project_id):
                path = f"templates/{file.name}" if not file.path.startswith('templates/') else file.path
                files[path] = file.content or ''
            
            # Get model files
            for file in ModelFile.objects.filter(project_id=project_id):
                files[file.path] = file.content or ''
            
            # Get view files
            for file in ViewFile.objects.filter(project_id=project_id):
                files[file.path] = file.content or ''
            
            # Get form files
            for file in FormFile.objects.filter(project_id=project_id):
                files[file.path] = file.content or ''
            
            # Get static files
            for file in StaticFile.objects.filter(project_id=project_id):
                path = f"static/{file.name}" if not file.path.startswith('static/') else file.path
                files[path] = file.content or ''
            
            # Get URL files
            for file in URLFile.objects.filter(project_id=project_id):
                files[file.path] = file.content or ''
            
            # Get app files
            for file in AppFile.objects.filter(project_id=project_id):
                files[file.path] = file.content or ''
                
            return files
            
        except Exception as e:
            logger.error(f"Error retrieving project files: {str(e)}")
            logger.error(traceback.format_exc())
            return {}

# Use the simplified consumer in the application
ProjectConsumer = BasicProjectConsumer





