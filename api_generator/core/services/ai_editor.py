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
    AIMessage
)
from .classifier import classify_request

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

async def call_ai(conversation, last_user_message, context_files):
    """Async version of AI API call"""
    cache_key = f"ai_response_{conversation.id}_{hash(last_user_message)}"
    cached_response = cache.get(cache_key)
    if cached_response:
        return cached_response

    history = await get_cached_conversation_history(conversation.id)
    history.append(f"User: {last_user_message}")

    file_list = "\n".join(f"- {p}" for p in context_files.keys())
    prompt = SYSTEM_PROMPT.format(
        project_name=conversation.project.name,
        app_name=conversation.app_name or "—",
        file_list=file_list
    )

    # Only include relevant files based on the message
    relevant_files = {}
    for path, content in context_files.items():
        if any(keyword in last_user_message.lower() for keyword in path.lower().split('/')):
            relevant_files[path] = get_cached_file_content(path, content)

    for path, content in relevant_files.items():
        prompt += f"```{path}\n{content}\n```\n\n"
    prompt += "\n".join(history[-5:]) + "\nAssistant:"

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
    """Refine user request to improve AI prompting"""
    if DEBUG_REFINE:
        logger.info("Refining request...")
    
    # Get project data first using sync_to_async
    get_project_name = sync_to_async(lambda: conversation.project.name)
    get_app_name = sync_to_async(lambda: conversation.app_name or "---")
    
    project_name = await get_project_name()
    app_name = await get_app_name()
    
    prompt = REFINE_PROMPT.format(
        user_message=user_message,
        project_name=project_name,
        app_name=app_name
    )
    
    try:
        # Use proper async HTTP request
        result = await make_ai_api_call(prompt)
        
        try:
            # Try to parse as JSON
            result_json = json.loads(result)
            if DEBUG_REFINE:
                logger.info(f"Request refined: {json.dumps(result_json, indent=2)}")
            return result_json
        except json.JSONDecodeError:
            # If not valid JSON, extract JSON portion
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                try:
                    result_json = json.loads(json_match.group(0))
                    if DEBUG_REFINE:
                        logger.info(f"Extracted JSON from response: {json.dumps(result_json, indent=2)}")
                    return result_json
                except json.JSONDecodeError:
                    # Still not valid JSON
                    logger.error(f"Failed to extract valid JSON from response: {result}")
                    return {
                        "refined_request": user_message,
                        "file_types": {
                            "template": [],
                            "view": [],
                            "model": [],
                            "static": [],
                            "url": []
                        }
                    }
            else:
                logger.error(f"No JSON found in response: {result}")
                return {
                    "refined_request": user_message,
                    "file_types": {
                        "template": [],
                        "view": [],
                        "model": [],
                        "static": [],
                        "url": []
                    }
                }
    except Exception as e:
        logger.error(f"Error refining request: {str(e)}")
        return {
            "refined_request": user_message,
            "file_types": {
                "template": [],
                "view": [],
                "model": [],
                "static": [],
                "url": []
            }
        }

