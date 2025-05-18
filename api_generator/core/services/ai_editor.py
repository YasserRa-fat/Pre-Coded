import os
import simplejson as json
import difflib
import requests
from django.core.management import call_command
from asgiref.sync import sync_to_async
import logging
import re
from functools import lru_cache
from django.core.cache import cache
import aiohttp
from typing import Dict, Optional
import ast  # Add this import for code validation
import asyncio
import traceback
import random
from core.services.code_validator import DjangoCodeValidator
from core.services.ai_editor_fixed import make_ai_api_call as call_ai_api_async
logger = logging.getLogger(__name__)
from create_api.models import (
    AIChangeRequest,
    TemplateFile,
    ModelFile,
    ViewFile,
    FormFile,
    AppFile,
    StaticFile,
    AIConversation,
    AIMessage,
    Project, App, URLFile
)
from .classifier import classify_request
import string
from pathlib import Path
from django.conf import settings
from .file_indexer import FileIndexer

TOGETHER_API_KEY = os.getenv("TOGETHER_AI_API_KEY")
MISTRAL_MODEL    = "mistralai/Mixtral-8x7B-Instruct-v0.1"
API_URL          = "https://api.together.xyz/inference"

# Cache timeouts
CACHE_TIMEOUT = 60 * 5  # 5 minutes
CHAT_CACHE_TIMEOUT = 60 * 30  # 30 minutes

# Shorter prompts for faster responses
SYSTEM_PROMPT = """You are a Django AI assistant. Analyze the request and generate necessary file changes for the project stored in the database.
Your task is to:
1. Identify all files that need to be modified or created based on the user's request
2. Generate complete, working code changes for each file
3. Return a JSON object with all changes

The changes should be returned in this format:
{{
    "files": {{
        "path/to/file1": "complete file content with changes",
        "path/to/file2": "complete file content with changes"
    }},
    "description": "Brief description of changes made",
    "dependencies": {{
        "python": ["package1", "package2"],
        "js": ["package1", "package2"]
    }}
}}

Project: {project_name}
App: {app_name}
Available Files: {file_list}
Request: {user_message}

Important:
1. The project is a standard Django project (not DRF)
2. All file paths should match the database structure (models/, views/, templates/, etc.)
3. Generate complete file contents with your changes, not just the changes
4. Include all necessary imports and dependencies
5. Ensure template changes include proper template inheritance
6. Make sure view changes include proper context data
7. Add any new URL patterns needed
8. Include any new static files required
9. NEVER respond with explanations or chat messages - ONLY GENERATE CODE CHANGES
10. ALWAYS return a valid JSON response with the "files" field containing your changes
11. If the request is unclear, still attempt to generate code changes rather than asking for clarification
12. ALWAYS use forward slashes (/) in file paths, NEVER use backslashes (\)

Do not use placeholders or '...'.
Generate complete, working code that can be directly used.
REMEMBER: This is for code generation only. Do not respond conversationally.
"""

SYSTEM_CHAT_PROMPT = """You are a friendly Django expert assistant. 
Your role is to help users with their Django project by answering questions and providing guidance.
Keep responses conversational and helpful.

Project: {project_name}
Description: {project_description}
Files: {file_list}

For code changes, users should explicitly ask to modify files.
Otherwise, provide helpful explanations in plain English.
"""

REFINE_PROMPT = r"""You are a Django request analyzer. Your task is to break down the user's request into specific file changes needed.
Return a JSON object in this format:
{{{{
    "refined_request": "Clear description of what needs to be done",
    "file_types": {{{{
        "template": ["Description of template changes needed"],
        "view": ["Description of view changes needed"],
        "model": ["Description of model changes needed"],
        "static": ["Description of static file changes needed"],
        "url": ["Description of URL changes needed"]
    }}}}
}}}}

Request: {user_message}
Project: {project_name}
App: {app_name}

IMPORTANT: Always use forward slashes (/) in file paths, never use backslashes (\).
"""

TEMPLATE_PROMPT_STAGE1 = r"""You are a Django template expert. Select template files that need to be modified based on this request.
Return a JSON object with ONLY the file paths that need to be modified:
{{{{
    "selected_files": ["templates/path/to/file1.html", "templates/path/to/file2.html"]
}}}}

IMPORTANT INSTRUCTIONS:
1. YOU decide which template files are most relevant to the request
2. ONLY include files that actually need to be modified to fulfill the request
3. Your response MUST be in valid JSON format with the exact structure shown above
4. Return ONLY the file paths, not their content
5. ALWAYS use forward slashes (/) in file paths, NEVER use backslashes (\)
6. Use full paths including directory prefixes like 'templates/'

Request: {refined_request}
Available template files:
{file_list}
"""

TEMPLATE_PROMPT_STAGE2 = r"""You are a Django template expert. Generate template file changes based on this request.
Return a JSON object with template file changes for the files you previously selected:
{{{{
    "files": {{{{
        "templates/path/to/file1.html": "complete template content",
        "templates/path/to/file2.html": "complete template content"
    }}}}
}}}}

IMPORTANT INSTRUCTIONS:
1. Your response MUST be in valid JSON format with the exact structure shown above
2. Put actual HTML code inside the file content strings
3. Make sure to escape any quotes in the HTML code
4. Include complete file content, not just the changes
5. Use EXACTLY the same paths that you selected in the previous step
6. ALWAYS use forward slashes (/) in file paths, NEVER use backslashes (\)

Request: {refined_request}
Selected files with their content:
{selected_files_content}
"""

VIEW_PROMPT_STAGE1 = r"""You are a Django view expert. Select view files that need to be modified based on this request.
Return a JSON object with ONLY the file paths that need to be modified:
{{{{
    "selected_files": ["views/path/to/file1.py", "views/path/to/file2.py"]
}}}}

IMPORTANT INSTRUCTIONS:
1. YOU decide which view files are most relevant to the request
2. ONLY include files that actually need to be modified to fulfill the request
3. Your response MUST be in valid JSON format with the exact structure shown above
4. Return ONLY the file paths, not their content
5. ALWAYS use forward slashes (/) in file paths, NEVER use backslashes (\)
6. Use full paths including directory prefixes like 'views/'

Request: {refined_request}
Available view files:
{file_list}
"""

VIEW_PROMPT_STAGE2 = r"""You are a Django view expert. Generate view file changes based on this request.
Return a JSON object with view file changes for the files you previously selected:
{{{{
    "files": {{{{
        "views/path/to/file1.py": "complete view content",
        "views/path/to/file2.py": "complete view content"
    }}}}
}}}}

IMPORTANT INSTRUCTIONS:
1. Your response MUST be in valid JSON format with the exact structure shown above
2. Include all necessary imports and complete view code
3. Make sure to escape any quotes in the Python code
4. Include complete file content, not just the changes

Request: {refined_request}
Selected files with their content:
{selected_files_content}
"""

MODEL_PROMPT_STAGE1 = r"""You are a Django model expert. Select model files that need to be modified based on this request.
Return a JSON object with ONLY the file paths that need to be modified:
{{{{
    "selected_files": ["models/path/to/file1.py", "models/path/to/file2.py"]
}}}}

IMPORTANT INSTRUCTIONS:
1. YOU decide which model files are most relevant to the request
2. ONLY include files that actually need to be modified to fulfill the request
3. Your response MUST be in valid JSON format with the exact structure shown above
4. Return ONLY the file paths, not their content
5. ALWAYS use forward slashes (/) in file paths, NEVER use backslashes (\)
6. Use full paths including directory prefixes like 'models/'

Request: {refined_request}
Available model files:
{file_list}
"""

