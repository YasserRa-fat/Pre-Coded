import json
import difflib
import logging
import tiktoken
from django.test import Client
import re
from urllib.parse import urljoin, quote as encodeURIComponent, parse_qs
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from django.urls import reverse
from django.core.exceptions import ImproperlyConfigured
import ast
import requests
from create_api.models import (
    AIConversation,
    AIMessage,
    AIChangeRequest,
    TemplateFile,
    StaticFile,
    ModelFile,
    ViewFile,
    FormFile,
    MediaFile,
    ProjectFile,
    AppFile,
    URLFile,
    SettingsFile
)
from core.services.file_indexer import FileIndexer
from core.services.classifier import classify_request
from core.services.ai_editor import (
    call_ai,
    parse_ai_output,
    call_chat_ai,
    run_apply,
    call_ai_multi_file,
)
from .ai_generator import (
    optimize_and_generate_code,
    validate_generated_code,
    get_prompt_template
)
from create_api.views import setup_preview_project
from .models import App 
import os
from pathlib import Path
from django.conf import settings
import time
from datetime import datetime, timedelta
from .template_utils import TemplateValidator, TemplateGenerator
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, wraps
import threading
from asyncio import Semaphore, sleep
from channels.db import database_sync_to_async
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError
import traceback
import sys
import hashlib
from typing import Dict, List, Any, Optional, Union, Set
from django.utils.timezone import timezone
from django.db.models import Count
import uuid

# Enhanced logging setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Add file handler for detailed logging
file_handler = logging.FileHandler('websocket_debug.log')
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Add console handler for immediate feedback during development
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Add a specialized handler for preview data
preview_handler = logging.FileHandler('preview_debug.log')
preview_handler.setLevel(logging.DEBUG)
preview_handler.setFormatter(formatter)
logger.addHandler(preview_handler)

logger.info("WebSocket consumer module loaded with enhanced logging")

# API Configuration
MISTRAL_MODEL = "mistralai/Mixtral-8x7B-Instruct-v0.1"
API_URL = "https://api.together.xyz/inference"
TOGETHER_API_KEY = os.getenv("TOGETHER_AI_API_KEY")

# Rate limiting configuration
API_SEMAPHORE = Semaphore(2)  # Max 2 concurrent API calls
RETRY_ATTEMPTS = 3
RETRY_DELAY = 1.0  # seconds

# Load configurations from Django settings
API_CONFIG = getattr(settings, 'AI_API_CONFIG', {
    'model': 'mistralai/Mixtral-8x7B-Instruct-v0.1',
    'max_tokens': 256,
    'temperature': 0.2,
    'batch_size': 2,
    'retry_attempts': 3,
    'retry_delay': 1.0,
    'cache_timeout': 3600,
})

# Dynamic request patterns loaded from settings
REQUEST_PATTERNS = getattr(settings, 'AI_REQUEST_PATTERNS', {
    'analytics': {
        'keywords': ['analytics', 'graph', 'chart', 'visualization', 'stats', 'metrics'],
        'components': ['view', 'template', 'static'],
        'files': {
            'view': 'views.py',
            'template': '.html',
            'static': ['.js', '.css']
        }
    },
    'crud': {
        'keywords': ['create', 'update', 'delete', 'edit', 'remove'],
        'components': ['view', 'model'],
        'files': {
            'view': 'views.py',
            'model': 'models.py'
        }
    },
    'ui': {
        'keywords': ['page', 'show', 'display', 'ui', 'layout', 'style'],
        'components': ['template', 'static'],
        'files': {
            'template': '.html',
            'static': ['.css', '.js']
        }
    }
})

def with_retry(func):
    """Decorator to handle retries with exponential backoff (async only)"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        for attempt in range(RETRY_ATTEMPTS):
            try:
                async with API_SEMAPHORE:
                    return await func(*args, **kwargs)
            except Exception as e:
                if "429" in str(e) and attempt < RETRY_ATTEMPTS - 1:
                    delay = RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"Rate limited, retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                raise
    return wrapper

@with_retry
async def call_ai_api_async(prompt, max_tokens=256, temperature=0.2):
    """Rate-limited API call with retries (async)"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "model": MISTRAL_MODEL,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
        async with session.post(API_URL, json=payload, headers=headers) as response:
            if response.status != 200:
                logger.error(f"API request failed with status {response.status}")
                response.raise_for_status()
            result = await response.json()
            return result.get("choices", [{}])[0].get("text", "").strip()

# Simplified rate limiting
class RateLimitTracker:
    def __init__(self):
        self.last_request = 0
        self.lock = threading.Lock()
        
    def can_make_request(self):
        with self.lock:
            now = time.time()
            if now - self.last_request >= 0.1:  # 100ms between requests
                self.last_request = now
                return True
            return False

rate_limiter = RateLimitTracker()

# Add caching for API responses
@lru_cache(maxsize=1000)
def cache_api_response(cache_key, response_text):
    """Cache API responses to avoid duplicate requests"""
    return response_text

