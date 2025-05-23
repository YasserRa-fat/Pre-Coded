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
from .json_validator import JSONValidator
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
from .ai_api_client import make_ai_api_call
TOGETHER_API_KEY = os.getenv("TOGETHER_AI_API_KEY")
MISTRAL_MODEL    = "mistralai/Mixtral-8x7B-Instruct-v0.1"
API_URL          = "https://api.together.xyz/inference"
# Cache timeouts
CACHE_TIMEOUT = 60 * 5  # 5 minutes
CHAT_CACHE_TIMEOUT = 60 * 30  # 30 minutes

# Shorter prompts for faster responses
SYSTEM_PROMPT = r"""You are a Django AI assistant. Analyze the request and generate necessary file changes for the project stored in the database.
Your task is to:
1. Identify all files that need to be modified or created based on the user's request
2. Generate complete, working code changes for each file
3. Return a JSON object with all changes

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "files": {
        "path/to/file1": "complete file content with changes",
        "path/to/file2": "complete file content with changes"
    },
    "description": "Brief description of changes made",
    "dependencies": {
        "python": ["package1", "package2"],
        "js": ["package1", "package2"]
    }
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. DO NOT use backticks (`) for code blocks - use proper JSON string escaping
3. DO NOT use comments in the code - include them as part of the string content
4. ALL file paths must match the database structure exactly
5. Template files should be just the filename (e.g. "feed.html" not "templates/feed.html")
6. Static files must include full path (e.g. "static/js/script.js")

Project: {project_name}
App: {app_name}
Available Files: {file_list}
Request: {user_message}

Remember: Return ONLY the JSON object, no other text."""

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

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "refined_request": "Clear description of what needs to be done",
    "file_types": {
        "template": ["Description of template changes needed"],
        "view": ["Description of view changes needed"],
        "model": ["Description of model changes needed"],
        "static": ["Description of static file changes needed"],
        "url": ["Description of URL changes needed"]
    }
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. DO NOT use backticks (`) or any other code block markers
3. ALL descriptions must be clear and specific
4. If a file type needs no changes, include an empty array
5. The refined_request must be a single clear sentence

Request: {user_message}
Project: {project_name}
App: {app_name}

Remember: Return ONLY the JSON object, no other text."""

TEMPLATE_PROMPT_STAGE1 = r"""You are a Django template expert. Select template files that need to be modified based on this request.

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "selected_files": ["file1.html", "file2.html"]
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. Template files must be filenames only, no paths
3. Files must exist in the available files list
4. Return empty array if no files need changes
5. DO NOT include 'templates/' prefix

Request: {refined_request}
Available template files:
{file_list}

Remember: Return ONLY the JSON object, no other text."""

TEMPLATE_PROMPT_STAGE2 = r"""You are a Django template expert. Generate template file changes based on this request.

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "files": {
        "file1.html": "complete template content",
        "file2.html": "complete template content"
    }
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. Use proper JSON string escaping for all content
3. Include complete file content, not just changes
4. Use EXACTLY the same filenames selected in stage 1
5. DO NOT use backticks (`) or any other code block markers
6. Template content must be valid Django template syntax

Request: {refined_request}
Selected files with their content:
{selected_files_content}

Remember: Return ONLY the JSON object, no other text."""

VIEW_PROMPT_STAGE1 = r"""You are a Django view expert. Select view files that need to be modified based on this request.

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "selected_files": ["views/path/to/file1.py", "views/path/to/file2.py"]
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. View files must include full path from views/
3. Files must exist in the available files list
4. Return empty array if no files need changes

Request: {refined_request}
Available view files:
{file_list}

Remember: Return ONLY the JSON object, no other text."""

VIEW_PROMPT_STAGE2 = r"""You are a Django view expert. Generate view file changes based on this request.

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "files": {
        "views/path/to/file1.py": "complete view content",
        "views/path/to/file2.py": "complete view content"
    }
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. Use proper JSON string escaping for all content
3. Include complete file content with all imports
4. Use EXACTLY the same paths selected in stage 1
5. DO NOT use backticks (`) or any other code block markers
6. View content must be valid Python syntax

Request: {refined_request}
Selected files with their content:
{selected_files_content}

Remember: Return ONLY the JSON object, no other text."""

MODEL_PROMPT_STAGE1 = r"""You are a Django model expert. Select model files that need to be modified based on this request.

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "selected_files": ["models/path/to/file1.py", "models/path/to/file2.py"]
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. Model files must include full path from models/
3. Files must exist in the available files list
4. Return empty array if no files need changes

Request: {refined_request}
Available model files:
{file_list}

Remember: Return ONLY the JSON object, no other text."""

MODEL_PROMPT_STAGE2 = r"""You are a Django model expert. Generate model file changes based on this request.

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "files": {
        "models/path/to/file1.py": "complete model content",
        "models/path/to/file2.py": "complete model content"
    }
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. Use proper JSON string escaping for all content
3. Include complete file content with all imports
4. Use EXACTLY the same paths selected in stage 1
5. DO NOT use backticks (`) or any other code block markers
6. Model content must be valid Python syntax