MODEL_PROMPT_STAGE2 = r"""You are a Django model expert. Generate model file changes based on this request.
Return a JSON object with model file changes for the files you previously selected:
{{{{
    "files": {{{{
        "models/path/to/file1.py": "complete model content",
        "models/path/to/file2.py": "complete model content"
    }}}}
}}}}

IMPORTANT INSTRUCTIONS:
1. Your response MUST be in valid JSON format with the exact structure shown above
2. Include all necessary imports and complete model code
3. Make sure to escape any quotes in the Python code
4. Include complete file content, not just the changes

Request: {refined_request}
Selected files with their content:
{selected_files_content}
"""

FORM_PROMPT_STAGE1 = r"""You are a Django form expert. Select form files that need to be modified based on this request.
Return a JSON object with ONLY the file paths that need to be modified:
{{{{
    "selected_files": ["forms/path/to/file1.py", "forms/path/to/file2.py"]
}}}}

IMPORTANT INSTRUCTIONS:
1. YOU decide which form files are most relevant to the request
2. ONLY include files that actually need to be modified to fulfill the request
3. Your response MUST be in valid JSON format with the exact structure shown above
4. Return ONLY the file paths, not their content

Request: {refined_request}
Available form files:
{file_list}
"""

FORM_PROMPT_STAGE2 = r"""You are a Django form expert. Generate form file changes based on this request.
Return a JSON object with form file changes for the files you previously selected:
{{{{
    "files": {{{{
        "forms/path/to/file1.py": "complete form content",
        "forms/path/to/file2.py": "complete form content"
    }}}}
}}}}

IMPORTANT INSTRUCTIONS:
1. Your response MUST be in valid JSON format with the exact structure shown above
2. Include all necessary imports and complete form code
3. Make sure to escape any quotes in the Python code
4. Include complete file content, not just the changes

Request: {refined_request}
Selected files with their content:
{selected_files_content}
"""

# Add the static file prompts
STATIC_PROMPT_STAGE1 = r"""You are a Django static files expert. Select static files that need to be modified based on this request.
Return a JSON object with ONLY the file paths that need to be modified:
{{{{
    "selected_files": ["static/path/to/file.js", "static/path/to/file.css"]
}}}}

IMPORTANT INSTRUCTIONS:
1. YOU decide which static files are most relevant to the request
2. ONLY include files that actually need to be modified to fulfill the request
3. Your response MUST be in valid JSON format with the exact structure shown above
4. Return ONLY the file paths, not their content

Request: {refined_request}
Available static files:
{file_list}
"""

STATIC_PROMPT_STAGE2 = r"""You are a Django static files expert. Generate static file changes based on this request.
Return a JSON object with ONLY static file changes:
{{{{
    "files": {{{{
        "static/path/to/file.js": "complete JS content",
        "static/path/to/file.css": "complete CSS content"
    }}}}
}}}}

IMPORTANT FORMATTING INSTRUCTIONS:
1. Your response MUST be in valid JSON format with the exact structure shown above
2. DO NOT include any explanations or notes outside the JSON structure
3. Put actual code inside the file content strings
4. Make sure to escape any quotes in the code
5. Include complete file content, not just the changes

Important implementation guidelines:
1. Include all necessary JS/CSS code
2. Add proper event handlers and functions
3. Handle data visualization if needed
4. Ensure proper styling and responsiveness

Request: {refined_request}
Selected files with their content:
{selected_files_content}
"""

# Add debug constants
DEBUG_REFINE = True
DEBUG_TEMPLATE = True
DEBUG_VIEW = True
DEBUG_STATIC = True
DEBUG_MULTI = True

@lru_cache(maxsize=100)
def get_cached_file_content(file_id, content):
    """Cache file contents to avoid repeated database lookups"""
    return content

async def get_cached_conversation_history(conversation_id):
    """Get cached conversation history or fetch from database (async)"""
    cache_key = f"conv_history_{conversation_id}"
    history = cache.get(cache_key)
    if history is None:
        history = []
        conversation = await sync_to_async(AIConversation.objects.get)(id=conversation_id)
        messages = await sync_to_async(lambda: list(conversation.messages.order_by('timestamp')) )()
        for msg in messages:
            prefix = "User:" if msg.sender=='user' else "Assistant:"
            history.append(f"{prefix} {msg.text}")
        cache.set(cache_key, history, CHAT_CACHE_TIMEOUT)
    return history

def normalize_path(path):
    """
    Normalize a path to a consistent format for AI and system interactions.
    Ensure this matches FileIndexer._normalize_path for consistency.
    """
    if not path:
        logger.debug("Empty path provided to AI Editor normalize_path")
        return ''
    
    # Log original path
    logger.debug(f"AI Editor normalizing path: '{path}'")
    
    # Standardize on forward slashes
    path = str(path).strip()
    path = path.replace('\\', '/')
    
    # Remove leading/trailing slashes
    path = path.strip('/')
    
    # Log normalized path for debugging
    logger.debug(f"AI Editor normalized path: '{path}'")
    return path

async def call_ai(conversation, last_user_message, context_files):
    """Async version of AI API call with strict path handling"""
    cache_key = f"ai_response_{conversation.id}_{hash(last_user_message)}"
    cached_response = cache.get(cache_key)
    if cached_response:
        logger.debug("Using cached AI response")
        return cached_response

    history = await get_cached_conversation_history(conversation.id)
    history.append(f"User: {last_user_message}")

    # Normalize all file paths in context
    normalized_context = {}
    logger.debug("Normalizing file paths for AI context")
    for path, content in context_files.items():
        norm_path = normalize_path(path)
        normalized_context[norm_path] = content
        logger.debug(f"AI context path: {path} -> {norm_path}")

    file_list = "\n".join(f"- {p}" for p in normalized_context.keys())
    logger.debug(f"Available files for AI:\n{file_list}")

    prompt = SYSTEM_PROMPT.format(
        project_name=conversation.project.name,
        app_name=conversation.app_name or "—",
        file_list=file_list
    )

    # Add strict path instructions
    prompt += "\nIMPORTANT: When selecting or referring to files:\n"
    prompt += "1. Use EXACT paths from the list above\n"
    prompt += "2. Always include the full path (e.g., 'templates/feed.html', not just 'feed.html')\n"
    prompt += "3. Return paths in a JSON object with no additional text\n"
    prompt += "4. Example: {'selected_files': ['templates/feed.html']}\n"

    # Only include relevant files based on the message
    relevant_files = {}
    logger.debug("Filtering relevant files based on message keywords")
    for path, content in normalized_context.items():
        if any(keyword in last_user_message.lower() for keyword in path.lower().split('/')):
            relevant_files[path] = get_cached_file_content(path, content)
            logger.debug(f"Including relevant file: {path}")

    for path, content in relevant_files.items():
        prompt += f"```{path}\n{content}\n```\n\n"
    prompt += "\n".join(history[-5:]) + "\nAssistant:"

    logger.debug("Making AI API call")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            API_URL,
            json={
                "model": MISTRAL_MODEL,
                "prompt": prompt,
                "temperature": 0.2,
                "max_tokens": 2048,
                "top_p": 0.7,
                "frequency_penalty": 0.5,
            },
            headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"}
        ) as response:
            response.raise_for_status()
            result = await response.json()
            result = result["choices"][0]["text"].strip()
            logger.debug("Received AI response")

    # Validate and normalize paths in the response
    try:
        logger.debug("Validating and normalizing paths in AI response")
        response_data = json.loads(result)
        if isinstance(response_data, dict):
            # Normalize paths in selected_files
            if 'selected_files' in response_data:
                logger.debug(f"Original selected files: {response_data['selected_files']}")
                response_data['selected_files'] = [
                    normalize_path(p) for p in response_data['selected_files']
                ]
                logger.debug(f"Normalized selected files: {response_data['selected_files']}")
            # Normalize paths in files dict
            if 'files' in response_data:
                logger.debug("Normalizing paths in files dictionary")
                normalized_files = {}
                for path, content in response_data['files'].items():
                    norm_path = normalize_path(path)
                    normalized_files[norm_path] = content
                    logger.debug(f"Normalized file path: {path} -> {norm_path}")
                response_data['files'] = normalized_files
            result = json.dumps(response_data)
    except json.JSONDecodeError:
        logger.warning("AI response was not valid JSON")

    cache.set(cache_key, result, CACHE_TIMEOUT)
    return result

