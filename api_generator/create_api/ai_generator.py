import asyncio
import hashlib
import json
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
import aiohttp
import logging
from django.core.cache import cache
from .models import TemplateFile, StaticFile, ModelFile, ViewFile, FormFile, URLFile, AppFile, ProjectFile
from asgiref.sync import sync_to_async
import re
import ast
import os

logger = logging.getLogger(__name__)

CACHE_TIMEOUT = 3600  # 1 hour
TOGETHER_API_KEY = os.getenv("TOGETHER_AI_API_KEY")
MISTRAL_MODEL = "mistralai/Mixtral-8x7B-Instruct-v0.1"
API_URL = "https://api.together.xyz/inference"

def get_cache_key(prompt: str, file_path: str) -> str:
    """Generate a cache key based on the prompt and file path"""
    hash_input = f"{prompt}:{file_path}"
    return f"ai_gen:{hashlib.md5(hash_input.encode()).hexdigest()}"

@lru_cache(maxsize=100)
def get_prompt_template(file_type: str) -> str:
    """Get the appropriate prompt template based on file type"""
    templates = {
        'template': """
You are an AI assistant for a Django project. Modify the template content for {file_path}.
Focus ONLY on these changes: {change_desc}

Requirements:
1. Keep existing template structure
2. Use proper Django template syntax
3. DO NOT include {{% extends %}} or {{% block %}} tags - they will be added automatically
4. Focus only on the content that should go inside the content block
5. Available static files: {static_files}
6. Available URL patterns: {url_patterns}

Original Content:
{original_content}

Generate ONLY the template content that should go inside the content block.
""",
        'model': """
You are an AI assistant for a Django project. Generate or modify the Django model code for {file_path} to fulfill the request: {change_desc}.
- Ensure appropriate fields and relationships
- If modifying existing code, preserve the original structure
- Include proper imports and model validation
- Do not include "..." in the response; provide the full code

File: {file_path}
Required Change: {change_desc}
Context: {context}
""",
        'view': """
You are an AI assistant for a Django project. Generate or modify the Django view code for {file_path} to fulfill the request: {change_desc}.
- Include proper imports and view logic
- Handle form validation if needed
- Add appropriate error handling
- Ensure proper context data is passed to templates
- Do not include "..." in the response; provide the full code

File: {file_path}
Required Change: {change_desc}
Context: {context}
""",
        'form': """
You are an AI assistant for a Django project. Generate or modify the Django form code for {file_path} to fulfill the request: {change_desc}.
- Include proper field validation
- Add custom clean methods if needed
- Include appropriate widgets
- Handle file uploads properly if needed
- Do not include "..." in the response; provide the full code

File: {file_path}
Required Change: {change_desc}
Context: {context}
""",
        'url': """
You are an AI assistant for a Django project. Generate or modify the Django URL configuration for {file_path} to fulfill the request: {change_desc}.
- Include proper URL patterns
- Add appropriate path converters
- Include proper view imports
- Handle namespacing correctly
- Do not include "..." in the response; provide the full code

File: {file_path}
Required Change: {change_desc}
Context: {context}
""",
        'static': """
You are an AI assistant for a Django project. Generate {file_type} code for {file_path} to fulfill the request: {change_desc}.
Requirements:
1. Use modern {file_type} practices
2. Include responsive design considerations
3. Handle browser compatibility
4. Preserve existing functionality
5. Add appropriate comments
6. Ensure proper error handling

Existing content:
{original_content}

Required changes:
{change_desc}
"""
    }
    return templates.get(file_type, templates['static'])

async def call_ai_api_async(prompt: str, file_path: str, max_tokens: int = 8192, temperature: float = 0.2) -> Optional[str]:
    """Asynchronous version of AI API call with caching"""
    cache_key = get_cache_key(prompt, file_path)
    cached_result = cache.get(cache_key)
    if cached_result:
        logger.debug(f"Cache hit for {file_path}")
        return cached_result

    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
    payload = {
        "model": MISTRAL_MODEL,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=payload, headers=headers) as response:
                if response.status == 429:
                    logger.warning(f"Rate limited for {file_path}")
                    return None
                response.raise_for_status()
                result = await response.json()
                text = result.get("choices", [{}])[0].get("text", "").strip()
                
                if text and not text.endswith("..."):
                    cache.set(cache_key, text, CACHE_TIMEOUT)
                    return text
                return None
    except Exception as e:
        logger.error(f"API call failed for {file_path}: {str(e)}")
        return None

def analyze_dependencies(file_path: str, content: str, context: Dict) -> List[str]:
    """Analyze file dependencies based on imports and references"""
    dependencies = set()
    
    if file_path.endswith('.html'):
        # Find template inheritance
        extends_match = re.search(r'{%\s*extends\s+[\'"]([^\'"]+)[\'"]', content)
        if extends_match:
            dependencies.add(f"templates/{extends_match.group(1)}")
            
        # Find included templates
        includes = re.findall(r'{%\s*include\s+[\'"]([^\'"]+)[\'"]', content)
        for include in includes:
            dependencies.add(f"templates/{include}")
            
        # Find static file references
        static_files = re.findall(r'{%\s*static\s+[\'"]([^\'"]+)[\'"]', content)
        for static_file in static_files:
            dependencies.add(f"static/{static_file}")
            
    elif file_path.endswith('.py'):
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        if name.name.startswith('.'):
                            dependencies.add(f"{os.path.dirname(file_path)}/{name.name[1:]}.py")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith('.'):
                        dependencies.add(f"{os.path.dirname(file_path)}/{node.module[1:]}.py")
        except Exception as e:
            logger.error(f"Failed to parse Python file {file_path}: {str(e)}")
    
    return list(dependencies)