Request: {refined_request}
Selected files with their content:
{selected_files_content}

Remember: Return ONLY the JSON object, no other text."""

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

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "selected_files": ["static/path/to/file1.js", "static/path/to/file2.css"]
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. Static files must include full path from static/
3. Files must exist in the available files list
4. Return empty array if no files need changes

Request: {refined_request}
Available static files:
{file_list}

Remember: Return ONLY the JSON object, no other text."""

STATIC_PROMPT_STAGE2 = r"""You are a Django static files expert. Generate static file changes based on this request.

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{
    "files": {
        "static/path/to/file1.js": "complete JS content",
        "static/path/to/file2.css": "complete CSS content"
    }
}

FORMATTING RULES:
1. DO NOT include any explanatory text before or after the JSON
2. Use proper JSON string escaping for all content
3. Include complete file content, not just changes
4. Use EXACTLY the same paths selected in stage 1
5. DO NOT use backticks (`) or any other code block markers
6. Content must be valid for the file type (JS/CSS)

Request: {refined_request}
Selected files with their content:
{selected_files_content}

Remember: Return ONLY the JSON object, no other text."""

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
    try:
        cache_key = f"ai_response_{conversation.id}_{hash(last_user_message)}"
        cached_response = cache.get(cache_key)
        if cached_response:
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
        prompt += "\nCRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH NO ADDITIONAL TEXT.\n"
        prompt += "\nFORMATTING RULES:\n"
        prompt += "1. NO comments in the JSON\n"
        prompt += "2. NO backticks or code blocks\n"
        prompt += "3. Proper JSON string escaping\n"
        prompt += "4. Template files use just filename\n"
        prompt += "5. Static files use full path\n"
        prompt += "6. NO explanatory text before or after JSON\n"

        # Only include relevant files based on the message
        relevant_files = {}
        logger.debug("Filtering relevant files based on message keywords")
        for path, content in normalized_context.items():
            if any(keyword in last_user_message.lower() for keyword in path.lower().split('/')):
                relevant_files[path] = get_cached_file_content(path, content)
                logger.debug(f"Including relevant file: {path}")

        for path, content in relevant_files.items():
            prompt += f"\nFile: {path}\n{content}\n"
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

        # Validate and clean the response using the new JSONValidator
        try:
            logger.debug("Validating and cleaning AI response")
            is_valid, cleaned_response, error_msg = JSONValidator.validate_and_parse(result)
            
            if is_valid and cleaned_response:
                cache.set(cache_key, json.dumps(cleaned_response), CACHE_TIMEOUT)
                return json.dumps(cleaned_response)
            else:
                logger.warning(f"JSON validation failed: {error_msg}")
                # Try fallback regex extraction
                extracted = JSONValidator.extract_json_with_regex(result)
                if extracted:
                    logger.info("Successfully extracted JSON data using regex fallback")
                    cache.set(cache_key, json.dumps(extracted), CACHE_TIMEOUT)
                    return json.dumps(extracted)
        except Exception as e:
            logger.error(f"Error cleaning AI response: {str(e)}")

        return json.dumps({
            "files": {},
            "description": "Failed to parse AI response",
            "dependencies": {"python": [], "js": []}
        })
    except Exception as e:
        logger.error(f"Error in call_ai: {str(e)}")
        return json.dumps({
            "files": {},
            "description": f"Error: {str(e)}",
            "dependencies": {"python": [], "js": []}
        })

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