async def call_chat_ai(conversation, last_user_message, context_files=None):
    """Async version of chat AI call"""
    try:
        cache_key = f"chat_response_{conversation.id}_{hash(last_user_message)}"
        cached_response = cache.get(cache_key)
        if cached_response:
            return cached_response

        history = await get_cached_conversation_history(conversation.id)
        history.append(f"User: {last_user_message}")

        if context_files:
            file_list = "\n".join(f"- {path}" for path in context_files.keys())
        else:
            file_list = "– no files provided –"

        prompt = SYSTEM_CHAT_PROMPT.format(
            project_name=conversation.project.name,
            project_description=conversation.project.description or "—",
            file_list=file_list
        )

        if context_files:
            relevant_files = {}
            for path, content in context_files.items():
                if any(keyword in last_user_message.lower() for keyword in path.lower().split('/')):
                    relevant_files[path] = get_cached_file_content(path, content)
            for path, content in relevant_files.items():
                prompt += f"```{path}\n{content}\n```\n\n"
        prompt += "\n".join(history[-3:]) + "\nAssistant:"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                API_URL,
                json={
                    "model": MISTRAL_MODEL,
                    "prompt": prompt,
                    "temperature": 0.2,
                    "max_tokens": 512,
                    "top_p": 0.7,
                    "frequency_penalty": 0.5,
                },
                headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"}
            ) as response:
                response.raise_for_status()
                result = await response.json()
                result = result["choices"][0]["text"].strip()
        cache.set(cache_key, result, CHAT_CACHE_TIMEOUT)
        return result
    except Exception as e:
        logger.error(f"Error in call_chat_ai: {str(e)}")
        return f"I apologize, but I encountered an error: {str(e)}"

# Replace the problematic string replacements with properly escaped literals
json_example = r'{{ "files": {{ "<file_path>": "<updated_content>", "<file_path>": "<updated_content>" }} }}'
empty_example = r'{{ "files": {{}} }}'

async def run_apply(change: AIChangeRequest, project_db_alias: str):
    diffs = json.loads(change.diff)
    FILE_MODEL = {
        'template': TemplateFile,
        'model': ModelFile,
        'view': ViewFile,
        'form': FormFile,
        'app': AppFile,
        'static': StaticFile,
    }

    for path, new_content in diffs.items():
        file_type = change.file_type or classify_request(change.conversation.messages.last().text, [path])[0]
        model_cls = FILE_MODEL.get(file_type, AppFile)
        
        qs = model_cls.objects.filter(project=change.conversation.project, path=path)
        obj = await sync_to_async(qs.first)()
        if obj:
            obj.content = new_content
            await sync_to_async(obj.save)()
        else:
            kwargs = {'project': change.conversation.project, 'content': new_content, 'path': path}
            if hasattr(model_cls, 'app') and change.app_name:
                try:
                    app_obj = await sync_to_async(App.objects.get)(
                        project=change.conversation.project, name=change.app_name
                    )
                    kwargs['app'] = app_obj
                except App.DoesNotExist:
                    # Try to extract app name from path
                    app_name = None
                    parts = path.split('/')
                    for part in parts:
                        if part in ['posts', 'users', 'accounts', 'comments']:
                            app_name = part
                            break
                    
                    if app_name:
                        try:
                            app_obj = await sync_to_async(App.objects.get)(
                                project=change.conversation.project, name=app_name
                            )
                            kwargs['app'] = app_obj
                        except App.DoesNotExist:
                            # Use the first app if no match found
                            app_obj = await sync_to_async(App.objects.filter)(
                                project=change.conversation.project
                            ).first()
                            if app_obj:
                                kwargs['app'] = app_obj
                    
            await sync_to_async(model_cls.objects.create)(**kwargs)

        if file_type == 'model':
            label = obj.app._meta.label_lower if obj else change.app_name or "main"
            await sync_to_async(call_command)("makemigrations", label, interactive=False)
            await sync_to_async(call_command)("migrate", label, database=project_db_alias, interactive=False)

async def async_call_ai_api(prompt: str, max_tokens: int = 4096, temperature: float = 0.2) -> str:
    """Async version of AI API call"""
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
    payload = {
        "model": MISTRAL_MODEL,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 0.7,
        "frequency_penalty": 0.5,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=payload, headers=headers, timeout=60) as response:
                if response.status == 429:
                    logger.warning("Rate limited by AI API")
                    raise ValueError("Rate limit exceeded")
                    
                response.raise_for_status()
                result = await response.json()
                return result["choices"][0]["text"].strip()
                
    except aiohttp.ClientError as e:
        logger.error(f"API call failed: {str(e)}")
        raise ValueError(f"API request failed: {str(e)}")

async def refine_request(conversation, user_message) -> dict:
    """
    Use AI to refine user request into specific file changes needed
    """
    # Get project name using sync_to_async
    project_name = "Unknown Project"
    try:
        if conversation.project_id:  # Access the ID directly instead of the relation
            project = await sync_to_async(Project.objects.get)(id=conversation.project_id)
            project_name = await sync_to_async(lambda: project.name)()
    except Exception as e:
        logger.error(f"Error getting project name: {str(e)}")
    
    app_name = conversation.app_name or "---"
    
    # Format the prompt with our variables
    formatted_prompt = REFINE_PROMPT.format(
        user_message=user_message,
        project_name=project_name,
        app_name=app_name
    )
    
    try:
        # Call AI API
        result = await call_ai_api_async(prompt=formatted_prompt)
        
        # Handle response
        try:
            # Try to parse the response as JSON
            parsed_result = parse_ai_output(result)
            if parsed_result:
                logger.info(f"Refinement result: {parsed_result}")
                return parsed_result
            else:
                logger.error("Failed to parse refined request result")
                return None
                
        except Exception as e:
            logger.error(f"Error parsing refinement result: {str(e)}")
            logger.error(f"Raw result: {result}")
            return None
            
    except Exception as e:
        logger.error(f"Error in refine_request: {str(e)}")
        return None

