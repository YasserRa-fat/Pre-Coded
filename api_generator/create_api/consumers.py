import json
import logging
import traceback
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import User, AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from .models import (AIConversation, AIMessage, AIChangeRequest, Project, 
                     App, TemplateFile, ModelFile, ViewFile, FormFile, StaticFile, AppFile, UserModel)
from core.services.ai_editor import call_ai_multi_file
from django.conf import settings
from .views import setup_preview_project
from asgiref.sync import sync_to_async
from .preview_registry import preview_manager
import difflib
import asyncio
from django.db.models import Q
import os

logger = logging.getLogger(__name__)

# Add debug constants
DEBUG_CONSUMER = True

class ProjectConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """
        Authenticate user with JWT token and connect to WebSocket
        """
        try:
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
            self.project_id = self.scope['url_route']['kwargs']['project_id']
            
            # Check if project exists and user has access
            project_exists = await self.check_project_access(self.project_id, self.user)
            if not project_exists:
                logger.error(f"User {self.user.username} attempted to access unauthorized project {self.project_id}")
                await self.close(code=4004)
                return

            # Join project group
            self.room_group_name = f"project_{self.project_id}"
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )

            # Get app_name and file_path from query string if present
            app_name = None
            file_path = None
            if "app_name=" in query_string:
                app_name = query_string.split("app_name=")[1].split("&")[0]
            if "file_path=" in query_string:
                file_path = query_string.split("file_path=")[1].split("&")[0]
            
            # Create or get conversation
            self.conversation = await self.create_conversation(
                project_id=self.project_id,
                user=self.user,
                app_name=app_name,
                file_path=file_path
            )

            # Accept the connection
            await self.accept()
            logger.info(f"WebSocket connected for user {self.user.username}, project {self.project_id}")
            
        except Exception as e:
            logger.error(f"Error in WebSocket connect: {str(e)}")
            logger.error(traceback.format_exc())
            await self.close(code=4000)

    async def disconnect(self, close_code):
        """
        Leave the room group
        """
        logger.info(f"WebSocket disconnected with code {close_code}")
        
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """
        Receive message from WebSocket and process it
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'send_message':
                await self.handle_send_message(data)
            elif message_type == 'confirm_changes':
                await self.handle_confirm_changes(data)
            elif message_type == 'chat_message':
                await self.handle_chat_message(data)
            else:
                logger.warning(f"Unknown message type: {message_type}")
                await self.send_error("Unknown message type")
                
        except json.JSONDecodeError:
            logger.error("Failed to parse WebSocket message as JSON")
            await self.send_error("Invalid JSON format")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {str(e)}")
            logger.error(traceback.format_exc())
            await self.send_error(f"Error processing message: {str(e)}")

    async def handle_chat_message(self, data):
        """
        Redirect chat messages to code changes
        """
        if DEBUG_CONSUMER:
            logger.info("Chat message received - redirecting to code changes")
        # Simply forward the request to handle_send_message to ensure consistent handling
        await self.handle_send_message(data)

    async def handle_send_message(self, data):
        """
        Process a user message for code changes with improved NLP handling
        """
        if not self.user or not self.conversation:
            await self.send_error("Not authenticated")
            return
            
        text = data.get('text', '').strip()
        if not text:
            await self.send_error("Empty message")
            return
            
        try:
            if DEBUG_CONSUMER:
                logger.info(f"Processing message from user {self.user.username}: {text}")
            
            # Save user message
            await self.save_message(self.conversation.id, 'user', text)
            
            # Get project files for context
            project_files = await self.get_project_files(self.project_id)
            if DEBUG_CONSUMER:
                logger.info(f"Retrieved {len(project_files)} project files")
                logger.info(f"Available files: {list(project_files.keys())}")
            
            # Generate code changes
            if DEBUG_CONSUMER:
                logger.info("Calling AI for code changes")

            # Create a task for AI processing
            try:
                ai_response = await call_ai_multi_file(
                    conversation=self.conversation,
                    last_user_message=text,
                    context_files=project_files
                )
            except Exception as e:
                logger.error(f"Error in AI processing: {str(e)}")
                logger.error(traceback.format_exc())
                await self.send_error(f"Error generating code changes: {str(e)}")
                return
            
            if DEBUG_CONSUMER:
                logger.info(f"AI response received: {json.dumps(ai_response, indent=2)}")
            
            if 'error' in ai_response:
                error_msg = f"Failed to generate code changes: {ai_response['error']}"
                logger.error(error_msg)
                await self.send_error(error_msg)
                return
                
            if not ai_response.get('files'):
                error_msg = "No code changes were identified. Please try rephrasing your request to specify what files need to be modified."
                logger.error(error_msg)
                await self.send_error(error_msg)
                return
                
            if DEBUG_CONSUMER:
                logger.info(f"Creating change request for {len(ai_response['files'])} files")
            
            # Extract app_name from the AI response or file paths
            app_name = ai_response.get('app_name')
            
            # If no app_name in the response, try to infer from file paths
            if not app_name:
                for file_path in ai_response.get('files', {}).keys():
                    parts = file_path.split('/')
                    for part in parts:
                        if part in ['posts', 'users', 'accounts', 'comments', 'main', 'blog', 'api']:
                            app_name = part
                            break
                    if app_name:
                        break
            
            # If still no app_name, use conversation's app_name or default to "main"
            if not app_name:
                app_name = self.conversation.app_name or "main"
            
            # Create change request with required app_name
            change_request = await self.create_change_request(
                conversation_id=self.conversation.id,
                project_id=self.project_id,
                file_type='multi',
                diff=json.dumps(ai_response.get('files', {})),
                files=json.dumps(list(project_files.keys())),
                app_name=app_name,
                file_path=self.conversation.file_path or ""
            )
            
            if DEBUG_CONSUMER:
                logger.info(f"Change request created with ID: {change_request.id}")
            
            # Set up preview environments
            before_alias = f"preview_{self.project_id}_before_{change_request.id}"
            after_alias = f"preview_{self.project_id}_after_{change_request.id}"
            preview_setup_success = True
            
            if DEBUG_CONSUMER:
                logger.info("Setting up before preview environment")

            # Use the async preview_manager.setup_preview method directly
            try:
                await preview_manager.setup_preview(
                    project_id=self.project_id,
                    change_id=change_request.id,
                    mode="before",
                    files=None
                )
            except Exception as e:
                logger.error(f"Error setting up 'before' preview: {str(e)}")
                logger.error("Continuing with diff display despite preview error")
                preview_setup_success = False
            
            if DEBUG_CONSUMER:
                logger.info("Setting up after preview environment")
            
            try:
                await preview_manager.setup_preview(
                    project_id=self.project_id,
                    change_id=change_request.id,
                    mode="after",
                    files=ai_response.get('files', {})
                )
            except Exception as e:
                logger.error(f"Error setting up 'after' preview: {str(e)}")
                logger.error("Continuing with diff display despite preview error")
                preview_setup_success = False
            
            # Generate diff and send to client
            old_files = project_files
            new_files = {**project_files, **ai_response.get('files', {})}
            
            diffs = {}
            for file_path in ai_response.get('files', {}).keys():
                old_content = old_files.get(file_path, '')
                new_content = new_files[file_path]
                
                diff = list(difflib.unified_diff(
                    old_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f'a/{file_path}',
                    tofile=f'b/{file_path}'
                ))
                
                if diff:
                    diffs[file_path] = ''.join(diff)
            
            # Send diff modal - make sure this happens even if previews fail
            try:
                preview_content = {}
                if preview_setup_success:
                    preview_content = {
                        'before_alias': before_alias,
                        'after_alias': after_alias
                    }
                
                # Always send the diff modal, even if preview has issues
                await self.send_diff_modal(
                    change_id=change_request.id,
                    diff=diffs,
                    files=ai_response.get('files', {}),
                    preview_content=preview_content
                )
                
                logger.info("Diff modal sent to client successfully")
            except Exception as e:
                logger.error(f"Error sending diff modal: {str(e)}")
                # Last resort fallback - send as chat message if diff modal fails
                await self.send_chat_message('assistant', f"Generated code changes but couldn't display diff modal. Error: {str(e)}")
            
            # Save AI response
            await self.save_message(self.conversation.id, 'assistant', json.dumps(ai_response))
            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            logger.error(traceback.format_exc())
            await self.send_error(f"Error processing message: {str(e)}")

    async def handle_confirm_changes(self, data):
        """Handle confirmation of changes with cleanup"""
        try:
            change_id = data.get('change_id')
            if not change_id:
                await self.send_error("No change ID provided")
                return
                
            change_request = await self.get_change_request(change_id)
            if not change_request:
                await self.send_error("Change request not found")
                return
                
            # Apply changes
            diffs = json.loads(change_request.diff)
            for file_path, content in diffs['files'].items():
                # Apply changes to actual project files
                await self.apply_file_change(change_request.project_id, file_path, content)
            
            # Update statuses
            await self.update_change_request_status(change_id, 'applied')
            await self.update_conversation_status(self.conversation.id, 'closed')
            
            # Clean up preview environments
            before_alias = f"preview_{self.project_id}_before_{change_id}"
            after_alias = f"preview_{self.project_id}_after_{change_id}"
            await preview_manager.cleanup_preview(before_alias)
            await preview_manager.cleanup_preview(after_alias)
            
            # Send success message
            await self.send_chat_message('assistant', "Changes have been applied successfully!")
            
        except Exception as e:
            error_msg = f"Error applying changes: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            await self.send_error(error_msg)

    async def send_chat_message(self, sender, text):
        """
        Send a chat message to the WebSocket
        """
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'sender': sender,
            'text': text
        }))

    async def send_error(self, message):
        """
        Send an error message to the WebSocket
        """
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message
        }))

    async def send_diff_modal(self, change_id, diff, files, preview_content=None):
        """
        Send diff data to the WebSocket with preview URLs
        """
        # Ensure preview_content is a dictionary, even if None was passed
        if preview_content is None:
            preview_content = {}
            
        # Create a default mapping even if preview info is missing
        preview_map = {
            'before': f"/api/projects/{self.project_id}/preview/?mode=before",
            'after': f"/api/projects/{self.project_id}/preview/?mode=after&change_id={change_id}"
        }
        
        # Add any additional preview content available
        response_data = {
            'type': 'show_diff_modal',
            'kind': 'show_diff_modal',  # For compatibility
            'change_id': change_id,
            'diff': diff,
            'files': files,
            'preview_content': preview_content,
            'previewMap': preview_map
        }
        
        logger.info(f"Sending diff modal for change ID: {change_id} with {len(diff)} files")
        await self.send(text_data=json.dumps(response_data))

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
            # The Project model uses a ForeignKey 'user' field, not a ManyToMany
            # Check if the project exists and either:
            # 1. The user is the owner of the project (ForeignKey relationship)
            # 2. The project is public
            has_access = Project.objects.filter(
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
        project = Project.objects.get(id=project_id)
        conversation, created = AIConversation.objects.get_or_create(
            project=project,
            user=user,
            app_name=app_name,
            file_path=file_path,
            defaults={'status': 'active'}
        )
        return conversation

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
    def create_change_request(self, conversation_id, project_id, file_type, diff, files, app_name=None, file_path=None):
        """Create change request"""
        conversation = AIConversation.objects.get(id=conversation_id)
        project = Project.objects.get(id=project_id)
        return AIChangeRequest.objects.create(
            conversation=conversation,
            project=project,
            file_type=file_type,
            diff=diff,
            files=files,
            app_name=app_name,
            file_path=file_path,
            status='pending'
        )

    @database_sync_to_async
    def get_project_files(self, project_id):
        """Get all files for project"""
        project = Project.objects.get(id=project_id)
        files = {}
        
        # Get all file types
        for model in [TemplateFile, ViewFile, ModelFile, FormFile, StaticFile]:
            for file in model.objects.filter(project=project):
                files[file.path] = file.content
                
        return files

    @database_sync_to_async
    def get_change_request(self, change_id):
        """Get change request by ID"""
        return AIChangeRequest.objects.get(id=change_id)

    @database_sync_to_async
    def update_conversation_status(self, conversation_id, status):
        """Update conversation status"""
        conversation = AIConversation.objects.get(id=conversation_id)
        conversation.status = status
        conversation.save()
        return conversation

    @database_sync_to_async
    def update_change_request_status(self, change_id, status):
        """Update change request status"""
        change = AIChangeRequest.objects.get(id=change_id)
        change.status = status
        change.save()
        return change

    @database_sync_to_async
    def apply_file_change(self, project_id, file_path, content):
        """Apply file change to the database"""
        try:
            project = Project.objects.get(id=project_id)
            
            # Determine the file type based on the path
            file_type = None
            if file_path.startswith('templates/') or file_path.endswith('.html'):
                file_type = 'template'
                model_class = TemplateFile
            elif file_path.startswith('views/') or file_path.endswith('.py'):
                file_type = 'view'
                model_class = ViewFile
            elif file_path.startswith('models/'):
                file_type = 'model'
                model_class = ModelFile
            elif file_path.startswith('forms/'):
                file_type = 'form'
                model_class = FormFile
            elif file_path.startswith('static/'):
                file_type = 'static'
                model_class = StaticFile
            else:
                # Default to AppFile
                file_type = 'app'
                model_class = AppFile
                
            # Try to find the file
            file_obj = model_class.objects.filter(project=project, path=file_path).first()
            
            if file_obj:
                # Update existing file
                file_obj.content = content
                file_obj.save()
                logger.info(f"Updated {file_type} file: {file_path}")
            else:
                # Create new file
                # Determine if this file belongs to an app
                app = None
                for app_obj in App.objects.filter(project=project):
                    if app_obj.name.lower() in file_path.lower():
                        app = app_obj
                        break
                
                # Create file with or without app reference
                if hasattr(model_class, 'app') and app:
                    file_obj = model_class.objects.create(
                        project=project,
                        app=app,
                        path=file_path,
                        name=os.path.basename(file_path),
                        content=content
                    )
                else:
                    file_obj = model_class.objects.create(
                        project=project,
                        path=file_path,
                        name=os.path.basename(file_path),
                        content=content
                    )
                logger.info(f"Created new {file_type} file: {file_path}")
            
            return True
        except Exception as e:
            logger.error(f"Error applying file change: {str(e)}")
            logger.error(traceback.format_exc())
            return False