async def make_initial_ai_call(conversation, text, files_data):
    """Make initial AI call with project context and file data"""
    try:
        logger.debug(f"Input - conversation: {conversation.id}, text length: {len(text)}")
        logger.debug(f"Files data keys: {list(files_data.keys())}")
        
        # Extract the actual file structure for the AI
        project_context = files_data.get('project_context', {})
        project_id = files_data.get('project_id')
        
        # Get list of existing view files
        existing_views = []
        if 'views' in project_context:
            existing_views = [view['path'] for view in project_context['views']]
        logger.debug(f"Existing view files: {existing_views}")
        
        # Check if this is an analytics-related request
        is_analytics_feature = any(keyword in text.lower() for keyword in 
                                   ['analytics', 'graph', 'chart', 'visualize', 'dashboard', 'statistics'])
        
        # Log project_context structure for debugging
        if project_context:
            logger.debug(f"Project context contains {len(project_context)} entries")
            sample_keys = list(project_context.keys())[:5]
            logger.debug(f"Sample keys: {sample_keys}")
        else:
            logger.warning("Project context is empty!")
        
        # Add analytics-specific instructions if needed
        analytics_instructions = ""
        if is_analytics_feature:
            analytics_instructions = """
ANALYTICS FEATURE INSTRUCTIONS:
1. ONLY use EXISTING view files - DO NOT create new ones
2. For graphs/charts, include:
   - JavaScript files with proper chart library integration
   - Use existing view files to add data fetching functions
   - Complete template files that render the analytics UI
3. Structure view functions to properly query data for the time period specified
4. Ensure all imports are included based on the analytics functionality needed
5. When showing analytics "for the past 10 days", ensure data is properly filtered
6. Include proper data aggregation using Django's ORM functions
"""

        # Create the prompt with properly escaped JSON example
        prompt = f"""
You are a Django AI assistant. Analyze the request and generate necessary file changes.
Project Context:
- Project ID: {project_id}
- App Name: {files_data.get('app_name')}
- User Request: {text}
- Existing View Files: {', '.join(existing_views)}

CRITICAL INSTRUCTIONS:
1. ONLY use EXISTING view files - NEVER create new ones
2. Available view files are: {', '.join(existing_views)}
3. For analytics, add functions to EXISTING view files only
4. For EACH file, return the COMPLETE file content, not just the changes
5. When handling graphs or charts, include JS files for rendering AND use existing view files for data
6. EVERY file in the response must be a COMPLETE file, not partial content
7. DO NOT create new view files - modify existing ones only
{analytics_instructions}

CRITICAL: YOU MUST RETURN ONLY A VALID JSON OBJECT WITH THIS EXACT STRUCTURE:
{{
    "files": {{
        "filename.html": "complete file content with your changes",
        "existing_app/views.py": "complete file content with your changes",
        "static/js/filename.js": "complete file content"
    }},
    "description": "Brief description of changes",
    "dependencies": {{
        "python": ["package1"],
        "js": ["package2"]
    }}
}}

FORMATTING RULES:
1. NO comments in the JSON
2. NO backticks or code blocks
3. Proper JSON string escaping
4. Template files use just filename
5. Static files use full path
6. NO explanatory text before or after JSON
7. ONLY use view files from this list: {', '.join(existing_views)}
"""
        logger.debug("Generated prompt for initial AI call")
        
        # Make the API call
        try:
            response = await make_ai_api_call(
                prompt=prompt,
                max_tokens=8192,
                temperature=0.2
            )
            logger.info("Successfully received AI response")
            logger.debug(f"Response length: {len(response) if response else 0}")
            
            # Validate response to ensure no new view files are created
            try:
                response_data = json.loads(response)
                if 'files' in response_data:
                    # Filter out any non-existing view files
                    files_to_remove = []
                    for file_path in response_data['files'].keys():
                        if file_path.endswith('views.py') and file_path not in existing_views:
                            logger.warning(f"Removing non-existing view file from response: {file_path}")
                            files_to_remove.append(file_path)
                    
                    # Remove non-existing view files
                    for file_path in files_to_remove:
                        del response_data['files'][file_path]
                    
                    # Re-serialize the filtered response
                    response = json.dumps(response_data)
            except json.JSONDecodeError:
                logger.error("Failed to validate response JSON")
            
            return response
            
        except Exception as api_error:
            logger.error(f"API call failed: {str(api_error)}")
            return None
            
    except Exception as e:
        logger.error(f"Error in make_initial_ai_call: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def remove_js_comments(text: str) -> str:
    """Remove JavaScript comments from JSON response."""
    # Remove single line comments that are not inside strings
    text = re.sub(r'(?<!["\'`])//.*$', '', text, flags=re.MULTILINE)
    return text

def fix_backticks(text: str) -> str:
    """Replace backtick code blocks with proper JSON strings."""
    return re.sub(r'`(.*?)`', lambda m: json.dumps(m.group(1)), text)

def normalize_file_paths(data: dict) -> dict:
    """Normalize file paths in the response data."""
    if not isinstance(data, dict) or 'files' not in data:
        return data
        
    normalized = {}
    for path, content in data['files'].items():
        if path.endswith('.html'):
            normalized[os.path.basename(path)] = content
        else:
            normalized[path] = content
    data['files'] = normalized
    return data

def escape_json_string(text: str) -> str:
    """Properly escape newlines and control characters in JSON strings."""
    # Replace literal newlines and control characters with their escaped versions
    replacements = {
        '\n': '\\n',
        '\t': '\\t',
        '\r': '\\r',
        '\b': '\\b',
        '\f': '\\f'
    }
    for char, escape in replacements.items():
        text = text.replace(char, escape)
    return text

def parse_descriptive_format(text: str) -> dict:
    """
    Parse AI response when it's in descriptive text format instead of JSON.
    Returns a properly formatted JSON structure.
    """
    logger.debug("=== Parsing Descriptive Format ===")
    logger.debug(f"Input text first 200 chars: {text[:200]}")
    
    files = {}
    dependencies = {"python": [], "js": []}
    
    try:
        # Extract file sections using numbered list format (1. filename...)
        file_sections = list(re.finditer(r'(?m)^\d+\.\s+([^\n(]+)(?:\s*\(type:\s*([^,\n]+)(?:,\s*app:\s*([^)]+))?\))?\s*(?:-[^\n]+(?:\n|$))+', text))
        logger.debug(f"Found {len(file_sections)} file sections")
        
        for match in file_sections:
            section_text = match.group(0)
            logger.debug(f"\nProcessing section:\n{section_text}")
            
            file_path = match.group(1).strip()
            file_type = match.group(2).strip() if match.group(2) else None
            app_name = match.group(3).strip() if match.group(3) else None
            
            logger.debug(f"Extracted - Path: {file_path}, Type: {file_type}, App: {app_name}")
            
            # For templates, ensure we only use the filename
            if file_type == 'templates' or file_path.endswith('.html'):
                file_path = os.path.basename(file_path)
                # logger.debug(f"Normalized template path to: {file_path}")
            
            # Extract content hints from bullet points
            content_hints = re.findall(r'(?m)^\s*-\s*(.+)$', section_text)
            logger.debug(f"Content hints: {content_hints}")
            
            # Generate appropriate placeholder based on file type
            if file_path.endswith('.html'):
                content = "{% extends 'base.html' %}\n\n{% block content %}\n  <!-- Generated from AI description -->\n"
                for hint in content_hints:
                    content += f"  <!-- {hint.strip()} -->\n"
                content += "{% endblock %}"
            elif file_path.endswith('.js'):
                content = "// Generated from AI description\n"
                for hint in content_hints:
                    content += f"// TODO: {hint.strip()}\n"
            else:
                content = "# Generated from AI description\n"
                for hint in content_hints:
                    content += f"# TODO: {hint.strip()}\n"
            
            files[file_path] = content
            logger.debug(f"Generated content for {file_path}")
            
            # Extract dependencies from description
            if any('chart' in hint.lower() for hint in content_hints):
                if 'Chart.js' in section_text:
                    dependencies['js'].append('chart.js')
                    logger.debug("Added Chart.js dependency")
                elif 'D3.js' in section_text:
                    dependencies['js'].append('d3')
                    logger.debug("Added D3.js dependency")
        
        logger.debug(f"=== Parse Result ===")
        logger.debug(f"Files: {list(files.keys())}")
        logger.debug(f"Dependencies: {dependencies}")
        
        return {
            "files": files,
            "description": "Generated from descriptive format",
            "dependencies": dependencies
        }
        
    except Exception as e:
        logger.error(f"Error parsing descriptive format: {str(e)}")
        logger.error(traceback.format_exc())
        return {
            "files": {},
            "description": "Failed to parse descriptive format",
            "dependencies": {"python": [], "js": []}
        }

def extract_json_from_hybrid(text: str) -> Optional[str]:
    """
    Extract JSON object from a response that mixes descriptive text and JSON.
    Only handles the specific case of JSON embedded in descriptive text.
    """
    logger.debug("=== Extracting JSON from hybrid response ===")
    
    # Find the last occurrence of a JSON-like structure
    json_matches = list(re.finditer(r'({[\s\S]*})\s*$', text))
    if not json_matches:
        logger.debug("No JSON structure found in hybrid response")
        return None
        
    potential_json = json_matches[-1].group(1)
    logger.debug(f"Found potential JSON structure: {potential_json[:200]}...")
    
    try:
        # Validate it's proper JSON
        json.loads(potential_json)
        logger.debug("Successfully validated JSON structure")
        return potential_json
    except json.JSONDecodeError as e:
        logger.debug(f"Invalid JSON in hybrid response: {str(e)}")
        return None

def handle_backtick_code_blocks(text: str) -> str:
    """
    Replace backtick-quoted code blocks with properly escaped JSON strings.
    Specifically handles the case of backticks in AI responses.
    """
    logger.debug("=== Handling backtick code blocks ===")
    logger.debug(f"Input text first 200 chars: {text[:200]}")
    
    try:
        # Replace backtick-quoted blocks with properly escaped JSON strings
        processed_text = re.sub(
            r'`([^`]*)`',
            lambda m: json.dumps(m.group(1)),
            text
        )
        logger.debug(f"Processed text first 200 chars: {processed_text[:200]}")
        return processed_text
    except Exception as e:
        logger.error(f"Error handling backtick code blocks: {str(e)}")
        return text

def sanitize_json_response(text: str) -> str:
    """
    Sanitize JSON response by handling newlines and placeholders.
    Preserves all content exactly as is, only fixes JSON formatting issues.
    """
    logger.debug("=== Sanitizing JSON Response ===")
    logger.debug(f"Original response first 200 chars:\n{text[:200]}")
    
    try:
        # Remove any leading/trailing whitespace and newlines
        text = text.strip()
        
        # Remove any response prefixes and extra newlines
        prefixes_to_remove = ['RESPONSE:', 'JSON:', 'OUTPUT:', 'RESULT:']
        for prefix in prefixes_to_remove:
            if text.upper().startswith(prefix):
                text = text[len(prefix):].strip()
        
        # Find the actual JSON content
        json_start = text.find('{')
        json_end = text.rfind('}') + 1  # Include the closing brace
        if json_start >= 0 and json_end > json_start:
            text = text[json_start:json_end]
            
            # Remove any trailing content after the JSON
            if text.count('{') == text.count('}'):
                text = text.strip()
            else:
                # If braces don't match, try to find the proper ending
                stack = []
                for i, char in enumerate(text):
                    if char == '{':
                        stack.append(i)
                    elif char == '}':
                        if stack:
                            stack.pop()
                            if not stack:  # All braces matched
                                text = text[:i+1]
                                break
        
        # Handle ellipsis and placeholder content
        text = re.sub(r'"\s*\.\.\.\s*"', '""', text)  # "..." -> ""
        text = re.sub(r'"\s*\.{3}.*?\.{3}\s*"', '""', text)  # "...content..." -> ""
        text = re.sub(r'"<.*?>"', '""', text)  # "<placeholder>" -> ""
        
        # Temporarily replace Django template tags to prevent escaping
        template_tags = []
        def save_template_tag(match):
            tag = match.group(0)
            template_tags.append(tag)
            return f"__TEMPLATE_TAG_{len(template_tags)-1}__"
            
        # Save template tags
        text = re.sub(r'{%[^}]+%}|{{[^}]+}}', save_template_tag, text)
        
        # Fix string escaping
        text = text.replace('\\', '\\\\')  # Escape backslashes first
        text = text.replace('\n', '\\n')
        text = text.replace('\t', '\\t')
        text = text.replace('\r', '\\r')
        text = text.replace('"', '\\"')
        
        # Restore template tags
        for i, tag in enumerate(template_tags):
            text = text.replace(f'"__TEMPLATE_TAG_{i}__"', json.dumps(tag))
        
        # Try to parse the JSON
        try:
            data = json.loads(text)
            # Remove any empty or placeholder file contents
            if isinstance(data, dict) and 'files' in data:
                data['files'] = {
                    k: v for k, v in data['files'].items() 
                    if v and not v.isspace() and v != '...' and not v.startswith('...')
                }
            return json.dumps(data, indent=2)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {str(e)}")
            logger.debug(f"Error location - line {e.lineno}, column {e.colno}")
            logger.debug(f"Error context:\n{text[max(0, e.pos-100):e.pos+100]}")
            return None
            
    except Exception as e:
        logger.error(f"Error in sanitize_json_response: {str(e)}")
        return None

VALIDATE_JSON_PROMPT = r"""You are a JSON validator and cleaner. Your task is to fix and validate the provided JSON.

CRITICAL RULES - YOU MUST FOLLOW THESE EXACTLY:
1. Return ONLY a valid JSON object with NO additional text or explanation
2. Preserve the exact data structure and field names
3. Do not modify or assume any file paths - keep them exactly as provided
4. For template files (ending in .html):
   - Keep the exact path structure (app/templates/file.html or templates/file.html)
   - Do not modify template paths or assume app names
5. Remove any:
   - Comments (both // and /* */)
   - Markdown formatting (```, etc)
   - Explanatory text
   - Non-JSON content
6. Ensure proper:
   - String escaping
   - JSON formatting
   - Quote consistency (use double quotes)
   - Template tag preservation (keep {% %} and {{ }} intact)

Input JSON to clean:
{input_json}

REMEMBER: Return ONLY the fixed JSON object, nothing else. No explanation, no comments."""

async def validate_json_with_ai(json_text: str) -> Optional[str]:
    """
    Use AI to validate and clean JSON response.
    Only handles JSON validation, no path modifications.
    """
    logger.debug("=== Validating JSON with AI ===")
    logger.debug(f"Input JSON first 200 chars:\n{json_text[:200]}")
    
    try:
        # First try to parse as is
        try:
            json.loads(json_text)
            logger.debug("JSON already valid")
            return json_text
        except json.JSONDecodeError as e:
            logger.debug(f"Initial JSON parse failed: {str(e)}")
            logger.debug(f"Error location - line {e.lineno}, column {e.colno}")
            logger.debug(f"Error context:\n{json_text[max(0, e.pos-100):e.pos+100]}")
        
        # Call AI for validation
        prompt = VALIDATE_JSON_PROMPT.format(input_json=json_text)
        validated = await async_call_ai_api(prompt=prompt, max_tokens=4096)
        
        if not validated:
            logger.error("AI validation returned empty response")
            return None
            
        logger.debug(f"AI validated response first 200 chars:\n{validated[:200]}")
        
        # Verify the AI response is valid JSON
        try:
            parsed = json.loads(validated)
            # Extra validation for template paths
            if isinstance(parsed, dict) and 'files' in parsed:
                for path in parsed['files'].keys():
                    if path.endswith('.html'):
                        # Ensure template paths weren't modified
                        original_parts = path.split('/')
                        if 'templates' in original_parts:
                            logger.debug(f"Template path preserved: {path}")
                        else:
                            logger.warning(f"Template path may have been modified: {path}")
            logger.debug("AI validation successful")
            return validated
        except json.JSONDecodeError as e:
            logger.error(f"AI validation failed to produce valid JSON: {str(e)}")
            return None
            
    except Exception as e:
        logger.error(f"Error in validate_json_with_ai: {str(e)}")
        return None

async def sanitize_ai_response(response_text: str, detect_analytics=False, request_text=None) -> str:
    """
    Sanitize AI response to ensure valid JSON for parsing.
    Preserves all paths and template tags exactly as provided.
    """
    if not response_text:
        logger.error("Empty response received in sanitize_ai_response")
        return json.dumps({
            "files": {},
            "description": "Empty response",
            "dependencies": {"python": [], "js": []}
        })

    logger.debug(f"Input first 200 chars: {response_text[:200]}")
    
    try:
        # Use the improved JSONValidator
        is_valid, data, error = await JSONValidator.validate_and_parse(response_text)
        
        if is_valid and data:
            # Add any missing required fields
            if 'description' not in data:
                data['description'] = "Generated from AI response"
            if 'dependencies' not in data:
                data['dependencies'] = {"python": [], "js": []}
            if 'files' not in data:
                data['files'] = {}
            
            # Handle analytics-specific requirements
            if detect_analytics:
                # Ensure Chart.js dependency
                if 'js' not in data['dependencies']:
                    data['dependencies']['js'] = []
                if 'chart.js' not in data['dependencies']['js']:
                    data['dependencies']['js'].append('chart.js')
                
                # Validate analytics-related files
                for file_path, content in list(data['files'].items()):
                    if file_path.endswith('.js') and 'chart' in file_path.lower():
                        if not JSONValidator._is_placeholder_content(content) and not any(pattern in content for pattern in [
                            'new Chart(',
                            'Chart.defaults',
                            'Chart.register',
                            'createChart'
                        ]):
                            logger.warning(f"Analytics JS file {file_path} missing Chart.js initialization")
                    elif file_path.endswith('.html'):
                        if not JSONValidator._is_placeholder_content(content) and not any(pattern in content for pattern in [
                            '<canvas',
                            'chart-container',
                            'data-chart'
                        ]):
                            logger.warning(f"Analytics template {file_path} missing chart elements")
            
            # Clean up file paths while preserving placeholders
            cleaned_files = {}
            for file_path, content in data['files'].items():
                # Skip empty content but preserve placeholders
                if not content or (content.isspace() and not JSONValidator._is_placeholder_content(content)):
                    continue
                    
                # Normalize path
                norm_path = normalize_path(file_path)
                
                # For templates, ensure we use just the filename
                if norm_path.endswith('.html'):
                    norm_path = os.path.basename(norm_path)
                
                cleaned_files[norm_path] = content
            
            data['files'] = cleaned_files
            
            return json.dumps(data, indent=2)
        else:
            logger.error(f"Failed to validate JSON: {error}")
            return json.dumps({
                "files": {},
                "description": f"Failed to parse response: {error}",
                "dependencies": {"python": [], "js": []}
            })
            
    except Exception as e:
        logger.error(f"Error in sanitize_ai_response: {str(e)}")
        return json.dumps({
            "files": {},
            "description": f"Error processing response: {str(e)}",
            "dependencies": {"python": [], "js": []}
        })

async def call_ai_multi_file(conversation, text, files_data):
    """Call AI service for multiple file changes with validation and refinement."""
    try:
        logger.info("Starting multi-file AI call")
        logger.debug(f"Files data keys: {list(files_data.keys())}")
        
        # Add debugging for project context
        project_context = files_data.get('project_context', {})
        logger.info(f"Project ID: {files_data.get('project_id')}")
        logger.info(f"App name: {files_data.get('app_name')}")
        
        # Debug project context structure
        logger.debug("=== Project Context Structure ===")
        for key, value in project_context.items():
            if isinstance(value, list):
                logger.debug(f"{key}: {len(value)} items")
                if value:
                    logger.debug(f"First item sample: {value[0]}")
            else:
                logger.debug(f"{key}: {type(value)}")
        
        response = {
            'files': {},
            'metadata': {
                'files_processed': 0,
                'files_skipped': 0,
                'validation_attempts': 0
            },
            'selected_files': []
        }

        # Check if this is an analytics-related request
        is_analytics_feature = any(keyword in text.lower() for keyword in ['analytics', 'graph', 'chart', 'visualize', 'dashboard'])
        if is_analytics_feature:
            logger.info("Detected analytics feature request in call_ai_multi_file")

        # Make initial AI call
        initial_response = await make_initial_ai_call(conversation, text, files_data)
        if not initial_response:
            logger.error("Initial AI call failed")
            return None
            
        # Debug the initial response
        logger.debug(f"Raw initial response: {initial_response[:500]}...")
        
        # Sanitize the response before parsing
        sanitized_response = await sanitize_ai_response(initial_response, detect_analytics=is_analytics_feature, request_text=text)
        logger.debug(f"Sanitized AI response: {sanitized_response[:500]}...")
        
        # Parse the response
        try:
            changes = json.loads(sanitized_response)
            if not isinstance(changes, dict):
                logger.error(f"Invalid response format - not a dict: {type(changes)}")
                return None
                
            files = changes.get('files', {})
            if not isinstance(files, dict):
                logger.error(f"Invalid files format - not a dict: {type(files)}")
                return None
                
            logger.info(f"Files to process: {list(files.keys())}")
            
            # Get existing files from project context
            existing_files = set()
            if 'views' in project_context:
                logger.debug("=== Views in Project Context ===")
                for view in project_context['views']:
                    view_path = view.get('path', '')
                    logger.debug(f"View path from context: {view_path}")
                    existing_files.add(view_path)
            
            if 'templates' in project_context:
                existing_files.update(t['name'] for t in project_context['templates'])
            
            # Debug existing files
            logger.debug("=== All Existing Files ===")
            for file_path in existing_files:
                logger.debug(f"Existing file: {file_path}")
            
            # Process each file
            for file_path, content in files.items():
                logger.info(f"Processing file: {file_path}")
                
                # Debug file path normalization
                logger.debug(f"=== File Path Normalization for {file_path} ===")
                logger.debug(f"Original path: {file_path}")
                
                # Normalize path but preserve app prefix
                norm_path = normalize_template_path(file_path)
                logger.debug(f"After template normalization: {norm_path}")
                
                # Additional normalization for views
                if file_path.endswith('views.py'):
                    logger.debug("Processing view file path")
                    # Try different path variations
                    variations = [
                        file_path,
                        f"{file_path.split('/')[0]}/views.py",  # app/views.py format
                        norm_path
                    ]
                    logger.debug(f"Trying view path variations: {variations}")
                    
                    # Check each variation
                    for var in variations:
                        if var in existing_files:
                            norm_path = var
                            logger.debug(f"Found matching view path: {norm_path}")
                            break
                
                # Check if file exists or is a new static/media file
                is_new_static = file_path.startswith(('static/', 'media/'))
                file_exists = norm_path in existing_files or file_path in existing_files
                
                logger.debug("=== File Existence Check ===")
                logger.debug(f"Normalized path: {norm_path}")
                logger.debug(f"Original path: {file_path}")
                logger.debug(f"Is static/media: {is_new_static}")
                logger.debug(f"Exists in project: {file_exists}")
                logger.debug(f"Exists as norm_path: {norm_path in existing_files}")
                logger.debug(f"Exists as original: {file_path in existing_files}")
                
                if not file_exists and not is_new_static:
                    logger.warning(f"Selected file {file_path} not found in project")
                    response['metadata']['files_skipped'] += 1
                    continue
                
                # Process the file
                response['files'][file_path] = content
                response['metadata']['files_processed'] += 1
                response['selected_files'].append(file_path)
                logger.info(f"{'Adding new' if is_new_static else 'Processing existing'} file: {file_path}")
                
            logger.info(f"Processed {response['metadata']['files_processed']} files, skipped {response['metadata']['files_skipped']}")
            logger.info(f"Selected files: {response['selected_files']}")
            
            if not response['files']:
                logger.error("No relevant existing files found")
                return None
                
            return response

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            logger.error(f"Sanitized response causing error: {sanitized_response}")
            return None
            
    except Exception as e:
        logger.error(f"Error in call_ai_multi_file: {str(e)}")
        logger.error(traceback.format_exc())
        return None

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
    """Extract JSON using regex as fallback"""
    try:
        # Find the outermost JSON object
        start = text.find('{')
        if start == -1:
            return None
            
        count = 1
        pos = start + 1
        
        while count > 0 and pos < len(text):
            if text[pos] == '{':
                count += 1
            elif text[pos] == '}':
                count -= 1
            pos += 1
            
        if count == 0:
            json_str = text[start:pos]
            # Escape JavaScript content before parsing
            if '"static/js/' in json_str:
                parts = json_str.split('"static/js/')
                for i in range(1, len(parts)):
                    js_part = parts[i]
                    end_idx = js_part.find('",')
                    if end_idx != -1:
                        js_content = js_part[:end_idx]
                        parts[i] = escape_js_content(js_content) + js_part[end_idx:]
                json_str = '"static/js/'.join(parts)
            return json.loads(json_str)
        return None
    except Exception:
        return None

def escape_js_content(content: str) -> str:
    """Properly escape JavaScript content for JSON"""
    return json.dumps(content)[1:-1]  # Remove the outer quotes but keep the escaping

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

def normalize_template_path(path: str) -> str:
    """
    Normalize template path by handling templates/ prefix appropriately,
    but preserving app prefixes (like posts/ or users/)
    
    For Django templates stored in the database:
    - If format is 'app/templates/file.html', extract file.html (DB stores just the filename)
    - If format is 'templates/file.html', extract file.html
    - If format is already 'file.html', leave as is
    """
    try:
        logger.debug(f"Normalizing path: {path}")
        
        if not path:
            logger.warning("Empty path provided to normalize_template_path")
            return path
            
        # Extract just the filename for templates
        # If app/templates/file.html -> extract file.html (matches DB format)
        if '/' in path and '.html' in path.lower():
            filename = os.path.basename(path)
            logger.debug(f"Extracted template filename: {filename}")
            return filename
            
        # For non-template files, preserve the path structure
        logger.debug(f"Path unchanged: {path}")
        return path
        
    except Exception as e:
        logger.error(f"Error in normalize_template_path: {str(e)}")
        logger.error(traceback.format_exc())
        return path

def validate_and_map_files(selected_files, project_files):
    """
    Validate and map selected files to actual project files.
    Returns a list of valid file paths that exist in the project.
    """
    try:
        logger.info(f"Validating {len(selected_files)} selected files against {len(project_files)} project files")
        logger.debug(f"Selected files: {selected_files}")
        logger.debug(f"Project files: {list(project_files.keys())}")
        valid_files = []
        
        for selected_path in selected_files:
            logger.debug(f"\nProcessing selected path: {selected_path}")
            
            # Normalize the selected path
            norm_path = normalize_template_path(selected_path)
            # logger.debug(f"Normalized path: {norm_path}")
            
            # Try direct match first
            if norm_path in project_files:
                valid_files.append(norm_path)
                logger.info(f"Direct match found for {selected_path} -> {norm_path}")
                continue
            else:
                logger.debug(f"No direct match found for normalized path: {norm_path}")
                logger.debug(f"Available paths: {[p for p in project_files.keys() if p.endswith(os.path.basename(norm_path))]}")
            
            # Try with templates/ prefix
            if selected_path in project_files:
                valid_files.append(selected_path)
                logger.info(f"Prefix match found for {selected_path}")
                continue
            else:
                logger.debug(f"No prefix match found for: {selected_path}")
            
            # Try fuzzy matching
            matching_paths = [
                path for path in project_files.keys()
                if os.path.basename(path) == os.path.basename(norm_path)
            ]
            if matching_paths:
                valid_files.append(matching_paths[0])
                logger.info(f"Fuzzy match found: {selected_path} -> {matching_paths[0]}")
            else:
                logger.debug(f"No fuzzy matches found. Basename comparison:")
                logger.debug(f"Looking for: {os.path.basename(norm_path)}")
                logger.debug(f"Available basenames: {[os.path.basename(p) for p in project_files.keys()][:5]}...")
                logger.warning(f"No matching file found for {selected_path} (normalized: {norm_path})")
                
        logger.info(f"Validation complete. Found {len(valid_files)} valid files: {valid_files}")
        return valid_files
        
    except Exception as e:
        logger.error(f"Error in validate_and_map_files: {str(e)}")
        logger.error(traceback.format_exc())
        return []

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