async def make_ai_api_call(prompt: str, max_tokens: int = 2048) -> str:
    """Make an async API call to the AI service with retry on rate limiting"""
    max_retries = 3
    base_retry_delay = 2  # start with 2 second delay
    
    # Safety check - ensure prompt is a string
    if not isinstance(prompt, str):
        raise ValueError(f"Prompt must be a string, got {type(prompt)}")
    
    # Pre-process prompt to handle Django template tags that could cause issues
    try:
        # Replace Django template tags with placeholders before sending to API
        prompt = prompt.replace("{% csrf_token %}", "CSRF_TOKEN_PLACEHOLDER")
        prompt = prompt.replace("{%", "DJANGO_TAG_START")
        prompt = prompt.replace("%}", "DJANGO_TAG_END")
    except Exception as e:
        logger.error(f"Error preprocessing prompt: {str(e)}")
        raise
    
    last_error = None
    for attempt in range(max_retries):
        try:
            logger.info(f"Making API call attempt {attempt + 1}/{max_retries}")
            
            # Wait before each attempt to avoid rate limits
            retry_delay = base_retry_delay * (attempt + 1)
            await asyncio.sleep(retry_delay)
            
            headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
            payload = {
                "model": MISTRAL_MODEL,
                "prompt": prompt,
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "top_p": 0.7,
                "frequency_penalty": 0.5
            }
            
            timeout = aiohttp.ClientTimeout(total=60)  # 60 second timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(API_URL, json=payload, headers=headers) as response:
                    if response.status == 429:  # Rate limited
                        logger.warning(f"Rate limited by AI API (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        else:
                            raise Exception("Max retries exceeded due to rate limiting")
                    
                    # Handle all non-2xx responses
                    if response.status >= 400:
                        error_text = await response.text()
                        logger.error(f"API error {response.status}: {error_text}")
                        last_error = f"API returned status code {response.status}: {error_text}"
                        if attempt < max_retries - 1:
                            continue
                        raise Exception(last_error)
                            
                    result = await response.json()
                    
                    if not result.get("choices"):
                        last_error = "Invalid response format from AI API"
                        if attempt < max_retries - 1:
                            continue
                        raise Exception(last_error)
                    
                    # Post-process the result to restore Django template tags
                    response_text = result["choices"][0]["text"]
                    response_text = response_text.replace("CSRF_TOKEN_PLACEHOLDER", "{% csrf_token %}")
                    response_text = response_text.replace("DJANGO_TAG_START", "{%")
                    response_text = response_text.replace("DJANGO_TAG_END", "%}")
                    
                    return response_text
                    
        except asyncio.TimeoutError:
            last_error = f"API call timed out (attempt {attempt + 1}/{max_retries})"
            logger.error(last_error)
            if attempt == max_retries - 1:
                raise Exception(last_error)
        except aiohttp.ClientError as e:
            last_error = f"API request failed: {str(e)}"
            logger.error(last_error)
            if attempt == max_retries - 1:
                raise Exception(last_error)
        except Exception as e:
            last_error = f"Error calling AI API: {str(e)}"
            logger.error(last_error)
            logger.error(traceback.format_exc())
            if attempt == max_retries - 1:
                raise
            
        # Wait before next retry
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
    
    raise Exception(last_error or "Failed to get response from AI API after all retries")
from django.db import connections

def get_project_files(project_id):
    files = {}
    with connections['default'].cursor() as cursor:
        # Template Files
        cursor.execute("SELECT path, app_id FROM create_api_templatefile WHERE project_id = %s", [project_id])
        for row in cursor.fetchall():
            path = row[0]
            app_id = row[1]
            app_name = App.objects.get(id=app_id).name if app_id else None
            files[f"templates/{path}"] = {'type': 'templates', 'app': app_name}
        # Static Files
        cursor.execute("SELECT path FROM create_api_staticfile WHERE project_id = %s", [project_id])
        files.update({f"static/{row[0]}": {'type': 'static', 'app': None} for row in cursor.fetchall()})
        # URL Files
        cursor.execute("SELECT path, app_id FROM create_api_urlfile WHERE project_id = %s", [project_id])
        for row in cursor.fetchall():
            path = row[0]
            app_id = row[1]
            app_name = App.objects.get(id=app_id).name if app_id else None
            files[f"urls/{path}"] = {'type': 'urls', 'app': app_name}
    logger.info(f"Retrieved {len(files)} files for project {project_id}: {list(files.keys())}")
    return files

def validate_and_map_files(selected_files, project_files):
    logger.debug("Validating and mapping selected files")
    valid_files = []
    for selected_path in selected_files:
        logger.debug(f"Processing selected path: {selected_path}")
        if selected_path in project_files:
            valid_files.append(selected_path)
            logger.debug(f"Found exact match for {selected_path}")
        else:
            # Fallback: Match by filename
            filename = os.path.basename(selected_path)
            logger.debug(f"No exact match, trying to match by filename: {filename}")
            matching_paths = [
                path for path in project_files.keys()
                if os.path.basename(path) == filename and project_files[path].get('type') == 'templates'
            ]
            if matching_paths:
                valid_files.append(matching_paths[0])
                logger.info(f"Mapped {selected_path} to {matching_paths[0]}")
            else:
                logger.warning(f"No matching file found for {selected_path}")
    return valid_files
def preprocess_django_template(template_content):
    """Preprocess Django template content to replace template tags with placeholders"""
    # Replace Django template tags with placeholders
    processed = re.sub(r'{%\s+extends\s+[\'"](.+?)[\'"]', 'EXTENDS_BASE_TEMPLATE', template_content)
    processed = re.sub(r'{%\s+block\s+(.+?)\s+%}', 'BLOCK_START_\\1', processed)
    processed = re.sub(r'{%\s+endblock\s*%}', 'BLOCK_END', processed)
    processed = re.sub(r'{%\s+csrf_token\s*%}', 'CSRF_TOKEN_PLACEHOLDER', processed)  
    processed = re.sub(r'{{\s+(.+?)\s+}}', 'VAR_\\1', processed)
    processed = re.sub(r'{%\s+(.+?)\s+%}', 'TAG_\\1', processed)
    return processed

def postprocess_django_template(template_content):
    """Postprocess Django template content to restore template tags from placeholders"""
    # Restore Django template tags from placeholders
    processed = template_content.replace('EXTENDS_BASE_TEMPLATE', "{% extends 'base.html' %}")
    processed = re.sub(r'BLOCK_START_(\w+)', r'{% block \1 %}', processed)
    processed = re.sub(r'BLOCK_END', r'{% endblock %}', processed)
    processed = re.sub(r'CSRF_TOKEN_PLACEHOLDER', r'{% csrf_token %}', processed)
    processed = re.sub(r'VAR_(\w+)', r'{{ \1 }}', processed)
    processed = re.sub(r'TAG_(\w+)', r'{% \1 %}', processed)
    return processed
async def generate_template_changes(refined_request, context, file_list, project_name, app_name, user_message):
    """Generate template file changes for a given request."""
    project_id = context.get('project_id')
    cache_key = f"template_changes:{project_id}:{hash(user_message)}"
    
    # Check cache
    cached_response = cache.get(cache_key)
    if cached_response:
        logger.info(f"Returning cached template changes for {cache_key}")
        return cached_response

    # Stage 1: Select relevant template files with explicit instructions
    stage1_prompt = f"""
You are a Django template expert. Select template files that need to be modified based on this request.
Return a JSON object with ONLY the file paths that need to be modified, wrapped in delimiters:
---JSON_START---
{{
    "selected_files": ["templates/feed.html", "templates/base.html"]
}}
---JSON_END---

IMPORTANT INSTRUCTIONS:
1. Select ONLY from the available template files listed below.
2. Use the EXACT paths as provided (e.g., 'templates/feed.html'). Do NOT modify, shorten, or invent paths.
3. If no files are relevant, return an empty array: {{"selected_files": []}}.
4. Example: To modify the feed page, select 'templates/feed.html' if listed.
5. Do NOT include app names in paths (e.g., do NOT select 'posts/templates/feed.html').

Request: {user_message}
Available template files:
{file_list}
"""
    stage1_response = await call_ai_api_async(prompt=stage1_prompt, max_tokens=4096, temperature=0.2)
    logger.debug(f"Raw Stage 1 response: {stage1_response}")

    selected_files = []
    project_files = context.get('files', {})

    # Parse Stage 1 response
    if stage1_response and isinstance(stage1_response, str):
        try:
            json_match = re.search(r'---JSON_START---\s*([\s\S]*?)\s*---JSON_END---', stage1_response)
            if json_match:
                stage1_data = json.loads(json_match.group(1))
                selected_files = stage1_data.get('selected_files', [])
            else:
                logger.warning(f"No JSON delimiters found in Stage 1 response: {stage1_response}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in Stage 1 response: {e}, response: {stage1_response}")

    # Fallback: Map selected files to existing paths
    valid_files = validate_and_map_files(selected_files, project_files)
    if not valid_files:
        logger.error("No valid template files selected or found")
        return {'error': 'No valid template files selected'}

    # Stage 2: Generate template content
    response = {'files': {}, 'dependencies': {'python': [], 'js': []}}
    for file_path in valid_files:
        current_content = project_files[file_path].get('content', '')
        stage2_prompt = f"""
You are a Django template expert. Generate complete template file content for {file_path} based on this request.
Return a JSON object with the file content as a string:
{{
    "files": {{
        "{file_path}": "complete template content"
    }}
}}

IMPORTANT INSTRUCTIONS:
1. Your response MUST be in valid JSON format with the exact structure shown above.
2. The file content MUST be a string containing complete, valid HTML code.
3. Include all necessary template tags and maintain existing functionality.
4. Escape quotes in HTML code as needed.
5. Use the current file content as a base and apply only the requested changes.
6. For analytics graphs, include a <canvas> element with an ID and reference Chart.js.

Request: {user_message}
Current content of {file_path}:
{current_content}
"""
        stage2_response = await call_ai_api_async(prompt=stage2_prompt, max_tokens=8192, temperature=0.3)
        try:
            stage2_data = json.loads(stage2_response)
            file_content = stage2_data.get('files', {}).get(file_path)
            if isinstance(file_content, str):
                response['files'][file_path] = file_content
                if 'analytics' in user_message.lower():
                    response['dependencies']['js'].append('chart.js')
            else:
                logger.error(f"Invalid content type for {file_path}: {type(file_content)}")
        except (json.JSONDecodeError, AttributeError):
            logger.error(f"Invalid Stage 2 response for {file_path}: {stage2_response}")
            continue

    # Cache the response
    if response['files']:
        cache.set(cache_key, response, timeout=300)
        logger.info(f"Cached template changes for {cache_key}")

    return response
async def generate_view_changes(refined_request: str, current_files: dict) -> dict:
    """Generate view-specific changes using a two-stage approach"""
    if DEBUG_VIEW:
        logger.info(f"Generating view changes for: {refined_request}")
        logger.info(f"Current view files: {list(current_files.keys())}")
    
    # STAGE 1: Only send filenames and directories to select relevant files
    file_list = "\n".join(f"- {k}" for k in current_files.keys())
    
    prompt_stage1 = VIEW_PROMPT_STAGE1.format(
        refined_request=refined_request,
        file_list=file_list
    )
    
    if DEBUG_VIEW:
        logger.info(f"View stage 1 prompt:\n{prompt_stage1}")
    
    try:
        result_stage1 = await make_ai_api_call(prompt_stage1)
        
        if DEBUG_VIEW:
            logger.info(f"View stage 1 response:\n{result_stage1}")
        
        try:
            # Parse stage 1 response to get selected files
            selected_files = []
            
            # Try to parse as JSON directly first
            try:
                json_data = json.loads(result_stage1)
                if isinstance(json_data, dict) and 'selected_files' in json_data:
                    selected_files = json_data['selected_files']
            except json.JSONDecodeError:
                # Try to extract from the response
                match = re.search(r'"selected_files"\s*:\s*\[(.*?)\]', result_stage1, re.DOTALL)
                if match:
                    # Extract the content between brackets
                    files_str = match.group(1)
                    # Split by commas, strip whitespace and quotes
                    selected_files = [f.strip().strip('"\'') for f in files_str.split(',')]
            
            if not selected_files:
                logger.error("No files selected in stage 1")
                return {"files": {}}
            
            # Filter out files that aren't in the current_files list
            valid_selected_files = [f for f in selected_files if f in current_files]
            if not valid_selected_files:
                # Look for valid files in current_files that match part of the selected paths
                valid_selected_files = []
                for selected in selected_files:
                    for current in current_files.keys():
                        if selected.split('/')[-1] in current:
                            valid_selected_files.append(current)
                            break
            
            if not valid_selected_files:
                logger.error("No valid files found after filtering")
                return {"files": {}}
            
            # STAGE 2: Send content of the selected files for detailed analysis
            selected_files_content = ""
            for file_path in valid_selected_files:
                content = current_files[file_path]
                selected_files_content += f"```{file_path}\n{content}\n```\n\n"
            
            prompt_stage2 = FORM_PROMPT_STAGE2.format(
                refined_request=refined_request,
                selected_files_content=selected_files_content
            )
            
            logger.info(f"Form stage 2 prompt:\n{prompt_stage2}")
            
            result_stage2 = await make_ai_api_call(prompt_stage2, max_tokens=4096)
            
            logger.info(f"Form stage 2 response:\n{result_stage2}")
            
            # Parse stage 2 response
            changes = parse_ai_output(result_stage2)
            
            # If parsing failed, create a basic structure
            if not isinstance(changes, dict) or "files" not in changes:
                changes = {"files": {}}
                # Try to extract file contents directly
                for file_path in valid_selected_files:
                    match = re.search(rf'"{file_path}"\s*:\s*"(.*?)"', result_stage2, re.DOTALL)
                    if match:
                        content = match.group(1)
                        changes["files"][file_path] = content
            
            return changes
        except Exception as e:
            logger.error(f"Failed to parse form changes: {str(e)}")
            logger.error(traceback.format_exc())
            return {"files": {}}
    except Exception as e:
        logger.error(f"Failed to generate form changes: {str(e)}")
        return {"files": {}}

async def generate_static_changes(refined_request: str, current_files: dict) -> dict:
    """Generate static file changes using a two-stage approach"""
    if DEBUG_STATIC:
        logger.info(f"Generating static changes for: {refined_request}")
        logger.info(f"Current static files: {list(current_files.keys())}")
    
    # STAGE 1: Only send filenames and directories to select relevant files
    current_static = {k: v for k, v in current_files.items() if k.startswith('static/')}
    file_list = "\n".join(f"- {k}" for k in current_static.keys())
    
    prompt_stage1 = STATIC_PROMPT_STAGE1.format(
        refined_request=refined_request,
        file_list=file_list
    )
    
    if DEBUG_STATIC:
        logger.info(f"Static stage 1 prompt:\n{prompt_stage1}")
    
    try:
        result_stage1 = await make_ai_api_call(prompt_stage1)
        
        if DEBUG_STATIC:
            logger.info(f"Static stage 1 response:\n{result_stage1}")
        
        try:
            # Parse stage 1 response to get selected files
            selected_files = []
            
            # Try to parse as JSON directly first
            try:
                json_data = json.loads(result_stage1)
                if isinstance(json_data, dict) and 'selected_files' in json_data:
                    selected_files = json_data['selected_files']
            except json.JSONDecodeError:
                # Try to extract from the response
                match = re.search(r'"selected_files"\s*:\s*\[(.*?)\]', result_stage1, re.DOTALL)
                if match:
                    # Extract the content between brackets
                    files_str = match.group(1)
                    # Split by commas, strip whitespace and quotes
                    selected_files = [f.strip().strip('"\'') for f in files_str.split(',')]
            
            if not selected_files:
                logger.error("No files selected in stage 1")
                return {"files": {}}
            
            # Filter out files that aren't in the current_files list
            valid_selected_files = [f for f in selected_files if f in current_files]
            if not valid_selected_files:
                # Look for valid files in current_files that match part of the selected paths
                valid_selected_files = []
                for selected in selected_files:
                    for current in current_files.keys():
                        if selected.split('/')[-1] in current:
                            valid_selected_files.append(current)
                            break
            
            if not valid_selected_files:
                logger.error("No valid files found after filtering")
                return {"files": {}}
            
            # STAGE 2: Send content of the selected files for detailed analysis
            selected_files_content = ""
            for file_path in valid_selected_files:
                content = current_files[file_path]
                selected_files_content += f"```{file_path}\n{content}\n```\n\n"
            
            prompt_stage2 = STATIC_PROMPT_STAGE2.format(
                refined_request=refined_request,
                selected_files_content=selected_files_content
            )
            
            if DEBUG_STATIC:
                logger.info(f"Static stage 2 prompt:\n{prompt_stage2}")
            
            result_stage2 = await make_ai_api_call(prompt_stage2, max_tokens=4096)
            
            if DEBUG_STATIC:
                logger.info(f"Static stage 2 response:\n{result_stage2}")
            
            # Parse stage 2 response
            changes = parse_ai_output(result_stage2)
            
            # If parsing failed, create a basic structure
            if not isinstance(changes, dict) or "files" not in changes:
                changes = {"files": {}}
                # Try to extract file contents directly
                for file_path in valid_selected_files:
                    match = re.search(rf'"{file_path}"\s*:\s*"(.*?)"', result_stage2, re.DOTALL)
                    if match:
                        content = match.group(1)
                        changes["files"][file_path] = content
            
            return changes
        except Exception as e:
            logger.error(f"Failed to parse static changes: {str(e)}")
            logger.error(traceback.format_exc())
            return {"files": {}}
    except Exception as e:
        if DEBUG_STATIC:
            logger.error(f"Failed to generate static changes: {str(e)}")
        return {"files": {}}

def sanitize_ai_response(text: str) -> str:
    """
    Clean up AI-generated code to remove problematic characters and fix common issues
    """
    if not text:
        return text
        
    # Replace Unicode characters that may cause issues in Python code
    replacements = {
        '\u200b': '',  # Zero width space
        '\u00a0': ' ',  # Non-breaking space
        '\u2010': '-',  # Hyphen
        '\u2011': '-',  # Non-breaking hyphen
        '\u2012': '-',  # Figure dash
        '\u2013': '-',  # En dash
        '\u2014': '-',  # Em dash
        '\u2015': '-',  # Horizontal bar
        '\uff08': '(',  # Fullwidth left parenthesis
        '\uff09': ')',  # Fullwidth right parenthesis
        '\uff1a': ':',  # Fullwidth colon
        '\uff1b': ';',  # Fullwidth semicolon
        '\uff1c': '<',  # Fullwidth less than
        '\uff1d': '=',  # Fullwidth equals
        '\uff1e': '>',  # Fullwidth greater than
        '\uff1f': '?',  # Fullwidth question mark
        '\u3000': ' ',  # Ideographic space
    }
    
    # Apply all replacements
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    
    # Clean up escaped backslashes in code (\\ -> \)
    text = text.replace('\\\\', '\\')
    
    # Fix common formatting issues in code
    text = text.replace('.\\ ', '.')
    text = text.replace('\\ ', '')
    text = text.replace('`` `', '```')
    text = text.replace('` ``', '```')
    
    # Remove "noqa" comments
    text = re.sub(r'\s*#\s*noqa.*', '', text)
    
    # Remove markdown code block markers if present
    if text.startswith('```') and text.endswith('```'):
        # Get the language identifier if present
        if text.startswith('```python'):
            text = text[9:-3].strip()
        else:
            text = text[3:-3].strip()
            
    return text

async def call_ai_multi_file(conversation, text, files_data):
    """Call AI service for multiple file changes with validation and refinement."""
    try:
        response = {
            'files': {},
            'metadata': {
                'files_processed': 0,
                'files_skipped': 0,
                'validation_attempts': 0
            }
        }

        # Handle refinement requests
        if isinstance(files_data, dict) and files_data.get('refinement_request'):
            try:
                result = await call_ai_api_async(prompt=text, max_tokens=8192, temperature=0.2)
                if result:
                    response['files'] = {'refined_content': result}
                return response
            except Exception as e:
                logger.error(f"Error in refinement request: {str(e)}")
                return {'error': str(e)}

        # Process AI-generated file changes
        validator = DjangoCodeValidator()
        max_validation_attempts = 3
        max_retry_attempts = 2

        # Assume files_data is from generate_template_changes or similar
        for attempt in range(max_retry_attempts):
            files_to_process = files_data.get('files', {}) if isinstance(files_data, dict) else files_data
            if attempt > 0:
                logger.info(f"Retrying AI call, attempt {attempt + 1}")
                # Re-call AI functions (e.g., generate_template_changes) if needed
                # This assumes files_data is the output of generate_template_changes
                files_to_process = await generate_template_changes(
                    files_data.get('refined_request', text),
                    files_data.get('context', {}),
                    files_data.get('file_list', ''),
                    files_data.get('project_name', ''),
                    files_data.get('app_name', ''),
                    text
                )
                files_to_process = files_to_process.get('files', {})

            for file_path, content in files_to_process.items():
                try:
                    # Skip invalid file paths
                    if not file_path or not isinstance(file_path, str):
                        logger.warning("Invalid file path, skipping")
                        response['metadata']['files_skipped'] += 1
                        continue

                    # Validate content type
                    if not isinstance(content, str):
                        logger.error(f"Invalid content type for {file_path}: {type(content)}")
                        response['metadata']['files_skipped'] += 1
                        if attempt < max_retry_attempts - 1:
                            continue
                        break

                    # Validate and refine content
                    current_content = content
                    is_valid = False
                    validation_issues = []

                    for val_attempt in range(max_validation_attempts):
                        response['metadata']['validation_attempts'] += 1
                        
                        # Skip empty content
                        if not current_content or not current_content.replace('\n', '').replace(' ', ''):
                            logger.warning(f"Empty content for {file_path}, skipping")
                            break

                        # Validate current content
                        is_valid, issues = validator.validate_file(file_path, current_content)
                        if is_valid:
                            response['files'][file_path] = current_content
                            response['metadata']['files_processed'] += 1
                            logger.info(f"File {file_path} validated successfully on attempt {val_attempt + 1}")
                            break

                        # Store issues for refinement
                        validation_issues = issues

                        if val_attempt < max_validation_attempts - 1:
                            refinement_prompt = f"""
Please fix the following validation issues in {file_path}:
{', '.join(issues)}

Current content:
{current_content}

Requirements:
1. Fix all validation issues
2. Maintain the same functionality
3. Ensure proper syntax and imports
4. Return only the fixed content as a string
"""
                            try:
                                refined_result = await call_ai_api_async(
                                    refinement_prompt,
                                    file_path,
                                    max_tokens=8192,
                                    temperature=0.2 + (val_attempt * 0.1)
                                )
                                if refined_result and isinstance(refined_result, str):
                                    current_content = refined_result
                                    continue
                            except Exception as e:
                                logger.error(f"Refinement attempt {val_attempt + 1} failed: {str(e)}")

                        logger.warning(f"Validation failed for {file_path} after {val_attempt + 1} attempts: {issues}")

                    if not is_valid:
                        response['metadata']['files_skipped'] += 1
                        logger.error(f"Failed to validate {file_path} after {max_validation_attempts} attempts")

                except Exception as e:
                    logger.error(f"Error processing {file_path}: {str(e)}")
                    response['metadata']['files_skipped'] += 1
                    continue

            if response['files']:
                break  # Exit retry loop if valid files are processed

        if not response['files']:
            logger.error("No valid files in response")
            return {'error': 'No valid code changes were generated'}

        logger.info(f"Processed {response['metadata']['files_processed']} files successfully")
        return response

    except Exception as e:
        logger.error(f"Error in call_ai_multi_file: {str(e)}")
        logger.error(traceback.format_exc())
        return {'error': str(e)}

def validate_generated_code(file_path: str, content: str) -> bool:
    """Validate generated code based on file type"""
    try:
        if not content.strip():
            logger.error(f"Empty content for {file_path}")
            return False
            
        if file_path.endswith('.py'):
            # Validate Python syntax
            ast.parse(content)
            # Check for common issues
            if 'import' not in content:
                logger.error(f"No imports found in Python file {file_path}")
                return False
        elif file_path.endswith('.html'):
            # Basic HTML validation
            if not ('<html' in content.lower() or '{% extends' in content):
                logger.error(f"No HTML structure or template inheritance in {file_path}")
                return False
            # Check for unclosed tags
            if content.count('{%') != content.count('%}'):
                logger.error(f"Mismatched template tags in {file_path}")
                return False
        elif file_path.endswith('.js'):
            # Basic JS validation
            if not content.strip():
                logger.error(f"Empty JS file {file_path}")
                return False
            # Check for syntax errors
            try:
                ast.parse(content)
            except:
                logger.error(f"JS syntax error in {file_path}")
                return False
        return True
    except Exception as e:
        logger.error(f"Code validation failed for {file_path}: {str(e)}")
        return False

async def analyze_request(message: str) -> dict:
    """Analyze the request to determine affected components and specific file patterns"""
    # Base component analysis
    components = {
        'templates': bool(re.search(r'(page|template|html|view|display)', message, re.I)),
        'models': bool(re.search(r'(database|model|table|field|data)', message, re.I)),
        'views': bool(re.search(r'(view|page|endpoint|api|route)', message, re.I)),
        'static': bool(re.search(r'(css|style|js|javascript|graph|chart)', message, re.I))
    }
    
    # Extract specific keywords that might indicate file names or features
    keywords = set(re.findall(r'\b\w+\b', message.lower()))
    
    # Analyze for specific file patterns
    file_patterns = {
        'templates': [kw for kw in keywords if any(pattern in kw for pattern in ['page', 'form', 'list', 'detail', 'dashboard'])],
        'models': [kw for kw in keywords if any(pattern in kw for pattern in ['model', 'table', 'entity'])],
        'views': [kw for kw in keywords if any(pattern in kw for pattern in ['view', 'api', 'endpoint'])],
        'static': [kw for kw in keywords if any(pattern in kw for pattern in ['style', 'script', 'chart'])]
    }
    
    return {
        'components': components,
        'patterns': file_patterns,
        'keywords': keywords
    }

async def get_relevant_files(project, request_analysis: dict) -> dict:
    """Get relevant files based on detailed request analysis"""
    files = {}
    components = request_analysis['components']
    patterns = request_analysis['patterns']
    keywords = request_analysis['keywords']
    
    async def filter_files(queryset, path_prefix: str):
        """Helper to filter files based on keywords and patterns"""
        relevant_files = {}
        async for file in queryset:
            # Check if file name matches any keyword or pattern
            file_name_lower = file.path.lower()
            
            # Direct keyword match in filename
            if any(kw in file_name_lower for kw in keywords):
                relevant_files[f'{path_prefix}/{file.path}'] = file.content
                continue
                
            # Pattern match in filename
            component_type = path_prefix.rstrip('s')  # Remove trailing 's' to match pattern keys
            if component_type in patterns and any(pattern in file_name_lower for pattern in patterns[component_type]):
                relevant_files[f'{path_prefix}/{file.path}'] = file.content
                continue
            
            # If no specific matches but it's a main/base file, include it
            if any(base in file_name_lower for base in ['base', 'main', 'index', 'common']):
                relevant_files[f'{path_prefix}/{file.path}'] = file.content
                
        return relevant_files

    if components['templates']:
        templates = await sync_to_async(TemplateFile.objects.filter)(project=project)
        template_files = await filter_files(templates, 'templates')
        files.update(template_files)

    if components['views']:
        views = await sync_to_async(ViewFile.objects.filter)(project=project)
        view_files = await filter_files(views, 'views')
        files.update(view_files)

    if components['models']:
        models = await sync_to_async(ModelFile.objects.filter)(project=project)
        model_files = await filter_files(models, 'models')
        files.update(model_files)

    if components['static']:
        static = await sync_to_async(StaticFile.objects.filter)(project=project)
        static_files = await filter_files(static, 'static')
        files.update(static_files)

    # If no files were found but components were identified, include base files
    if not files:
        for component, needed in components.items():
            if needed:
                base_files = await sync_to_async(globals()[f"{component.rstrip('s')}File"].objects.filter)(
                    project=project,
                    path__icontains='base'
                )
                async for file in base_files:
                    files[f'{component}/{file.path}'] = file.content

    return files

def parse_ai_output(prompt_result, field_format='json'):
    """
    Parse the AI model's output to extract usable data
    
    This function handles various JSON parsing issues and cleans up the response.
    """
    if not prompt_result:
        logger.error("Empty response from AI model")
        return None
        
    # Remove any prefixes like "Model: Post" etc.
    if field_format == 'json':
        # Remove any preamble before the first '{'
        if '{' in prompt_result:
            json_start = prompt_result.find('{')
            prompt_result = prompt_result[json_start:]
            
        # Remove any content after the last '}'
        if '}' in prompt_result:
            json_end = prompt_result.rfind('}') + 1
            prompt_result = prompt_result[:json_end]
            
        # Fix common JSON formatting errors
        prompt_result = fix_json_formatting(prompt_result)
        
        try:
            # Try to parse the JSON
            return json.loads(prompt_result)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from AI response: {str(e)}")
            logger.error(f"Problematic JSON: {prompt_result}")
            
            # Try to extract useful data using regex as a fallback
            return extract_json_with_regex(prompt_result)
            
    return prompt_result

def fix_json_formatting(json_str):
    """Fix common JSON formatting errors"""
    # Replace trailing commas before closing brackets
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)
    
    # Fix unbalanced brackets by removing extra closing brackets
    open_braces = json_str.count('{')
    close_braces = json_str.count('}')
    if close_braces > open_braces:
        json_str = json_str[:-(close_braces - open_braces)]
    
    # Add any missing closing brackets
    elif open_braces > close_braces:
        json_str += '}' * (open_braces - close_braces)
    
    # Fix any invalid escape sequences
    json_str = json_str.replace('\\\\', '\\')
    
    return json_str