def batch_generate_code(files_data, max_concurrent=2):
    """Simplified batch code generation"""
    results = {}
    
    # Process files sequentially for more predictable behavior
    for file_data in files_data:
        file_type = file_data['file_type']
        generator_map = {
            'template': generate_template_code,
            'model': generate_model_code,
            'view': generate_views_code,
            'form': generate_form_code,
            'url': generate_urls_code,
            'app': generate_app_code,
            'other': generate_static_code
        }
        
        generator_func = generator_map.get(file_type, generate_static_code)
        
        try:
            content = generator_func(
                file_data['file_path'],
                file_data['change_desc'],
                file_data['context'],
                file_data.get('original_content', '')
            )
            
            if content:
                results[file_data['file_path']] = content
                logger.info(f"Generated code for {file_data['file_path']}")
            
        except Exception as e:
            logger.error(f"Error generating code for {file_data['file_path']}: {str(e)}")
    
    return results

def extract_url_namespaces(template_content):
    pattern = r"{% url '([\w-]+)'(?:\s+[^%]+)?\s*%}"
    matches = re.findall(pattern, template_content)
    return set(matches)

def estimate_tokens(text):
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception as e:
        logger.error(f"Failed to estimate tokens: {e}")
        return len(text.split())

async def get_change_plan(project_id, app_name, user_text, context):
    """Simplified change plan generation"""
    prompt = f"""
Determine files to modify in Django project {project_id}, app {app_name}.
User Request: {user_text}

Existing Files:
{chr(10).join(f'- {path}' for path in context.keys())}

For each file that needs changes, specify:
- File: [path]
- Change: [exact changes needed]
"""
    plan_text = await call_ai_api_async(prompt, max_tokens=2048)
    if not plan_text:
        return {}
    
    changes = {}
    current_file = None
    current_change = None
    
    for line in plan_text.split('\n'):
        line = line.strip()
        if line.startswith('- File:'):
            if current_file and current_change:
                changes[current_file] = {'change': current_change}
            current_file = line.split(':', 1)[1].strip()
            current_change = None
        elif line.startswith('- Change:'):
            current_change = line.split(':', 1)[1].strip()
    
    if current_file and current_change:
        changes[current_file] = {'change': current_change}
    
    return changes

def determine_file_type(file_path):
    """
    Determine the file type based on the file path.
    Returns one of: 'template', 'model', 'view', 'form', 'app', 'other'
    """
    if file_path.endswith('.html'):
        return 'template'
    elif file_path.endswith('.py'):
        if 'models' in file_path:
            return 'model'
        elif 'views' in file_path:
            return 'view'
        elif 'forms' in file_path:
            return 'form'
        elif 'urls' in file_path or 'settings' in file_path:
            return 'app'
    elif file_path.endswith(('.css', '.js')):
        return 'other'
    return 'other'  # Default fallback

def clean_template_content(content):
    """Clean up template content by removing unwanted tags"""
    return TemplateValidator.clean_template(content)

def fix_template_syntax(content):
    """Fix common template syntax errors"""
    return TemplateValidator.fix_template_syntax(content)

async def generate_views_code(file_path, change_desc, context, original_content=""):
    """Generate view code dynamically based on request and context"""
    try:
        change = change_desc.get('change', '')
        request_type = change_desc.get('request_type', '')
        
        # Step 1: Analyze requirements
        analysis_prompt = f"""Analyze this view request and extract key requirements:
Request: {change}
Context: {json.dumps(context, indent=2)}

Return a JSON object with:
1. view_type: type of view needed (e.g., ListView, DetailView, etc.)
2. model_name: main model to use
3. required_fields: list of fields/data needed
4. data_operations: list of data operations needed
5. time_range: any time-based filtering needed
6. user_specific: whether data should be user-specific
7. aggregations: any data aggregation needed"""

        analysis_result = await call_ai_api_async(analysis_prompt, max_tokens=2048)
        requirements = json.loads(analysis_result)

        # Step 2: Generate view structure
        structure_prompt = f"""Create a Django view structure based on these requirements:
{json.dumps(requirements, indent=2)}

Include:
1. Class definition
2. Required mixins
3. Basic attributes
4. Method stubs

Return only the basic structure."""

        structure = await call_ai_api_async(structure_prompt, max_tokens=2048)

        # Step 3: Implement core logic
        logic_prompt = f"""Implement the core logic for this view structure:
{structure}

Requirements:
{json.dumps(requirements, indent=2)}

Focus on:
1. Data retrieval and filtering
2. Aggregations and calculations
3. Context preparation
4. Error handling
5. Performance optimization

Return the implementation."""

        implementation = await call_ai_api_async(logic_prompt, max_tokens=2048)

        # Step 4: Add template context
        context_prompt = f"""Add template context handling to this view:
{implementation}

Requirements:
1. Prepare all necessary data for the template
2. Format data for any JavaScript libraries needed
3. Add proper serialization
4. Include error states
5. Add any required metadata

Return the complete view code."""

        with_context = await call_ai_api_async(context_prompt, max_tokens=2048)

        # Step 5: Validate and optimize
        validation_prompt = f"""Validate and optimize this view code:
{with_context}

Check for:
1. Security issues
2. Performance bottlenecks
3. Django best practices
4. Error handling
5. Edge cases

Return the optimized code."""

        validated_code = await call_ai_api_async(validation_prompt, max_tokens=2048)

        # Step 6: Add imports and documentation
        final_prompt = f"""Finalize this view code:
{validated_code}

Add:
1. All necessary imports
2. Proper documentation
3. Type hints
4. Usage examples
5. Performance notes

Return the complete, production-ready view code."""

        final_code = await call_ai_api_async(final_prompt, max_tokens=2048)

        # Verify the generated code meets requirements
        verification_prompt = f"""Verify this view code meets all requirements:
Original request: {change}
Requirements: {json.dumps(requirements, indent=2)}

Code:
{final_code}

Return a JSON object with:
1. meets_requirements: boolean
2. missing_requirements: list of any missing requirements
3. suggested_fixes: list of any needed fixes"""

        verification_result = await call_ai_api_async(verification_prompt, max_tokens=2048)
        verification = json.loads(verification_result)

        if not verification.get('meets_requirements', False):
            # One more iteration to fix any issues
            fix_prompt = f"""Fix these issues in the view code:
{final_code}

Issues to fix:
{json.dumps(verification.get('missing_requirements', []))}

Suggested fixes:
{json.dumps(verification.get('suggested_fixes', []))}

Return the fixed code."""

            final_code = await call_ai_api_async(fix_prompt, max_tokens=2048)

        return final_code

    except Exception as e:
        logger.error(f"Error generating view code: {str(e)}")
        logger.error(traceback.format_exc())
        raise