def enhance_context(file_path: str, context: Dict) -> Dict:
    """Enhance context with relevant information for better code generation"""
    enhanced = context.copy()
    
    # Add URL patterns
    url_patterns = []
    for path, content in context.items():
        if path.endswith('urls.py'):
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'path':
                        if len(node.args) >= 2:
                            pattern = ast.literal_eval(node.args[0])
                            url_patterns.append(pattern)
            except Exception:
                pass
    enhanced['url_patterns'] = url_patterns
    
    # Add model information
    models = {}
    for path, content in context.items():
        if path.endswith('models.py'):
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        models[node.name] = {
                            'fields': [],
                            'relationships': []
                        }
                        for child in node.body:
                            if isinstance(child, ast.Assign):
                                for target in child.targets:
                                    if isinstance(target, ast.Name):
                                        models[node.name]['fields'].append(target.id)
            except Exception:
                pass
    enhanced['models'] = models
    
    # Add form information
    forms = {}
    for path, content in context.items():
        if path.endswith('forms.py'):
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        forms[node.name] = {
                            'fields': [],
                            'widgets': []
                        }
            except Exception:
                pass
    enhanced['forms'] = forms
    
    return enhanced

def validate_dependencies(generated_code: str, file_path: str, context: Dict) -> bool:
    """Validate that all dependencies are available in the context"""
    dependencies = analyze_dependencies(file_path, generated_code, context)
    for dep in dependencies:
        if dep not in context:
            logger.warning(f"Missing dependency {dep} for {file_path}")
            return False
    return True

async def generate_code_batch(files_data: List[Dict]) -> Dict[str, str]:
    """Generate code for multiple files in parallel with enhanced context and validation"""
    async def process_file(file_data: Dict) -> Tuple[str, Optional[str]]:
        file_path = file_data['file_path']
        file_type = file_data['file_type']
        change_desc = file_data['change_desc']
        context = enhance_context(file_path, file_data.get('context', {}))
        original_content = file_data.get('original_content', '')

        prompt_template = get_prompt_template(file_type)
        prompt = prompt_template.format(
            file_path=file_path,
            file_type=file_type,
            change_desc=change_desc,
            context=json.dumps(context),
            original_content=original_content,
            static_files=json.dumps([k for k in context.keys() if k.startswith('static/')]),
            url_patterns=json.dumps(context.get('url_patterns', []))
        )

        result = await call_ai_api_async(prompt, file_path)
        
        if result and validate_dependencies(result, file_path, context):
            return file_path, result
        return file_path, None

    tasks = [process_file(file_data) for file_data in files_data]
    results = await asyncio.gather(*tasks)
    return {path: content for path, content in results if content is not None}

def validate_generated_code(file_type: str, content: str) -> bool:
    """Validate the generated code based on file type"""
    if not content or "..." in content:
        return False

    if file_type == 'template':
        try:
            from django.template import Template, Context
            Template(content)
            return True
        except Exception as e:
            logger.error(f"Template validation failed: {str(e)}")
            return False
    
    if file_type == 'python':
        try:
            import ast
            ast.parse(content)
            return True
        except Exception as e:
            logger.error(f"Python code validation failed: {str(e)}")
            return False

    return True

async def regenerate_failed_code(failed_files: List[Dict], max_retries: int = 3) -> Dict[str, str]:
    """Attempt to regenerate failed code with different parameters"""
    results = {}
    for attempt in range(max_retries):
        if not failed_files:
            break
            
        logger.info(f"Retry attempt {attempt + 1} for {len(failed_files)} files")
        
        # Adjust generation parameters for retry
        for file_data in failed_files:
            file_data['temperature'] = 0.2 + (attempt * 0.1)  # Gradually increase temperature
            file_data['max_tokens'] = 8192 + (attempt * 2048)  # Gradually increase max tokens
        
        retry_results = await generate_code_batch(failed_files)
        results.update(retry_results)
        
        # Filter out successful generations
        failed_files = [
            f for f in failed_files 
            if f['file_path'] not in retry_results
        ]
    
    return results

async def optimize_and_generate_code(files_data: List[Dict]) -> Dict[str, str]:
    """Main entry point for optimized code generation"""
    # Initial generation
    results = await generate_code_batch(files_data)
    
    # Identify failed generations
    failed_files = [
        f for f in files_data 
        if f['file_path'] not in results or not validate_generated_code(f['file_type'], results[f['file_path']])
    ]
    
    # Retry failed generations
    if failed_files:
        retry_results = await regenerate_failed_code(failed_files)
        results.update(retry_results)
    
    return results 