def extract_json_with_regex(text):
    """Extract JSON parts using regex when JSON parsing fails"""
    result = {}
    
    # Try to extract refined_request using regex
    refined_match = re.search(r'"refined_request"\s*:\s*"([^"]+)"', text)
    if refined_match:
        result["refined_request"] = refined_match.group(1)
    
    # Try to extract file_types
    file_types = {}
    for file_type in ["template", "view", "model", "static", "url"]:
        file_type_match = re.search(rf'"{file_type}"\s*:\s*\[(.*?)\]', text, re.DOTALL)
        if file_type_match:
            items_str = file_type_match.group(1)
            items = []
            for item_match in re.finditer(r'"([^"]+)"', items_str):
                items.append(item_match.group(1))
            file_types[file_type] = items
    
    if file_types:
        result["file_types"] = file_types
    
    return result if result else None

def preprocess_django_templates(text):
    """Replace Django template tags with placeholders to avoid JSON parsing issues"""
    # Replace {% ... %} tags
    text = re.sub(r'{%\s+([^}]*?)\s+%}', r'DJANGO_TAG_OPEN_\1_DJANGO_TAG_CLOSE', text)
    
    # Replace {{ ... }} expressions
    text = re.sub(r'{{\s+([^}]*?)\s+}}', r'DJANGO_VAR_OPEN_\1_DJANGO_VAR_CLOSE', text)
    
    # Replace {# ... #} comments
    text = re.sub(r'{#\s+([^}]*?)\s+#}', r'DJANGO_COMMENT_OPEN_\1_DJANGO_COMMENT_CLOSE', text)
    
    return text