async def generate_template_code(self, file_path, change_desc, context, original_content=""):
    """Generate template code with proper analytics integration"""
    if 'analytics' in change_desc['request_type'].lower():
        # For analytics requests, generate specialized template code
        analytics_prompt = f"""Generate template code for an analytics graph that:
1. Shows user interactions from the past {context.get('time_range', 10)} days
2. Uses Chart.js for visualization
3. Places the graph before the posts section
4. Only shows for authenticated users
5. Includes proper data loading and error handling

Change request: {change_desc['change']}
File: {file_path}

Return the complete template code with:
1. Required Chart.js integration
2. Data loading section
3. Graph container and configuration
4. Error handling and loading states"""

        template_code = await self._call_ai(analytics_prompt)
        return template_code
    else:
        # For non-analytics templates, use the standard generation
        return await self.generate_code_with_validation(file_path, change_desc, context, original_content)

async def generate_static_code(file_path, change_desc, context, original_content=""):
    """Generate static files (JS/CSS) for analytics"""
    if 'analytics' in change_desc['request_type'].lower():
        # For analytics requests, generate specialized JS/CSS code
        static_prompt = f"""Generate {'JavaScript' if file_path.endswith('.js') else 'CSS'} code that:
1. Handles analytics graph initialization
2. Manages data loading and updates
3. Configures Chart.js properly
4. Includes responsive design
5. Handles errors gracefully

Change request: {change_desc['change']}
File: {file_path}

Return the complete code with:
1. Proper initialization
2. Event handlers
3. AJAX calls
4. Error handling
5. Responsive styling"""

        static_code = await self._call_ai(static_prompt)
        return static_code
    else:
        # For non-analytics static files, use the standard generation
        return await self.generate_code_with_validation(file_path, change_desc, context, original_content)

def _analyze_code_patterns(self, content):
    """Analyze code patterns in existing files"""
    patterns = {
        'indentation': None,
        'naming_convention': None,
        'function_style': None,
        'comment_style': None
    }
    
    try:
        # Detect indentation
        lines = content.split('\n')
        for line in lines:
            if line.startswith(' '):
                patterns['indentation'] = len(line) - len(line.lstrip(' '))
                break
            elif line.startswith('\t'):
                patterns['indentation'] = 'tab'
                break
        
        # Detect naming convention
        if 'function' in content:
            if 'function myFunction' in content or 'function MyFunction' in content:
                patterns['naming_convention'] = 'camelCase'
            elif 'function my_function' in content:
                patterns['naming_convention'] = 'snake_case'
        
        # Detect function style
        if 'async function' in content:
            patterns['function_style'] = 'async/await'
        elif '=>' in content:
            patterns['function_style'] = 'arrow'
        else:
            patterns['function_style'] = 'traditional'
        
        # Detect comment style
        if '/**' in content:
            patterns['comment_style'] = 'jsdoc'
        elif '//' in content:
            patterns['comment_style'] = 'inline'
        elif '/*' in content:
            patterns['comment_style'] = 'block'
            
    except Exception as e:
        logger.error(f"Error analyzing code patterns: {str(e)}")
        
    return patterns

