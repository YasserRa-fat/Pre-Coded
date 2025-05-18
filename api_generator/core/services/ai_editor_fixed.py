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

async def make_ai_api_call(prompt: str, max_tokens: int = 2048, temperature: float = 0.2) -> str:
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
                "temperature": temperature,
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

# Add debug constants
DEBUG_REFINE = True
DEBUG_TEMPLATE = True
DEBUG_VIEW = True
DEBUG_STATIC = True
DEBUG_MULTI = True

# Add the fixed functions below

async def validate_file_selection(file_paths, request_description, file_type=""):
    """Use AI to validate if the selected files are actually needed for the requested changes.
    Returns a tuple of (validated_files, rejected_files)."""
    if not file_paths:
        return [], []
        
    file_list = "\n".join([f"- {path}" for path in file_paths])
    
    prompt = (
        "You are a Django development expert. For the following change request, determine which files "
        "from the selected list actually need to be modified. Some files may have been incorrectly selected.\n\n"
        f"Change request: {request_description}\n\n"
        f"Selected {file_type} files:\n"
        f"{file_list}\n\n"
        "Return a JSON object in this format:\n"
        "{\n"
        '    "needed_files": ["file1", "file2", ...],\n'
        '    "unnecessary_files": ["file3", "file4", ...],\n'
        '    "explanation": "Brief explanation of your reasoning"\n'
        "}\n\n"
        "IMPORTANT: Only include files in needed_files if they are DIRECTLY relevant to implementing the requested change."
    )
    
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
    """Use AI to validate generated code changes and identify issues.
    Returns (is_valid, issues, fixed_content)."""
    file_type = file_path.split('.')[-1] if '.' in file_path else 'unknown'
    
    validation_prompt = (
        "You are a code quality validator. Analyze the following code for syntax errors, "
        f"logical issues, and implementation problems. File type: {file_type}\n\n"
        "```\n"
        f"{content}\n"
        "```\n\n"
        "Return a JSON object with this structure:\n"
        "{\n"
        '    "is_valid": true/false,\n'
        '    "issues": ["issue 1", "issue 2", ...],\n'
        '    "fixed_content": "corrected code if there are issues, or empty string if no issues"\n'
        "}\n\n"
        "Important guidelines:\n"
        "1. Check for syntax errors\n"
        "2. Verify imports are correct\n"
        "3. Check for logical errors\n"
        "4. Ensure code matches the file type\n"
        "5. Fixed code should preserve the original intent while being syntactically correct\n"
        "6. For Python files, check for proper indentation and PEP8 compliance\n"
        "7. For HTML/templates, check for properly balanced tags\n"
        "8. For JavaScript, check for proper function definitions and variable usage"
    )

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
    """Perform basic syntax validation on code without AI. Returns (is_valid, issues)."""
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