async def make_ai_api_call(prompt: str, max_tokens: int = 2048) -> str:
    """Make an async API call to the AI service with retry on rate limiting"""
    max_retries = 3
    base_retry_delay = 2  # start with 2 second delay
    
    for attempt in range(max_retries):
        try:
            # Wait 1 second before first attempt to avoid immediate rate limits
            if attempt == 0:
                await asyncio.sleep(1)
                
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    API_URL,
                    json={
                        "model": MISTRAL_MODEL,
                        "prompt": prompt,
                        "temperature": 0.2,
                        "max_tokens": max_tokens,
                        "top_p": 0.7,
                        "frequency_penalty": 0.5,
                    },
                    headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"},
                    timeout=60  # Increased timeout
                ) as response:
                    if response.status == 429:  # Too Many Requests
                        logger.warning(f"Rate limited by AI API (attempt {attempt+1}/{max_retries})")
                        if attempt < max_retries - 1:
                            # Exponential backoff with jitter
                            wait_time = base_retry_delay * (2 ** attempt) + random.uniform(0, 1)
                            logger.info(f"Waiting {wait_time:.2f} seconds before retrying...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error("Rate limit exceeded, max retries reached")
                            return json.dumps({"files": {}, "error": "Rate limit exceeded"})
                    
                    response.raise_for_status()
                    result = await response.json()
                    return result["choices"][0]["text"].strip()
        except aiohttp.ClientResponseError as e:
            if e.status == 429 and attempt < max_retries - 1:
                wait_time = base_retry_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.info(f"Waiting {wait_time:.2f} seconds before retrying...")
                await asyncio.sleep(wait_time)
                continue
            logger.error(f"API response error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"API call error: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = base_retry_delay * (2 ** attempt)
                logger.info(f"Error occurred, waiting {wait_time} seconds before retrying...")
                await asyncio.sleep(wait_time)
                continue
            raise

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

async def generate_template_changes(refined_request: str, current_files: dict) -> dict:
    """Generate template-specific changes using a two-stage approach"""
    if DEBUG_TEMPLATE:
        logger.info(f"Generating template changes for: {refined_request}")
        logger.info(f"Current template files: {list(current_files.keys())}")
    
    # STAGE 1: Only send filenames and directories to select relevant files
    file_list = "\n".join(f"- {k}" for k in current_files.keys())
    
    prompt_stage1 = TEMPLATE_PROMPT_STAGE1.format(
        refined_request=refined_request,
        file_list=file_list
    )
    
    if DEBUG_TEMPLATE:
        logger.info(f"Template stage 1 prompt:\n{prompt_stage1}")
    
    try:
        result_stage1 = await make_ai_api_call(prompt_stage1)
        
        if DEBUG_TEMPLATE:
            logger.info(f"Template stage 1 response:\n{result_stage1}")
        
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
            
            # STAGE 2: Send content of the selected files for detailed analysis
            selected_files_content = ""
            for file_path in selected_files:
                if file_path in current_files:
                    content = current_files[file_path]
                    selected_files_content += f"```{file_path}\n{content}\n```\n\n"
                else:
                    logger.warning(f"Selected file {file_path} not found in current_files")
            
            prompt_stage2 = TEMPLATE_PROMPT_STAGE2.format(
                refined_request=refined_request,
                selected_files_content=selected_files_content
            )
            
            if DEBUG_TEMPLATE:
                logger.info(f"Template stage 2 prompt:\n{prompt_stage2}")
            
            result_stage2 = await make_ai_api_call(prompt_stage2, max_tokens=4096)
            
            if DEBUG_TEMPLATE:
                logger.info(f"Template stage 2 response:\n{result_stage2}")
            
            # Parse stage 2 response
            changes = parse_ai_output(result_stage2)
            
            # Process Django template tags
            if isinstance(changes, dict) and "files" in changes:
                for path, content in changes["files"].items():
                    if path.endswith(".html"):
                        changes["files"][path] = postprocess_django_template(content)
            
            return changes
        except Exception as e:
            logger.error(f"Failed to parse template changes: {str(e)}")
            logger.error(traceback.format_exc())
            return {"files": {}}
    except Exception as e:
        if DEBUG_TEMPLATE:
            logger.error(f"Failed to generate template changes: {str(e)}")
        return {"files": {}}

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

async def call_ai_multi_file(conversation, last_user_message, context_files):
    """
    Enhanced AI function to process multiple files, identifying which ones need changes and modifying them
    individually to reduce parsing complexity. This implements a safer approach where we process each file
    separately rather than trying to parse complex JSON responses.
    """
    try:
        logger.info("Starting call_ai_multi_file")
        project_id = conversation.project_id
        from create_api.models import Project
        project = await Project.objects.aget(id=project_id)
        
        # First refine the request to determine what needs to be changed
        logger.info("Refining request...")
        refinement_result = await refine_request(conversation, last_user_message)
        logger.info(f"Refinement result: {refinement_result}")
        
        # Sort files by type
        template_files = {}
        view_files = {}
        model_files = {}
        form_files = {}
        static_files = {}
        
        for path, content in context_files.items():
            # Only save the file paths now, not the content
            if path.endswith('.html') or path.startswith('templates/'):
                template_files[path] = content
            elif 'views.py' in path or path.endswith('_view.py'):
                view_files[path] = content
            elif 'models.py' in path or path.endswith('_model.py'):
                model_files[path] = content
            elif 'forms.py' in path or path.endswith('_form.py'):
                form_files[path] = content
            elif path.startswith('static/') or path.endswith('.css') or path.endswith('.js'):
                static_files[path] = content
        
        # Track completed changes
        combined_changes = {"files": {}}
        
        # Analyze request for common code change patterns
        code_change_indicators = ['add', 'create', 'update', 'modify', 'change', 'implement', 'fix', 'build', 'develop']
        is_likely_code_change = any(indicator in last_user_message.lower() for indicator in code_change_indicators)
        
        # If this doesn't seem like a code change request, make sure we still treat it as one
        if not is_likely_code_change:
            logger.info("Request doesn't contain explicit code change terms, but will still generate code changes")
            
        # Process template files if relevant to the request
        template_files_to_change = []
        if template_files and ('template' in refinement_result.get('file_types', {}) or any(term in last_user_message.lower() for term in ['html', 'template', 'page', 'form'])):
            logger.info(f"Letting AI access all {len(template_files)} template files to determine relevance")
            file_list = "\n".join(f"- {path}" for path in template_files.keys())
            
            prompt_stage1 = TEMPLATE_PROMPT_STAGE1.format(
                refined_request=refinement_result.get('refined_request', last_user_message),
                file_list=file_list
            )
            
            logger.info(f"Template stage 1 prompt:\n{prompt_stage1}")
            template_result_stage1 = await make_ai_api_call(prompt_stage1)
            logger.info(f"Template stage 1 response:\n{template_result_stage1}")
            
            # Extract selected files
            try:
                json_data = json.loads(template_result_stage1)
                if isinstance(json_data, dict) and 'selected_files' in json_data:
                    template_files_to_change = json_data['selected_files']
            except json.JSONDecodeError:
                match = re.search(r'"selected_files"\s*:\s*\[(.*?)\]', template_result_stage1, re.DOTALL)
                if match:
                    files_str = match.group(1)
                    template_files_to_change = [f.strip().strip('"\'') for f in files_str.split(',')]
            
            # Validate file selection to ensure we're only modifying actually needed files
            validated_files, rejected_files = await validate_file_selection(
                template_files_to_change, 
                refinement_result.get('refined_request', last_user_message),
                file_type="template"
            )
            
            if rejected_files:
                logger.info(f"Removed {len(rejected_files)} unnecessary template files: {rejected_files}")
                
            template_files_to_change = validated_files
            
            # Stage 2: Process each template file individually
            for file_path in template_files_to_change:
                if file_path in template_files:
                    # For each selected file, make a dedicated AI call
                    logger.info(f"Processing template file: {file_path}")
                    content = template_files[file_path]
                    
                    # Create a specific prompt just for this file
                    file_prompt = f"""
You are a Django template expert. Modify this template file to implement the following request:
{refinement_result.get('refined_request', last_user_message)}

Here is the current content of the file:
```{file_path}
{content}
```

Return ONLY the complete modified content of the file. Do not include any explanations, JSON formatting, or markdown code blocks.
Just return the raw template code that should replace the file content.
"""
                    try:
                        # Make a dedicated call for this file
                        template_content = await make_ai_api_call(file_prompt, max_tokens=4096)
                        
                        # Extract the content (no JSON parsing needed)
                        # Remove any markdown code blocks if present
                        clean_content = re.sub(r'```.*?\n|```', '', template_content)
                        
                        # Process Django template tags if needed
                        if file_path.endswith('.html'):
                            clean_content = postprocess_django_template(clean_content)
                        
                        # Validate and potentially fix the generated code
                        is_valid, issues, validated_content = await validate_code_with_ai(file_path, clean_content)
                        
                        if not is_valid:
                            logger.warning(f"AI validation found issues with {file_path}: {issues}")
                            # If the AI couldn't fix it or didn't provide fixed content, try again
                            if validated_content == clean_content:
                                # Try once more with a more targeted prompt
                                repair_prompt = f"""
You are a Django template expert. The following HTML template has issues that need to be fixed:
{issues}

Here is the template with issues:
```{file_path}
{clean_content}
```

Please provide a corrected version of this template. Return ONLY the fixed template content 
with no explanations, JSON formatting, or markdown code blocks.
"""
                                try:
                                    repaired_content = await make_ai_api_call(repair_prompt, max_tokens=4096)
                                    clean_content = re.sub(r'```.*?\n|```', '', repaired_content)
                                    
                                    # Validate the repaired content
                                    basic_valid, basic_issues = basic_code_syntax_check(file_path, clean_content)
                                    if not basic_valid:
                                        logger.warning(f"Repair attempt still has issues: {basic_issues}")
                                    else:
                                        logger.info(f"Successfully repaired {file_path}")
                                except Exception as repair_err:
                                    logger.error(f"Error repairing {file_path}: {str(repair_err)}")
                            else:
                                # Use the AI-fixed content
                                clean_content = validated_content
                                logger.info(f"Using AI-fixed content for {file_path}")
                        
                        # Add to our combined changes
                        combined_changes["files"][file_path] = clean_content
                    except Exception as e:
                        logger.error(f"Error processing template file {file_path}: {str(e)}")
        
        # Process view files similarly
        view_files_to_change = []
        if view_files and ('view' in refinement_result.get('file_types', {}) or any(term in last_user_message.lower() for term in ['view', 'page', 'route', 'api', 'endpoint'])):
            logger.info(f"Letting AI access all {len(view_files)} view files to determine relevance")
            file_list = "\n".join(f"- {path}" for path in view_files.keys())
            
            prompt_stage1 = VIEW_PROMPT_STAGE1.format(
                refined_request=refinement_result.get('refined_request', last_user_message),
                file_list=file_list
            )
            
            logger.info(f"View stage 1 prompt:\n{prompt_stage1}")
            view_result_stage1 = await make_ai_api_call(prompt_stage1)
            logger.info(f"View stage 1 response:\n{view_result_stage1}")
            
            # Extract selected files
            try:
                json_data = json.loads(view_result_stage1)
                if isinstance(json_data, dict) and 'selected_files' in json_data:
                    view_files_to_change = json_data['selected_files']
            except json.JSONDecodeError:
                match = re.search(r'"selected_files"\s*:\s*\[(.*?)\]', view_result_stage1, re.DOTALL)
                if match:
                    files_str = match.group(1)
                    view_files_to_change = [f.strip().strip('"\'') for f in files_str.split(',')]
            
            # Validate file selection to ensure we're only modifying actually needed files
            validated_files, rejected_files = await validate_file_selection(
                view_files_to_change, 
                refinement_result.get('refined_request', last_user_message),
                file_type="view"
            )
            
            if rejected_files:
                logger.info(f"Removed {len(rejected_files)} unnecessary view files: {rejected_files}")
                
            view_files_to_change = validated_files
                
            # Find valid matches in the context files
            valid_view_files = []
            for selected in view_files_to_change:
                if selected in view_files:
                    valid_view_files.append(selected)
                else:
                    # Try to find a match by filename without path
                    selected_basename = selected.split('/')[-1]
                    for current in view_files.keys():
                        if selected_basename in current:
                            valid_view_files.append(current)
                            break
            
            # Process each view file individually
            for file_path in valid_view_files:
                if file_path in view_files:
                    logger.info(f"Processing view file: {file_path}")
                    content = view_files[file_path]
                    
                    file_prompt = f"""
You are a Django view expert. Modify this view file to implement the following request:
{refinement_result.get('refined_request', last_user_message)}

Here is the current content of the file:
```{file_path}
{content}
```

Return ONLY the complete modified content of the file. Do not include any explanations, JSON formatting, or markdown code blocks.
Just return the raw Python code that should replace the file content.
"""
                    try:
                        view_content = await make_ai_api_call(file_prompt, max_tokens=4096)
                        clean_content = re.sub(r'```.*?\n|```', '', view_content)
                        
                        # Validate and potentially fix the generated code
                        is_valid, issues, validated_content = await validate_code_with_ai(file_path, clean_content)
                        
                        if not is_valid:
                            logger.warning(f"AI validation found issues with view file {file_path}: {issues}")
                            # If the AI couldn't fix it or didn't provide fixed content, try again
                            if validated_content == clean_content:
                                # Try once more with a more targeted prompt
                                repair_prompt = f"""
You are a Django view expert. The following Python view has issues that need to be fixed:
{issues}

Here is the view code with issues:
```{file_path}
{clean_content}
```

Please provide a corrected version of this view. Return ONLY the fixed Python code 
with no explanations, JSON formatting, or markdown code blocks.
"""
                                try:
                                    repaired_content = await make_ai_api_call(repair_prompt, max_tokens=4096)
                                    clean_content = re.sub(r'```.*?\n|```', '', repaired_content)
                                    
                                    # Validate the repaired content
                                    basic_valid, basic_issues = basic_code_syntax_check(file_path, clean_content)
                                    if not basic_valid:
                                        logger.warning(f"Repair attempt still has issues: {basic_issues}")
                                    else:
                                        logger.info(f"Successfully repaired view {file_path}")
                                except Exception as repair_err:
                                    logger.error(f"Error repairing view {file_path}: {str(repair_err)}")
                            else:
                                # Use the AI-fixed content
                                clean_content = validated_content
                                logger.info(f"Using AI-fixed content for view {file_path}")
                        
                        combined_changes["files"][file_path] = clean_content
                    except Exception as e:
                        logger.error(f"Error processing view file {file_path}: {str(e)}")
        
        # Process model files similarly
        model_files_to_change = []
        if model_files and ('model' in refinement_result.get('file_types', {}) or any(term in last_user_message.lower() for term in ['model', 'database', 'field', 'table', 'schema'])):
            logger.info(f"Letting AI access all {len(model_files)} model files to determine relevance")
            file_list = "\n".join(f"- {path}" for path in model_files.keys())
            
            prompt_stage1 = MODEL_PROMPT_STAGE1.format(
                refined_request=refinement_result.get('refined_request', last_user_message),
                file_list=file_list
            )
            
            model_result_stage1 = await make_ai_api_call(prompt_stage1)
            logger.info(f"Model stage 1 response:\n{model_result_stage1}")
            
            # Extract selected files
            try:
                json_data = json.loads(model_result_stage1)
                if isinstance(json_data, dict) and 'selected_files' in json_data:
                    model_files_to_change = json_data['selected_files']
            except json.JSONDecodeError:
                match = re.search(r'"selected_files"\s*:\s*\[(.*?)\]', model_result_stage1, re.DOTALL)
                if match:
                    files_str = match.group(1)
                    model_files_to_change = [f.strip().strip('"\'') for f in files_str.split(',')]
            
            # Validate file selection to ensure we're only modifying actually needed files
            validated_files, rejected_files = await validate_file_selection(
                model_files_to_change, 
                refinement_result.get('refined_request', last_user_message),
                file_type="model"
            )
            
            if rejected_files:
                logger.info(f"Removed {len(rejected_files)} unnecessary model files: {rejected_files}")
                
            model_files_to_change = validated_files
            
            # Find valid matches in the context files
            valid_model_files = []
            for selected in model_files_to_change:
                if selected in model_files:
                    valid_model_files.append(selected)
                else:
                    # Try to find a match by filename without path
                    selected_basename = selected.split('/')[-1]
                    for current in model_files.keys():
                        if selected_basename in current:
                            valid_model_files.append(current)
                            break
            
            # Process each model file individually
            for file_path in valid_model_files:
                if file_path in model_files:
                    logger.info(f"Processing model file: {file_path}")
                    content = model_files[file_path]
                    
                    file_prompt = f"""
You are a Django model expert. Modify this model file to implement the following request:
{refinement_result.get('refined_request', last_user_message)}

Here is the current content of the file:
```{file_path}
{content}
```

Return ONLY the complete modified content of the file. Do not include any explanations, JSON formatting, or markdown code blocks.
Just return the raw Python code that should replace the file content.
"""
                    try:
                        model_content = await make_ai_api_call(file_prompt, max_tokens=4096)
                        clean_content = re.sub(r'```.*?\n|```', '', model_content)
                        
                        # Validate and potentially fix the generated code
                        is_valid, issues, validated_content = await validate_code_with_ai(file_path, clean_content)
                        
                        if not is_valid:
                            logger.warning(f"AI validation found issues with model file {file_path}: {issues}")
                            # If the AI couldn't fix it or didn't provide fixed content, try again
                            if validated_content == clean_content:
                                # Try once more with a more targeted prompt
                                repair_prompt = f"""
You are a Django model expert. The following Python model has issues that need to be fixed:
{issues}

Here is the model code with issues:
```{file_path}
{clean_content}
```

Please provide a corrected version of this model. Return ONLY the fixed Python code 
with no explanations, JSON formatting, or markdown code blocks.
"""
                                try:
                                    repaired_content = await make_ai_api_call(repair_prompt, max_tokens=4096)
                                    clean_content = re.sub(r'```.*?\n|```', '', repaired_content)
                                    
                                    # Validate the repaired content
                                    basic_valid, basic_issues = basic_code_syntax_check(file_path, clean_content)
                                    if not basic_valid:
                                        logger.warning(f"Repair attempt still has issues: {basic_issues}")
                                    else:
                                        logger.info(f"Successfully repaired model {file_path}")
                                except Exception as repair_err:
                                    logger.error(f"Error repairing model {file_path}: {str(repair_err)}")
                            else:
                                # Use the AI-fixed content
                                clean_content = validated_content
                                logger.info(f"Using AI-fixed content for model {file_path}")
                        
                        combined_changes["files"][file_path] = clean_content
                    except Exception as e:
                        logger.error(f"Error processing model file {file_path}: {str(e)}")

        # Process static files - particularly important for graph/chart requests
        static_files_to_change = []
        if static_files and ('static' in refinement_result.get('file_types', {}) or any(term in last_user_message.lower() for term in ['css', 'javascript', 'js', 'graph', 'chart', 'analytics', 'visual'])):
            logger.info(f"Letting AI access all {len(static_files)} static files to determine relevance")
            file_list = "\n".join(f"- {path}" for path in static_files.keys())
            
            prompt_stage1 = STATIC_PROMPT_STAGE1.format(
                refined_request=refinement_result.get('refined_request', last_user_message),
                file_list=file_list
            )
            
            static_result_stage1 = await make_ai_api_call(prompt_stage1)
            logger.info(f"Static stage 1 response:\n{static_result_stage1}")
            
            # Extract selected files
            try:
                json_data = json.loads(static_result_stage1)
                if isinstance(json_data, dict) and 'selected_files' in json_data:
                    static_files_to_change = json_data['selected_files']
            except json.JSONDecodeError:
                match = re.search(r'"selected_files"\s*:\s*\[(.*?)\]', static_result_stage1, re.DOTALL)
                if match:
                    files_str = match.group(1)
                    static_files_to_change = [f.strip().strip('"\'') for f in files_str.split(',')]
            
            # Process each static file individually
            for file_path in static_files_to_change:
                if file_path in static_files:
                    logger.info(f"Processing static file: {file_path}")
                    content = static_files[file_path]
                    
                    file_prompt = f"""
You are a Django static file expert. Modify this file to implement the following request:
{refinement_result.get('refined_request', last_user_message)}

Here is the current content of the file:
```{file_path}
{content}
```

Return ONLY the complete modified content of the file. Do not include any explanations, JSON formatting, or markdown code blocks.
Just return the raw code that should replace the file content.
"""
                    try:
                        static_content = await make_ai_api_call(file_prompt, max_tokens=4096)
                        clean_content = re.sub(r'```.*?\n|```', '', static_content)
                        
                        # Validate and potentially fix the generated code
                        is_valid, issues, validated_content = await validate_code_with_ai(file_path, clean_content)
                        
                        if not is_valid:
                            logger.warning(f"AI validation found issues with static file {file_path}: {issues}")
                            # If the AI couldn't fix it or didn't provide fixed content, try again
                            if validated_content == clean_content:
                                # Try once more with a more targeted prompt
                                repair_prompt = f"""
You are a web development expert. The following {file_path.split('.')[-1]} code has issues that need to be fixed:
{issues}

Here is the code with issues:
```{file_path}
{clean_content}
```

Please provide a corrected version. Return ONLY the fixed code 
with no explanations, JSON formatting, or markdown code blocks.
"""
                                try:
                                    repaired_content = await make_ai_api_call(repair_prompt, max_tokens=4096)
                                    clean_content = re.sub(r'```.*?\n|```', '', repaired_content)
                                    
                                    # Validate the repaired content
                                    basic_valid, basic_issues = basic_code_syntax_check(file_path, clean_content)
                                    if not basic_valid:
                                        logger.warning(f"Repair attempt still has issues: {basic_issues}")
                                    else:
                                        logger.info(f"Successfully repaired static file {file_path}")
                                except Exception as repair_err:
                                    logger.error(f"Error repairing static file {file_path}: {str(repair_err)}")
                            else:
                                # Use the AI-fixed content
                                clean_content = validated_content
                                logger.info(f"Using AI-fixed content for static file {file_path}")
                        
                        combined_changes["files"][file_path] = clean_content
                    except Exception as e:
                        logger.error(f"Error processing static file {file_path}: {str(e)}")
                
        # If no changes were identified but this seems like a code change request,
        # fall back to creating a new file if we can determine the type
        if not combined_changes["files"] and is_likely_code_change:
            logger.info("No existing files were modified, attempting to create a new file")
            
            # Try to determine file type from the request
            file_type = None
            file_path = None
            
            if any(term in last_user_message.lower() for term in ['html', 'template', 'page', 'view']):
                file_type = 'template'
                # Extract potential name from request
                match = re.search(r'(page|template|view) (for|called|named) [\'"]?([a-zA-Z0-9_]+)[\'"]?', last_user_message.lower())
                name = match.group(3) if match else 'new_page'
                file_path = f"templates/{name}.html"
                
            elif any(term in last_user_message.lower() for term in ['javascript', 'js', 'chart', 'graph']):
                file_type = 'static'
                match = re.search(r'(script|chart|graph) (for|called|named) [\'"]?([a-zA-Z0-9_]+)[\'"]?', last_user_message.lower())
                name = match.group(3) if match else 'analytics'
                file_path = f"static/js/{name}.js"
                
            if file_type and file_path:
                logger.info(f"Creating new {file_type} file: {file_path}")
                
                file_prompt = f"""
You are a Django {file_type} expert. Create a new {file_type} file to implement the following request:
{refinement_result.get('refined_request', last_user_message)}

Return ONLY the complete content of the new file. Do not include any explanations, JSON formatting, or markdown code blocks.
Just return the raw code for the new file.
"""
                try:
                    new_content = await make_ai_api_call(file_prompt, max_tokens=4096)
                    clean_content = re.sub(r'```.*?\n|```', '', new_content)
                    
                    # Validate and potentially fix the generated code
                    is_valid, issues, validated_content = await validate_code_with_ai(file_path, clean_content)
                    
                    if not is_valid:
                        logger.warning(f"AI validation found issues with new file {file_path}: {issues}")
                        # If the AI couldn't fix it or didn't provide fixed content, try again
                        if validated_content == clean_content:
                            # Try once more with a more targeted prompt
                            repair_prompt = f"""
You are a Django {file_type} expert. The following code for a new file has issues that need to be fixed:
{issues}

Here is the code with issues:
```{file_path}
{clean_content}
```

Please provide a corrected version. Return ONLY the fixed code 
with no explanations, JSON formatting, or markdown code blocks.
"""
                            try:
                                repaired_content = await make_ai_api_call(repair_prompt, max_tokens=4096)
                                clean_content = re.sub(r'```.*?\n|```', '', repaired_content)
                                
                                # Validate the repaired content
                                basic_valid, basic_issues = basic_code_syntax_check(file_path, clean_content)
                                if not basic_valid:
                                    logger.warning(f"Repair attempt still has issues: {basic_issues}")
                                else:
                                    logger.info(f"Successfully repaired new file {file_path}")
                            except Exception as repair_err:
                                logger.error(f"Error repairing new file {file_path}: {str(repair_err)}")
                        else:
                            # Use the AI-fixed content
                            clean_content = validated_content
                            logger.info(f"Using AI-fixed content for new file {file_path}")
                    
                    combined_changes["files"][file_path] = clean_content
                except Exception as e:
                    logger.error(f"Error creating new {file_type} file: {str(e)}")
                
        # Extract app_name from response or file paths
        app_name = None
        for file_path in combined_changes.get('files', {}).keys():
            parts = file_path.split('/')
            for part in parts:
                if part in ['posts', 'users', 'accounts', 'comments', 'main', 'blog', 'api']:
                    app_name = part
                    break
            if app_name:
                break
                
        # Ensure app_name is always populated with a default value if not found
        if not app_name:
            app_name = "main"
            
        combined_changes['app_name'] = app_name
        combined_changes['description'] = refinement_result.get('refined_request', last_user_message)
        
        # Always ensure we have at least one file change, even if we need to make a best guess
        if not combined_changes["files"]:
            logger.warning("No files were identified for change - creating a fallback template change")
            fallback_file = "templates/fallback_response.html"
            fallback_content = (
                '{% extends "base.html" %}\n\n'
                '{% block content %}\n'
                '<div class="container mt-4">\n'
                f'    <h1>Response to: {last_user_message}</h1>\n'
                '    <div class="card">\n'
                '        <div class="card-body">\n'
                '            <p>This is a generated response to your request.</p>\n'
                '            <p>Please provide more specific details about what files you\'d like to modify.</p>\n'
                '        </div>\n'
                '    </div>\n'
                '</div>\n'
                '{% endblock %}'
            )
            combined_changes["files"][fallback_file] = fallback_content
            
        return combined_changes
        
    except Exception as e:
        logger.error(f"Error in call_ai_multi_file: {str(e)}")
        logger.error(traceback.format_exc())
        return {"files": {}, "error": str(e)}

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
    Extract JSON or code blocks from AI response with improved Django template handling
    """
    if not prompt_result:
        return None
        
    try:
        # First, handle any Django template tags to avoid JSON parsing issues
        # Replace Django template tags with placeholders before JSON parsing
        processed_text = preprocess_django_templates(prompt_result)
        
        # Extract JSON from the response
        if field_format == 'json':
            # If the text is already valid JSON, try to parse it directly first
            try:
                result = json.loads(processed_text)
                # Process files to restore Django template tags if they exist
                if isinstance(result, dict) and 'files' in result:
                    for file_path, content in result['files'].items():
                        if isinstance(content, str):
                            result['files'][file_path] = postprocess_django_templates(content)
                return result
            except json.JSONDecodeError:
                pass  # Continue with other extraction methods
            
            # Try to extract a JSON object from code blocks
            json_match = re.search(r'```(?:json)?\s*({[\s\S]*?})\s*```', processed_text)
            if json_match:
                json_str = json_match.group(1)
                # Parse the JSON and restore Django template tags
                try:
                    result = json.loads(json_str)
                    # Process files to restore Django template tags
                    if isinstance(result, dict) and 'files' in result:
                        for file_path, content in result['files'].items():
                            if isinstance(content, str):
                                result['files'][file_path] = postprocess_django_templates(content)
                    return result
                except json.JSONDecodeError:
                    pass  # Continue with other extraction methods
                
            # Try direct JSON parsing if no code blocks found
            # Look for JSON objects
            json_pattern = r'{[\s\S]*?}'
            matches = re.findall(json_pattern, processed_text)
            
            for match in matches:
                try:
                    result = json.loads(match)
                    if isinstance(result, dict):
                        if 'files' in result:
                            # Process files to restore Django template tags
                            for file_path, content in result['files'].items():
                                if isinstance(content, str):
                                    result['files'][file_path] = postprocess_django_templates(content)
                        return result
                except json.JSONDecodeError:
                    continue
                
            # Last resort: try to find a pattern like "files": { ... } or "selected_files": [ ... ]
            files_match = re.search(r'"(?:files|selected_files)"\s*[:=]\s*[\[{][\s\S]*?[\]}]', processed_text)
            if files_match:
                files_str = '{' + files_match.group(0) + '}'
                try:
                    result = json.loads(files_str)
                    # Process files to restore Django template tags
                    if isinstance(result, dict) and 'files' in result:
                        for file_path, content in result['files'].items():
                            if isinstance(content, str):
                                result['files'][file_path] = postprocess_django_templates(content)
                    return result
                except:
                    pass
        
        # Handle code blocks
        elif field_format == 'code_block':
            # Extract content from code blocks
            code_match = re.search(r'```(?:.*?)\n([\s\S]*?)```', processed_text)
            if code_match:
                return postprocess_django_templates(code_match.group(1))
                
        # If all structured parsing fails, return the raw content
        return postprocess_django_templates(prompt_result)
        
    except Exception as e:
        logger.error(f"Error parsing AI output: {str(e)}")
        logger.error(traceback.format_exc())
        return None

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

async def generate_template_changes(refined_request: str, current_files: dict) -> dict:
    """Generate template-specific changes using a two-stage approach"""
    if DEBUG_TEMPLATE:
        logger.info(f"Generating template changes for: {refined_request}")
        logger.info(f"Current template files: {list(current_files.keys())}")
    
    # STAGE 1: Only send filenames and directories to select relevant files
    file_list = "\n".join(f"- {k}" for k in current_files.keys())
    
    prompt_stage1 = TEMPLATE_PROMPT_STAGE1.format(
        refined_request=refined_request,
        file_list=file_list
    )
    
    if DEBUG_TEMPLATE:
        logger.info(f"Template stage 1 prompt:\n{prompt_stage1}")
    
    try:
        result_stage1 = await make_ai_api_call(prompt_stage1)
        
        if DEBUG_TEMPLATE:
            logger.info(f"Template stage 1 response:\n{result_stage1}")
        
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
            
            # STAGE 2: Send content of the selected files for detailed analysis
            selected_files_content = ""
            for file_path in selected_files:
                if file_path in current_files:
                    content = current_files[file_path]
                    selected_files_content += f"```{file_path}\n{content}\n```\n\n"
                else:
                    logger.warning(f"Selected file {file_path} not found in current_files")
            
            prompt_stage2 = TEMPLATE_PROMPT_STAGE2.format(
                refined_request=refined_request,
                selected_files_content=selected_files_content
            )
            
            if DEBUG_TEMPLATE:
                logger.info(f"Template stage 2 prompt:\n{prompt_stage2}")
            
            result_stage2 = await make_ai_api_call(prompt_stage2, max_tokens=4096)
            
            if DEBUG_TEMPLATE:
                logger.info(f"Template stage 2 response:\n{result_stage2}")
            
            # Parse stage 2 response
            changes = parse_ai_output(result_stage2)
            
            # Process Django template tags
            if isinstance(changes, dict) and "files" in changes:
                for path, content in changes["files"].items():
                    if path.endswith(".html"):
                        changes["files"][path] = postprocess_django_template(content)
            
            return changes
        except Exception as e:
            logger.error(f"Failed to parse template changes: {str(e)}")
            logger.error(traceback.format_exc())
            return {"files": {}}
    except Exception as e:
        if DEBUG_TEMPLATE:
            logger.error(f"Failed to generate template changes: {str(e)}")
        return {"files": {}}

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

async def call_ai_multi_file(conversation, last_user_message, context_files):
    """
    Enhanced AI function to process multiple files, identifying which ones need changes and modifying them
            return False, [f"JavaScript syntax error: {str(e)}"]
    
    # For other file types, we don't have specific checks
    return True, []

async def validate_file_selection(file_paths, request_description, file_type=""):
    """
    Use AI to validate if the selected files are actually needed for the requested changes
    Returns a tuple of (validated_files, rejected_files)
    """
    if not file_paths:
        return [], []
        
    file_list = "\n".join([f"- {path}" for path in file_paths])
    
    prompt = f"""
You are a Django development expert. For the following change request, determine which files 
from the selected list actually need to be modified. Some files may have been incorrectly selected.

Change request: {request_description}

Selected {file_type} files:
{file_list}

Return a JSON object in this format:
{{
    "needed_files": ["file1", "file2", ...],
    "unnecessary_files": ["file3", "file4", ...],
    "explanation": "Brief explanation of your reasoning"
}}

IMPORTANT: Only include files in needed_files if they are DIRECTLY relevant to implementing the requested change.
"""
    
    try:
        result = await make_ai_api_call(prompt)
        
        try:
            validation = json.loads(result)
            needed = validation.get('needed_files', [])
            unnecessary = validation.get('unnecessary_files', [])
            explanation = validation.get('explanation', 'No explanation provided')
            
            # Log the reasoning
            logger.info(f"File selection validation: {explanation}")
            
            # If no files were classified as needed, it's likely an error
            if not needed and file_paths:
                logger.warning("No files classified as needed - using all selected files")
                return file_paths, []
                
            return needed, unnecessary
            
        except json.JSONDecodeError:
            # Try to extract using regex
            needed_match = re.search(r'"needed_files"\s*:\s*\[(.*?)\]', result, re.DOTALL)
            needed = []
            if needed_match:
                files_str = needed_match.group(1)
                needed = [f.strip().strip('"\'').strip() for f in files_str.split(',')]
                
            # If regex failed or no needed files found, return all files
            if not needed:
                return file_paths, []
                
            # Find unnecessary files by subtracting needed files from all files
            unnecessary = [f for f in file_paths if f not in needed]
            return needed, unnecessary
            
    except Exception as e:
        logger.error(f"Error validating file selection: {str(e)}")
        return file_paths, []  # On error, return all files

async def validate_code_with_ai(file_path: str, content: str) -> tuple:
    """
    Use AI to validate generated code changes and identify issues
    Returns (is_valid, issues, fixed_content)
    """
    file_type = file_path.split('.')[-1] if '.' in file_path else 'unknown'
    
    validation_prompt = f"""
You are a code quality validator. Analyze the following {file_type} code for syntax errors,
logical issues, and implementation problems. Return a JSON object with your analysis:

```{file_path}
{content}
```

Return a JSON object with this structure:
{{
    "is_valid": true/false,
    "issues": ["issue 1", "issue 2", ...],
    "fixed_content": "corrected code if there are issues, or empty string if no issues"
}}

Important guidelines:
1. Check for syntax errors
2. Verify imports are correct
3. Check for logical errors
4. Ensure code matches the file type
5. Fixed code should preserve the original intent while being syntactically correct
6. For Python files, check for proper indentation and PEP8 compliance
7. For HTML/templates, check for properly balanced tags
8. For JavaScript, check for proper function definitions and variable usage
"""

    try:
        result = await make_ai_api_call(validation_prompt, max_tokens=4096)
        
        # Parse the JSON response
        try:
            validation_result = json.loads(result)
            is_valid = validation_result.get('is_valid', False)
            issues = validation_result.get('issues', [])
            fixed_content = validation_result.get('fixed_content', '')
            
            # If the AI provided fixed content but marked it as valid (inconsistent),
            # still use the fixed content as it might be better
            if is_valid and fixed_content and fixed_content != content:
                logger.info(f"AI marked {file_path} as valid but still provided fixes")
                
            return is_valid, issues, fixed_content if fixed_content else content
            
        except json.JSONDecodeError:
            # Handle case where AI didn't return valid JSON
            logger.error(f"AI validation didn't return valid JSON for {file_path}")
            
            # Extract any issues it found using regex
            issues_match = re.search(r'"issues"\s*:\s*\[(.*?)\]', result, re.DOTALL)
            issues = []
            if issues_match:
                issues_str = issues_match.group(1)
                issues = [i.strip().strip('"\'') for i in issues_str.split(',')]
            
            # Extract fixed content if available
            content_match = re.search(r'"fixed_content"\s*:\s*"(.*?)"', result, re.DOTALL)
            fixed_content = content_match.group(1) if content_match else ''
            
            return False, issues, fixed_content if fixed_content else content
            
    except Exception as e:
        logger.error(f"Error validating code with AI for {file_path}: {str(e)}")
        return False, [f"Validation error: {str(e)}"], content

def basic_code_syntax_check(file_path: str, content: str) -> tuple:
    """
    Perform basic syntax validation on code without AI
    Returns (is_valid, issues)
    """
    issues = []
    
    if not content.strip():
        return False, ["Empty file content"]
    
    if file_path.endswith('.py'):
        try:
            # Check Python syntax
            ast.parse(content)
            
            # Check for common issues
            if 'import' not in content and not file_path.endswith('__init__.py'):
                issues.append("No imports found - might be missing dependencies")
                
            # Check indentation consistency
            lines = content.split('\n')
            indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
            if indents and max(indents) % 4 != 0:
                issues.append("Inconsistent indentation (not multiple of 4 spaces)")
                
            return len(issues) == 0, issues
        except SyntaxError as e:
            return False, [f"Python syntax error: {str(e)}"]
            
    elif file_path.endswith('.html'):
        # Basic HTML/template validation
        if content.count('{%') != content.count('%}'):
            issues.append("Mismatched template tags")
            
        if content.count('{{') != content.count('}}'):
            issues.append("Mismatched variable tags")
            
        # Check for common HTML issues
        for tag in ['div', 'span', 'p', 'a', 'table', 'tr', 'td', 'form']:
            if content.count(f'<{tag}') != content.count(f'</{tag}'):
                issues.append(f"Mismatched {tag} tags")
                
        return len(issues) == 0, issues
        
    elif file_path.endswith('.js'):
        try:
            # Basic JS validation - check for syntax errors
            try:
                import esprima
                esprima.parseScript(content)
            except ImportError:
                # If esprima is not available, try basic validation
                ast.parse(content)
            return True, []
        except Exception as e:
            return False, [f"JavaScript syntax error: {str(e)}"]
    
    # For other file types, we don't have specific checks
    return True, []