def log_operation(operation_name):
    """Decorator for logging function calls and timing"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = datetime.now()
            logger.debug(f"Starting {operation_name} at {start_time}")
            logger.debug(f"Args: {args}, Kwargs: {kwargs}")
            try:
                result = await func(*args, **kwargs)
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                logger.debug(f"Completed {operation_name} in {duration:.2f} seconds")
                return result
            except Exception as e:
                logger.error(f"Error in {operation_name}: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                raise
        return wrapper
    return decorator

class RequestClassifier:
    def __init__(self, context):
        self.context = dict(context)
        logger.debug(f"Initializing RequestClassifier with {len(self.context)} context items")

    def classify(self, text):
        """Classify request type and determine required files"""
        logger.info(f"Classifying request: {text}")
        cache_key = f"request_classification_{hash(text.lower())}"
        
        cached_result = cache.get(cache_key)
        if cached_result:
            logger.debug(f"Using cached classification for: {text}")
            return cached_result

        try:
            request_type = self._analyze_request_type(text)
            logger.debug(f"Analyzed request type: {request_type}")
            
            files = self._get_required_files(request_type, text)
            logger.debug(f"Required files: {files}")
            
            changes = self._create_changes(files, request_type, text)
            logger.debug(f"Created {len(changes)} change objects")

            result = {
                'type': request_type,
                'files': files,
                'changes': changes
            }
            
            logger.info(f"Classification complete - Type: {request_type}, Files: {len(files)}")
            cache.set(cache_key, result, API_CONFIG['cache_timeout'])
            return result
        except Exception as e:
            logger.error(f"Error during classification: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    def _analyze_request_type(self, text):
        """Analyze request text to determine type"""
        text_lower = text.lower()
        
        # Check for analytics request first
        analytics_keywords = ['analytics', 'graph', 'chart', 'visualization', 'stats']
        if any(keyword in text_lower for keyword in analytics_keywords):
            if 'feed' in text_lower or 'page' in text_lower:
                logger.info(f"Detected analytics request with keywords: {[k for k in analytics_keywords if k in text_lower]}")
                return 'analytics'
        
        # Define keyword patterns for other types
        patterns = {
            'template': ['template', 'page', 'html', 'view'],
            'model': ['model', 'database', 'table', 'field'],
            'view': ['view', 'endpoint', 'route', 'url'],
            'form': ['form', 'input', 'submit', 'field'],
            'url': ['url', 'route', 'path'],
            'static': ['static', 'css', 'javascript', 'js']
        }
        
        # Count keyword matches for each type
        matches = {}
        for req_type, keywords in patterns.items():
            matches[req_type] = []
            for keyword in keywords:
                if keyword in text_lower:
                    matches[req_type].append(keyword)
                    
        # Get type with most matches
        max_matches = 0
        detected_type = 'unknown'
        
        for req_type, matched_keywords in matches.items():
            if len(matched_keywords) > max_matches:
                max_matches = len(matched_keywords)
                detected_type = req_type
                
        return detected_type

    def _get_required_files(self, request_type, text):
        """Dynamically determine required files based on request"""
        files = []
        
        # For analytics requests, we only need the feed template and its associated JS
        if request_type == 'analytics':
            # Find the feed template
            feed_templates = [f for f in self.context.keys() if 'feed' in f.lower() and f.endswith('.html')]
            if feed_templates:
                files.extend(feed_templates)
            
            # Add Chart.js if needed
            if 'graph' in text.lower() or 'chart' in text.lower():
                chart_js = [f for f in self.context.keys() if 'chart' in f.lower() and f.endswith('.js')]
                if chart_js:
                    files.extend(chart_js)
            
            logger.info(f"Selected {len(files)} files for analytics request")
            return files
            
        # For other request types, use existing logic
        needs_template = any(word in text.lower() for word in ['page', 'view', 'display', 'show'])
        needs_data = any(word in text.lower() for word in ['data', 'model', 'database', 'store'])
        needs_styling = any(word in text.lower() for word in ['style', 'css', 'look', 'design'])
        needs_interaction = any(word in text.lower() for word in ['click', 'interact', 'dynamic', 'update'])
        
        # Find relevant files based on needs
        if needs_template:
            template_files = [f for f in self.context.keys() if f.endswith('.html')]
            files.extend(self._filter_relevant_files(template_files, text))
            
        if needs_data:
            view_files = [f for f in self.context.keys() if f.endswith('views.py')]
            model_files = [f for f in self.context.keys() if f.endswith('models.py')]
            files.extend(self._filter_relevant_files(view_files + model_files, text))
            
        if needs_styling:
            style_files = [f for f in self.context.keys() if f.endswith('.css')]
            files.extend(self._filter_relevant_files(style_files, text))
            
        if needs_interaction:
            js_files = [f for f in self.context.keys() if f.endswith('.js')]
            files.extend(self._filter_relevant_files(js_files, text))
            
        logger.info(f"Selected {len(files)} files based on request analysis")
        return files

    def _filter_relevant_files(self, files, text):
        """Filter files based on relevance to request"""
        relevant_files = []
        keywords = text.lower().split()
        
        for file in files:
            # Calculate relevance score based on keyword matches
            score = sum(1 for word in keywords if word in file.lower())
            if score > 0:
                relevant_files.append(file)
                
        return relevant_files

    def _create_changes(self, files, request_type, text):
        """Create change objects for each file"""
        changes = []
        
        if request_type == 'analytics':
            # For analytics, we only need to modify the feed template
            feed_template = next((f for f in files if 'feed' in f.lower() and f.endswith('.html')), None)
            if feed_template:
                changes.append({
                    'file': feed_template,
                    'type': 'template',
                    'content': text,
                    'change': text,
                    'request_type': request_type
                })
                logger.debug(f"Created change object for analytics in {feed_template}")
            return changes
        
        # For other request types, create change objects for each file
        for file_path in files:
            change = {
                'file': file_path,
                'type': self._determine_file_type(file_path),
                'content': text,
                'change': text,
                'request_type': request_type
            }
            changes.append(change)
            
        logger.debug(f"Created {len(changes)} change objects")
        return changes

    def _determine_file_type(self, file_path):
        """Dynamically determine file type based on path and content"""
        if file_path.endswith('.html'):
            return 'template'
        elif file_path.endswith('.py'):
            if 'views' in file_path:
                return 'view'
            elif 'models' in file_path:
                return 'model'
            elif 'forms' in file_path:
                return 'form'
            elif 'urls' in file_path:
                return 'url'
        elif file_path.endswith(('.js', '.css')):
            return 'static'
        return 'unknown'

class CodeGenerator:
    def __init__(self):
        """Initialize code generator with dynamic handlers"""
        self.handlers = {
            'view': self.generate_code_with_validation,
            'template': self.generate_code_with_validation,
            'model': self.generate_code_with_validation,
            'form': self.generate_code_with_validation,
            'url': self.generate_code_with_validation,
            'static': self.generate_code_with_validation,
            'default': self.generate_code_with_validation
        }
        self.pattern_cache = {}
        self.api_config = API_CONFIG
        self.semaphore = Semaphore(2)  # Limit concurrent API calls

    async def generate_code_with_validation(self, file_path, change_desc, context, original_content=""):
        """Generate code with validation and multiple AI requests if needed"""
        try:
            file_type = self._determine_file_type(file_path)
            handler = self.handlers.get(file_type, self.handlers['default'])

            # Step 1: Analyze requirements
            analysis_prompt = self._create_analysis_prompt(file_type, change_desc, context)
            analysis = await self._call_ai(analysis_prompt)

            # Step 2: Generate initial code
            code_prompt = self._create_code_prompt(file_type, change_desc, analysis, context)
            code = await self._call_ai(code_prompt)

            # Step 3: Validate and fix if needed
            issues = await self._validate_code(code, file_type)
            if issues:
                fix_prompt = self._create_fix_prompt(code, issues, file_type)
                code = await self._call_ai(fix_prompt)

            # Step 4: Add imports and dependencies
            imports_prompt = self._create_imports_prompt(code, file_type)
            final_code = await self._call_ai(imports_prompt)

            return final_code

        except Exception as e:
            logger.error(f"Error generating code for {file_path}: {str(e)}")
            return None

    def _create_analysis_prompt(self, file_type, change_desc, context):
        """Create prompt for analyzing requirements"""
        return f"""Analyze this {file_type} change request:
Change: {change_desc['change']}
Type: {change_desc['request_type']}
Context: {json.dumps(context, indent=2)}

Return a structured analysis of:
1. Required functionality
2. Dependencies needed
3. Integration points
4. Data requirements
5. UI/UX considerations"""

    def _create_code_prompt(self, file_type, change_desc, analysis, context):
        """Create prompt for generating initial code"""
        return f"""Generate {file_type} code based on:
Change: {change_desc['change']}
Analysis: {analysis}
Context: {json.dumps(context, indent=2)}

Requirements:
1. Follow best practices for {file_type}
2. Include error handling
3. Make code modular and reusable
4. Add clear comments
5. Ensure proper integration"""

    def _create_fix_prompt(self, code, issues, file_type):
        """Create prompt for fixing code issues"""
        return f"""Fix the following issues in this {file_type} code:
Code: {code}
Issues: {issues}

Requirements:
1. Maintain existing functionality
2. Fix all reported issues
3. Improve code quality
4. Ensure compatibility"""

    def _create_imports_prompt(self, code, file_type):
        """Create prompt for adding imports and dependencies"""
        return f"""Add necessary imports and dependencies to this {file_type} code:
{code}

Requirements:
1. Include all required imports
2. Add any missing dependencies
3. Remove unused imports
4. Organize imports properly"""

    async def _validate_code(self, code, file_type):
        """Validate generated code"""
        # Add validation logic based on file type
        return []

    async def _call_ai(self, prompt):
        """Make AI API call with retry and rate limiting"""
        async with self.semaphore:
            try:
                response = await call_ai_api_async(prompt)
                return response
            except Exception as e:
                logger.error(f"Error calling AI API: {str(e)}")
                return None

    def _determine_file_type(self, file_path):
        """Determine file type from path"""
        if file_path.endswith('.html'):
            return 'template'
        elif file_path.endswith('.py'):
            return 'view'
        elif file_path.endswith(('.js', '.css')):
            return 'static'
        return 'default'

    async def generate_default_code(self, file_path, change_desc, context, original_content=""):
        """Default code generation handler"""
        return await self.generate_code_with_validation(file_path, change_desc, context, original_content)

class AIChatConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for AI chat functionality.
    Handles real-time communication between client and server.
    """
    
    async def connect(self):
        """Handle WebSocket connection"""
        try:
            # Get user and project info from scope
            self.user = self.scope["user"]
            self.project_id = int(self.scope["url_route"]["kwargs"]["project_id"])
            self.conversation = None
            self.api_semaphore = Semaphore(2)
            self.code_generator = CodeGenerator()
            
            # Create unique channel group name for this project
            self.group_name = f"project_{self.project_id}"
            
            logger.info(f"WebSocket connection attempt - User: {self.user}, Project: {self.project_id}")

            if not self.user.is_authenticated:
                logger.error(f"Connection rejected - User not authenticated: {self.user}")
                await self.close(code=4003, reason="Authentication failed")
                return

            # Join project group
            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            
            # Accept the connection
            await self.accept()
            
            # Send connection confirmation
            await self.send_json({
                "type": "connection_established",
                "project_id": self.project_id,
                "user": self.user.username
            })
            
            logger.info(f"WebSocket connected successfully - User: {self.user}, Project: {self.project_id}, Channel: {self.channel_name}")
            
        except Exception as e:
            logger.error(f"Connection error: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            await self.close(code=1011, reason=f"Server error: {str(e)}")
            raise

    @sync_to_async
    def _get_project_context(self):
        """Get project context with all file contents"""
        context = {}
        
        # Load all file types
        for model in [TemplateFile, StaticFile, ModelFile, ViewFile, FormFile, 
                     ProjectFile, SettingsFile, URLFile, AppFile]:
            try:
                files = model.objects.filter(project_id=self.project_id)
                for file in files:
                    path = getattr(file, 'path', '')
                    if path:
                        context[path] = file.content or ""
            except Exception as e:
                logger.error(f"Error loading {model.__name__}: {str(e)}")
                continue

        logger.debug(f"Loaded project context with {len(context)} files")
        return context

    async def disconnect(self, code):
        """Handle WebSocket disconnection"""
        try:
            # Leave project group
            if hasattr(self, 'group_name'):
                await self.channel_layer.group_discard(
                    self.group_name,
                    self.channel_name
                )
            
            # Close any active conversation
            if self.conversation:
                await self._update_conversation_status('closed')
            
            reason = self.scope.get('close_reason', 'No reason provided')
            logger.info(
                f"WebSocket disconnected - User: {getattr(self, 'user', 'Unknown')}, "
                f"Project: {getattr(self, 'project_id', 'Unknown')}, "
                f"Code: {code}, Reason: {reason}, "
                f"Channel: {getattr(self, 'channel_name', 'Unknown')}"
            )
        except Exception as e:
            logger.error(f"Error during disconnect: {str(e)}")
            logger.error(traceback.format_exc())

    @database_sync_to_async
    def _update_conversation_status(self, status):
        """Update conversation status in database"""
        if self.conversation:
            try:
                self.conversation.status = status
                self.conversation.save()
                logger.debug(f"Updated conversation {self.conversation.id} status to {status}")
            except Exception as e:
                logger.error(f"Error updating conversation status: {str(e)}")

    async def receive_json(self, content):
        """Handle incoming WebSocket messages"""
        try:
            if not self.user.is_authenticated:
                logger.warning(f"Unauthenticated message received from {self.channel_name}")
                await self.close(code=4003)
                return
                
            logger.info(f"Received message: {content}")

            message_type = content.get("type")
            
            if message_type == "send_message":
                text = content.get("text", "").strip()
                if not text:
                    logger.warning("Empty message received")
                    await self._send_error("Empty message")
                    return

                # Process the initial request
                logger.debug("Starting message processing steps...")
                await self._process_message(text)

            elif message_type == "confirm_changes":
                # Handle change confirmation from frontend
                change_id = content.get("change_id")
                if not change_id:
                    await self._send_error("No change ID provided")
                    return

                await self._apply_confirmed_changes(change_id)

            else:
                logger.warning(f"Invalid message type: {message_type}")
                await self._send_error("Invalid message type")

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            await self._send_error(f"Failed to process request: {str(e)}")

    async def _send_error(self, message):
        """Send error message to client"""
        try:
            if not self.channel_name:
                logger.error("Cannot send error - no channel name")
                return
                
            await self.send_json({
                "type": "error",
                "message": str(message)
            })
            logger.error(f"Sent error to client: {message}")
        except Exception as e:
            logger.error(f"Failed to send error message: {str(e)}")
            logger.error(f"Original error was: {message}")

    @sync_to_async
    def _get_or_create_conversation(self):
        """Get or create AI conversation"""
        if not self.conversation or self.conversation.status == "closed":
            return AIConversation.objects.create(
                project_id=self.project_id,
                user=self.user,
                status="open",
                app_name="default_app"
            )
        return self.conversation

    @sync_to_async
    def _create_message(self, text):
        """Create AI message"""
        return AIMessage.objects.create(
            conversation=self.conversation,
            sender='user',
            text=text
        )

    @sync_to_async
    def _create_change_request(self, changes):
        """Create change request"""
        return AIChangeRequest.objects.create(
            conversation=self.conversation,
            project_id=self.project_id,
            file_type=changes['type'],
            file_path=changes['files'][0] if changes['files'] else '',
            app_name=self.conversation.app_name,
            status='pending',
            diff=json.dumps({}),
            files=[]
        )

    @log_operation("Change Application")
    async def _apply_changes(self, change):
        """Prepare changes and send diff for frontend confirmation"""
        try:
            logger.info(f"Starting to prepare changes for request {change.id}")
            
            # Get the change request
            change = await sync_to_async(AIChangeRequest.objects.get)(id=change.id)
            results = json.loads(change.diff)
            logger.debug(f"Change diff content: {results}")
            
            # Send diff modal to frontend for confirmation
            await self.send_json({
                "type": "show_diff_modal",
                "change_id": change.id,
                "files": change.files,
                "diff": results,
                "title": "Review Changes",
                "message": "Please review the following changes before applying"
            })

            # Update change request to pending_confirmation
            await self._update_change_request(change, results, change.files, 'pending_confirmation')
            
            logger.info(f"Changes prepared and awaiting frontend confirmation for request {change.id}")
            
        except Exception as e:
            logger.error(f"Error preparing changes: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            await self._update_change_request(change, {}, [], 'failed')
            await self._send_error(f"Failed to prepare changes: {str(e)}")

    async def _process_message(self, text):
        """Process the initial request"""
        try:
            # Get or create conversation
            self.conversation = await self._get_or_create_conversation()
            logger.debug(f"Conversation ID: {self.conversation.id}")

            # Create message
            message = await self._create_message(text)
            logger.debug(f"Created message ID: {message.id}")

            # Get project context
            context = await self._get_project_context()
            logger.debug(f"Got project context with {len(context)} items")

            # Classify request
            classifier = RequestClassifier(context)
            changes = classifier.classify(text)
            logger.debug(f"Request classified: {changes}")

            if not changes or not changes.get('files'):
                logger.warning("No changes determined from classification")
                await self._send_error("Could not determine required changes")
                return

            # Create and process change request
            change = await self._create_change_request(changes)
            logger.debug(f"Created change request ID: {change.id}")

            await self._process_changes(change, changes)
            logger.debug(f"Processed changes for request {change.id}")

            await self._apply_changes(change)
            logger.info(f"Prepared changes for review for request {change.id}")

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            await self._send_error(f"Failed to process request: {str(e)}")

    async def _apply_confirmed_changes(self, change_id):
        """Apply changes after frontend confirmation"""
        try:
            # Get the pending change request
            change = await sync_to_async(AIChangeRequest.objects.get)(id=change_id)
            
            if change.status != 'pending_confirmation':
                await self._send_error("Changes are not in pending confirmation state")
                return

            results = json.loads(change.diff)
            applied_files = []
            
            # Apply each file change
            for file_path, data in results.items():
                try:
                    logger.debug(f"Applying changes to {file_path}")
                    
                    # Create or update file with new content
                    file_type = self._determine_file_type(file_path)
                    model_class = {
                        'template': TemplateFile,
                        'static': StaticFile,
                        'model': ModelFile,
                        'view': ViewFile,
                        'form': FormFile,
                        'project': ProjectFile,
                        'settings': SettingsFile,
                        'url': URLFile,
                        'app': AppFile
                    }.get(file_type, ProjectFile)

                    # Create or update the file
                    await sync_to_async(model_class.objects.update_or_create)(
                        project_id=self.project_id,
                        path=file_path,
                        defaults={'content': data['content']}
                    )
                    
                    applied_files.append(file_path)
                    logger.info(f"Successfully applied changes to {file_path}")
                    
                except Exception as e:
                    logger.error(f"Error applying changes to {file_path}: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    await self._send_error(f"Failed to apply changes to {file_path}: {str(e)}")
            
            # Update change request status
            if applied_files:
                await self._update_change_request(change, results, applied_files, 'applied')
                
                # Update the live preview
                try:
                    # Import required function from views
                    from create_api.views import setup_preview_project
                    
                    # Create a preview alias for this project and change
                    preview_alias = f"preview_{self.project_id}_after_{change.id}"
                    raw_label = self.conversation.app_name.lower()
                    
                    # Log the diff structure before sending to preview
                    logger.debug(f"[PREVIEW DEBUG] Diff structure for change {change.id}:")
                    for file_path, data in results.items():
                        if isinstance(data, dict):
                            logger.debug(f"[PREVIEW DEBUG] {file_path}: {len(data)} chars, keys: {list(data.keys())}")
                        else:
                            logger.debug(f"[PREVIEW DEBUG] {file_path}: {len(str(data))} chars")
                    
                    # Create the preview project
                    preview_modified_files = setup_preview_project(self.project_id, preview_alias, raw_label, change.id)
                    
                    # Log success and preview URL
                    preview_url = f"/projects/{self.project_id}/?preview_mode=after&preview_change_id={change.id}"
                    logger.info(f"[PREVIEW SUCCESS] Created live preview for change {change.id} at {preview_url}")
                    logger.debug(f"[PREVIEW FILES] Modified: {preview_modified_files}")
                    
                    # First send preview information to the client
                    await self.send_json({
                        "type": "preview_ready",
                        "change_id": change.id,
                        "preview_url": preview_url,
                        "previews": {
                            file_path: data['preview'] 
                            for file_path, data in results.items()
                        },
                        "full_diffs": results
                    })
                    
                    # Then show diff modal for user review
                    await self.send_json({
                        "type": "show_diff_modal",
                        "title": "Review Changes",
                        "message": "Please review the following changes before applying",
                        "files": list(results.keys()),
                        "change_id": change.id,
                        "diff": results
                    })
                    
                except Exception as e:
                    logger.error(f"[PREVIEW ERROR] Failed to setup preview: {str(e)}", exc_info=True)
                
                logger.info(f"Successfully processed changes for request {change.id}")
            else:
                await self._update_change_request(change, {}, [], 'failed')
                await self._send_error("No changes were applied")

        except Exception as e:
            logger.error(f"Error applying confirmed changes: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            await self._update_change_request(change, {}, [], 'failed')
            await self._send_error(f"Failed to apply changes: {str(e)}")

    @sync_to_async
    def _create_empty_file(self, file_path):
        """Create an empty file entry in the database"""
        file_type = self._determine_file_type(file_path)
        model_class = {
            'template': TemplateFile,
            'static': StaticFile,
            'model': ModelFile,
            'view': ViewFile,
            'form': FormFile,
            'project': ProjectFile,
            'settings': SettingsFile,
            'url': URLFile,
            'app': AppFile
        }.get(file_type, ProjectFile)

        # Create or update the file with empty content
        model_class.objects.update_or_create(
            project_id=self.project_id,
            path=file_path,
            defaults={'content': ''}
        )

    def _determine_file_type(self, file_path):
        """Dynamically determine file type based on path and content"""
        if file_path.endswith('.html'):
            return 'template'
        elif file_path.endswith('.py'):
            if 'views' in file_path:
                return 'view'
            elif 'models' in file_path:
                return 'model'
            elif 'forms' in file_path:
                return 'form'
            elif 'urls' in file_path:
                return 'url'
        elif file_path.endswith(('.js', '.css')):
            return 'static'
        return 'unknown'

    @database_sync_to_async
    def _update_change_request(self, change, results, files, status):
        """Update change request with results"""
        try:
            AIChangeRequest.objects.filter(id=change.id).update(
                diff=json.dumps(results),
                files=files,
                status=status
            )
            logger.debug(f"Updated change request {change.id} with status {status}")
        except Exception as e:
            logger.error(f"Error updating change request: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")

    async def _process_changes(self, change_request, changes):
        """Process each change in the request"""
        try:
            code_generator = CodeGenerator()
            results = []
            modified_files = []

            for change in changes:
                try:
                    if isinstance(change, str):
                        # Handle string case (shouldn't happen but just in case)
                        logger.warning(f"Unexpected string change: {change}")
                        continue

                    # Get file type and original content
                    file_path = change.get('file')
                    if not file_path:
                        logger.warning("Change object missing file path")
                        continue

                    # Generate code using the correct method
                    generated_code = await code_generator.generate_code_with_validation(
                        file_path,
                        {
                            'change': change.get('change', ''),
                            'request_type': change.get('request_type', '')
                        },
                        self.context,
                        ""  # Original content
                    )

                    if generated_code:
                        modified_files.append({
                            'file': file_path,
                            'content': generated_code
                        })
                        results.append({
                            'file': file_path,
                            'status': 'success',
                            'message': f'Generated code for {file_path}'
                        })
                    else:
                        results.append({
                            'file': file_path,
                            'status': 'error',
                            'message': f'No code generated for {file_path}'
                        })
                except Exception as e:
                    logger.error(f"Error applying changes to {change.get('file', 'unknown file')}: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    results.append({
                        'file': change.get('file', 'unknown file'),
                        'status': 'error',
                        'message': str(e)
                    })

            # Update change request with results
            await self._update_change_request(change_request, results, modified_files, 'pending_preview')
            
            # Create preview
            await self._create_preview(change_request.id, modified_files)
            
            return results

        except Exception as e:
            logger.error(f"Error processing changes: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    async def _create_preview(self, change_id, modified_files):
        """Create a preview for the changes"""
        try:
            # Generate preview URL
            preview_url = f"/projects/{self.project_id}/?preview_mode=after&preview_change_id={change_id}"
            
            # Log preview creation
            logger.debug(f"[PREVIEW DEBUG] Diff structure for change {change_id}:")
            logger.info(f"[PREVIEW SUCCESS] Created live preview for change {change_id} at {preview_url}")
            logger.debug(f"[PREVIEW FILES] Modified: {[f['file'] for f in modified_files]}")

            # Send preview info to frontend
            await self.send_json({
                'type': 'preview_ready',
                'preview_url': preview_url,
                'change_id': change_id
            })

            return True
        except Exception as e:
            logger.error(f"Error creating preview: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False