def postprocess_django_template(template_content):
    """Postprocess Django template content to restore template tags from placeholders"""
    # Restore Django template tags from placeholders
    processed = template_content.replace('EXTENDS_BASE_TEMPLATE', "{% extends 'base.html' %}")
    processed = re.sub(r'BLOCK_START_(\w+)', r'{% block \1 %}', processed)
    processed = re.sub(r'BLOCK_END', r'{% endblock %}', processed)
    processed = re.sub(r'CSRF_TOKEN_PLACEHOLDER', r'{% csrf_token %}', processed)
    processed = re.sub(r'VAR_(\w+)', r'{{ \1 }}', processed)
    processed = re.sub(r'TAG_(\w+)', r'{% \1 %}', processed)
    return processed

class AIEditor:
    def __init__(self, project_id, app_name=None):
        self.project_id = project_id
        self.app_name = app_name
        # Ensure the project is loaded in the FileIndexer
        FileIndexer.load_index(project_id)
        
    def validate_file_path(self, file_path):
        """
        Validate and normalize a file path
        Returns tuple (normalized_path, error_message)
        """
        if not file_path:
            return None, "File path cannot be empty"
            
        # Normalize path
        try:
            # Use FileIndexer's normalize_path for consistent handling
            path = FileIndexer._normalize_path(file_path)
            logger.debug(f"AIEditor validating path: {file_path} -> {path}")
        except Exception as e:
            logger.error(f"Path normalization error: {e}")
            return None, f"Invalid path format: {file_path}"
            
        # Find matching file
        file_obj = FileIndexer.find_file(self.project_id, path)
        if not file_obj:
            # Try fuzzy matching
            candidates = FileIndexer.get_candidates(self.project_id, self.app_name)
            suggestions = []
            for c in candidates:
                similarity = FileIndexer._similarity_ratio(path, c)
                if similarity > 0.6:
                    suggestions.append((c, similarity))
            
            # Sort by similarity and get top 3
            suggestions.sort(key=lambda x: x[1], reverse=True)
            top_suggestions = [s[0] for s in suggestions[:3]]
            
            if top_suggestions:
                return None, f"File not found. Did you mean one of: {', '.join(top_suggestions)}?"
            return None, f"File not found: {path}"
        
        # Always return the canonical path from the file object
        return file_obj.path, None
        
    def get_file_content(self, file_path):
        """Get file content with validation"""
        norm_path, error = self.validate_file_path(file_path)
        if error:
            raise ValueError(error)
            
        return FileIndexer.get_content(self.project_id, norm_path)
        
    def create_change_request(self, file_path, new_content, conversation_id):
        """Create change request with validation"""
        norm_path, error = self.validate_file_path(file_path)
        if error:
            raise ValueError(error)
            
        # Get conversation
        try:
            conv = AIConversation.objects.get(id=conversation_id)
        except AIConversation.DoesNotExist:
            raise ValueError(f"Conversation {conversation_id} not found")
            
        # Create change request
        change = AIChangeRequest.objects.create(
            conversation=conv,
            project_id=self.project_id,
            file_path=norm_path,
            diff={norm_path: new_content},
            files=[norm_path]
        )
        
        return change
        
    def apply_changes(self, change_request):
        """Apply changes with validation"""
        if not isinstance(change_request, AIChangeRequest):
            raise ValueError("Invalid change request object")
            
        # Validate all file paths
        for file_path in change_request.files:
            norm_path, error = self.validate_file_path(file_path)
            if error:
                raise ValueError(f"Invalid file path in change request: {error}")
                
        # Apply changes
        for file_path, new_content in change_request.diff.items():
            norm_path, _ = self.validate_file_path(file_path)
            file_obj = FileIndexer.find_file(self.project_id, norm_path)
            file_obj.content = new_content
            file_obj.save()
            
        # Reload index
        FileIndexer.reload_project(self.project_id)