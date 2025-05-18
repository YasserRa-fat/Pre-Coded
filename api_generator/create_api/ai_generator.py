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
import traceback
import datetime
from core.services.code_validator import DjangoCodeValidator

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

async def call_ai_api_async(prompt: str, file_path: str = None, max_tokens: int = 4096, temperature: float = 0.2) -> Optional[str]:
    """Asynchronous version of AI API call with caching and token management"""
    cache_key = get_cache_key(prompt, file_path)
    cached_result = cache.get(cache_key)
    if cached_result:
        logger.debug(f"Cache hit for {file_path}")
        return cached_result

    logger.debug(f"Making API call for {file_path}")
    
    if not TOGETHER_API_KEY:
        logger.error("Together AI API key is not set. Please set the TOGETHER_AI_API_KEY environment variable.")
        return None

    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
    
    # More accurate token estimation
    special_chars = len(re.findall(r'[^a-zA-Z0-9\s]', prompt))
    prompt_tokens = (len(prompt) // 3) + special_chars  # 3 chars per token + extra for special chars
    
    # Adjust max_tokens based on prompt length
    MAX_TOTAL_TOKENS = 32000  # Model's maximum context length
    SAFETY_MARGIN = 1000     # Leave room for error in token estimation
    
    if prompt_tokens >= (MAX_TOTAL_TOKENS - SAFETY_MARGIN):
        logger.error(f"Prompt too long for {file_path} ({prompt_tokens} tokens)")
        return None
        
    # Calculate available tokens for completion
    max_completion_tokens = min(max_tokens, MAX_TOTAL_TOKENS - prompt_tokens - SAFETY_MARGIN)
    
    payload = {
        "model": MISTRAL_MODEL,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_completion_tokens,
        "stop": ["```", "---END---"]
    }

    async with aiohttp.ClientSession() as session:
        max_retries = 3
        retry_delay = 1
        last_error = None
        
        for attempt in range(max_retries):
            try:
                async with session.post(API_URL, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "choices" in data and data["choices"]:
                            result = data["choices"][0].get("text", "")
                            if result:
                                # Cache successful result
                                cache.set(cache_key, result, CACHE_TIMEOUT)
                                return result
                    elif response.status == 400:
                        data = await response.json()
                        error_msg = data.get("error", {}).get("message", "")
                        if "maximum context length" in error_msg.lower():
                            # Token limit exceeded, try with reduced tokens
                            max_completion_tokens = max_completion_tokens // 2
                            payload["max_tokens"] = max_completion_tokens
                            logger.warning(f"Reducing max_tokens to {max_completion_tokens} for {file_path}")
                            continue
                        last_error = error_msg
                    else:
                        last_error = f"API returned status code {response.status}"
                    
                    logger.error(f"API call failed for {file_path} (attempt {attempt + 1}/{max_retries}): {last_error}")
                    
            except Exception as e:
                last_error = str(e)
                logger.error(f"API call error for {file_path} (attempt {attempt + 1}/{max_retries}): {last_error}")
            
            # Wait before retrying with exponential backoff
            retry_delay = min(retry_delay * 2, 8)  # Cap at 8 seconds
            await asyncio.sleep(retry_delay)
    
    if last_error:
        logger.error(f"All attempts failed for {file_path}: {last_error}")
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

async def generate_code_batch(files_data: Dict[str, Dict]) -> Dict[str, str]:
    """Generate code for multiple files in parallel with enhanced context and validation"""
    if not files_data:
        logger.error("No files provided for code generation")
        return {}

    async def process_file(file_path: str, file_data: Dict) -> Tuple[str, Optional[str]]:
        try:
            if not file_path:
                logger.error("File data missing file_path")
                return None, None

            file_type = file_data.get('file_type')
            if not file_type:
                file_type = 'generic'  # Default to generic if not specified
                
            change_desc = file_data.get('change_desc', '')
            context = enhance_context(file_path, file_data.get('context', {}))
            original_content = file_data.get('original_content', '')

            # Get and format prompt template
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

            # Calculate token estimate for this file
            prompt_tokens = len(prompt) // 4  # Rough estimate
            max_response_tokens = min(4096, 32000 - prompt_tokens)  # Leave room for prompt

            # Generate code with adjusted token limit
            result = await call_ai_api_async(prompt=prompt, max_tokens=max_response_tokens)
            
            if not result:
                logger.warning(f"No content generated for {file_path}")
                return file_path, None

            # Validate dependencies and code
            if validate_dependencies(result, file_path, context) and validate_generated_code(file_type, result):
                return file_path, result
            else:
                logger.warning(f"Validation failed for {file_path}")
                return file_path, None

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {str(e)}")
            return None, None

    # Process files in parallel with concurrency limit
    semaphore = asyncio.Semaphore(3)  # Limit concurrent API calls
    
    async def process_with_semaphore(file_path: str, file_data: Dict) -> Tuple[str, Optional[str]]:
        async with semaphore:
            return await process_file(file_path, file_data)

    tasks = [process_with_semaphore(file_path, file_data) for file_path, file_data in files_data.items()]
    results = await asyncio.gather(*tasks)
    
    # Filter out None results and create response dict
    response = {}
    for path, content in results:
        if path and content:
            response[path] = content
            
    if not response:
        logger.error("No files selected in stage 1")
    else:
        logger.info(f"Successfully generated code for {len(response)} files")
        
    return response

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

async def regenerate_failed_code(failed_files: Dict[str, Dict], max_retries: int = 3) -> Dict[str, str]:
    """Attempt to regenerate failed code with different parameters"""
    results = {}
    for attempt in range(max_retries):
        if not failed_files:
            break
            
        logger.info(f"Retry attempt {attempt + 1} for {len(failed_files)} files")
        
        # Adjust generation parameters for retry
        for file_data in failed_files.values():
            file_data['temperature'] = 0.2 + (attempt * 0.1)  # Gradually increase temperature
            file_data['max_tokens'] = 8192 + (attempt * 2048)  # Gradually increase max tokens
        
        retry_results = await generate_code_batch(failed_files)
        results.update(retry_results)
        
        # Filter out successful generations
        failed_files = {
            file_path: file_data
            for file_path, file_data in failed_files.items()
            if file_path not in retry_results
        }
    
    return results

def group_related_files(files_data: Dict[str, Dict]) -> List[Dict[str, Dict]]:
    """Group related files together based on their dependencies and types"""
    groups = []
    remaining_files = files_data.copy()
    
    # Helper function to get file type
    def get_file_category(file_path: str) -> str:
        if file_path.endswith('.html'):
            return 'template'
        elif '/static/' in file_path or file_path.startswith('static/'):
            return 'static'
        elif 'models.py' in file_path:
            return 'model'
        elif 'views.py' in file_path:
            return 'view'
        elif 'forms.py' in file_path:
            return 'form'
        elif 'urls.py' in file_path:
            return 'url'
        return 'other'
    
    # First group: Models (they should be processed first as other files may depend on them)
    model_files = {k: v for k, v in remaining_files.items() if get_file_category(k) == 'model'}
    if model_files:
        groups.append(model_files)
        for k in model_files:
            remaining_files.pop(k)
    
    # Second group: Forms (they often depend on models)
    form_files = {k: v for k, v in remaining_files.items() if get_file_category(k) == 'form'}
    if form_files:
        groups.append(form_files)
        for k in form_files:
            remaining_files.pop(k)
    
    # Third group: Views (they may depend on both models and forms)
    view_files = {k: v for k, v in remaining_files.items() if get_file_category(k) == 'view'}
    if view_files:
        groups.append(view_files)
        for k in view_files:
            remaining_files.pop(k)
    
    # Fourth group: Templates (they depend on views)
    template_files = {k: v for k, v in remaining_files.items() if get_file_category(k) == 'template'}
    if template_files:
        groups.append(template_files)
        for k in template_files:
            remaining_files.pop(k)
    
    # Fifth group: Static files
    static_files = {k: v for k, v in remaining_files.items() if get_file_category(k) == 'static'}
    if static_files:
        groups.append(static_files)
        for k in static_files:
            remaining_files.pop(k)
    
    # Last group: Any remaining files
    if remaining_files:
        groups.append(remaining_files)
    
    return groups

async def optimize_and_generate_code(files_data: Dict[str, Dict]) -> Dict[str, str]:
    """Main entry point for optimized code generation with batching"""
    try:
        # First analyze and group files by type and relevance
        file_groups = {
            'model': {},
            'view': {},
            'form': {},
            'template': {},
            'static': {},
            'url': {},
            'other': {}
        }
        
        # Helper function to determine file relevance
        def is_file_relevant(file_path: str, change_desc: str) -> bool:
            # Convert both to lowercase for case-insensitive matching
            file_path = file_path.lower()
            change_desc = change_desc.lower()
            
            # Extract key terms from file path
            path_terms = set(file_path.replace('/', ' ').replace('.', ' ').split())
            desc_terms = set(change_desc.split())
            
            # Check for direct mentions of the file or its components
            if any(term in change_desc for term in path_terms):
                return True
                
            # Check for type-specific keywords
            if 'model' in file_path and any(term in desc_terms for term in ['model', 'database', 'field', 'table']):
                return True
            if 'view' in file_path and any(term in desc_terms for term in ['view', 'page', 'endpoint', 'route']):
                return True
            if 'form' in file_path and any(term in desc_terms for term in ['form', 'input', 'validation']):
                return True
            if 'template' in file_path and any(term in desc_terms for term in ['template', 'html', 'page', 'display']):
                return True
            if 'static' in file_path and any(term in desc_terms for term in ['static', 'css', 'style', 'javascript', 'js']):
                return True
            if 'url' in file_path and any(term in desc_terms for term in ['url', 'route', 'path', 'endpoint']):
                return True
                
            return False

        # Group files by type and filter for relevance
        for file_path, file_data in files_data.items():
            change_desc = file_data.get('change_desc', '')
            
            # Skip if file is not relevant to the change description
            if not is_file_relevant(file_path, change_desc):
                logger.debug(f"Skipping irrelevant file: {file_path}")
                continue
                
            # Determine file type
            if 'models.py' in file_path or '/models/' in file_path:
                file_groups['model'][file_path] = file_data
            elif 'views.py' in file_path or '/views/' in file_path:
                file_groups['view'][file_path] = file_data
            elif 'forms.py' in file_path or '/forms/' in file_path:
                file_groups['form'][file_path] = file_data
            elif file_path.endswith('.html') or '/templates/' in file_path:
                file_groups['template'][file_path] = file_data
            elif '/static/' in file_path or any(file_path.endswith(ext) for ext in ['.css', '.js', '.jpg', '.png']):
                file_groups['static'][file_path] = file_data
            elif 'urls.py' in file_path:
                file_groups['url'][file_path] = file_data
            else:
                file_groups['other'][file_path] = file_data

        # Process each group in sequence
        results = {}
        processing_order = ['model', 'form', 'view', 'url', 'template', 'static', 'other']
        
        for group_type in processing_order:
            group_files = file_groups[group_type]
            if not group_files:
                continue
                
            logger.info(f"Processing {len(group_files)} {group_type} files")
            
            # Process files in this group
            try:
                # Calculate token budget for this group
                total_tokens = sum(
                    len(str(data.get('original_content', ''))) // 3 +
                    len(json.dumps(data.get('context', {}))) // 3
                    for data in group_files.values()
                )
                
                # If total tokens exceed limit, process files individually
                if total_tokens > 16000:  # Conservative token limit
                    for file_path, file_data in group_files.items():
                        try:
                            file_result = await process_file_with_retries(
                                file_path=file_path,
                                prompt=get_prompt_template(group_type).format(
                                    file_path=file_path,
                                    file_type=group_type,
                                    change_desc=file_data.get('change_desc', ''),
                                    context=json.dumps(file_data.get('context', {})),
                                    original_content=str(file_data.get('original_content', '')),
                                    static_files=json.dumps([k for k in file_data.get('context', {}).keys() if k.startswith('static/')]),
                                    url_patterns=json.dumps(file_data.get('context', {}).get('url_patterns', []))
                                ),
                                max_tokens=4096,
                                file_type=group_type
                            )
                            if file_result:
                                results[file_path] = file_result
                        except Exception as e:
                            logger.error(f"Error processing {file_path}: {str(e)}")
                else:
                    # Process the group as a batch
                    batch_results = await process_batch_with_retries(group_files)
                    if batch_results:
                        results.update(batch_results)
                        
            except Exception as e:
                logger.error(f"Error processing {group_type} group: {str(e)}")
                continue

        if not results:
            logger.error("No valid code changes were generated")
            return {}
            
        logger.info(f"Successfully generated code for {len(results)} files")
        return results
        
    except Exception as e:
        logger.error(f"Error in optimize_and_generate_code: {str(e)}")
        logger.error(traceback.format_exc())
        return {}

async def process_file_with_retries(file_path: str, prompt: str, max_tokens: int, file_type: str) -> Optional[str]:
    """Process a single file with retries and validation"""
    max_retries = 3
    base_delay = 1  # Base delay in seconds
    
    for attempt in range(max_retries):
        try:
            # Adjust token limit based on attempt
            adjusted_tokens = max_tokens + (attempt * 1024)  # Increase token limit with each retry
            
            # Call AI with adjusted parameters
            result = await call_ai_api_async(
                prompt=prompt,
                max_tokens=adjusted_tokens,
                temperature=0.2 + (attempt * 0.1)  # Gradually increase temperature
            )
            
            if not result:
                logger.warning(f"No result generated for {file_path} on attempt {attempt + 1}")
                continue
                
            # Validate the generated code
            if validate_generated_code(file_type, result):
                logger.info(f"Successfully generated and validated code for {file_path}")
                return result
            else:
                logger.warning(f"Generated code validation failed for {file_path} on attempt {attempt + 1}")
                
            # Wait before retry with exponential backoff
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # Exponential backoff
                await asyncio.sleep(delay)
                
        except Exception as e:
            logger.error(f"Error processing {file_path} on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                await asyncio.sleep(delay)
                
    logger.error(f"Failed to generate valid code for {file_path} after {max_retries} attempts")
    return None

async def call_ai_multi_file(conversation, text, files_data):
    """Call AI service for multiple file changes with validation and refinement"""
    try:
        response = {
            'files': {},
            'metadata': {
                'files_processed': 0,
                'files_skipped': 0,
                'validation_attempts': 0
            }
        }

        # Handle refinement requests differently
        if isinstance(files_data, dict) and files_data.get('refinement_request'):
            try:
                result = await call_ai_api_async(prompt=text, max_tokens=8192, temperature=0.2)
                if result:
                    response['files'] = {'refined_content': result}
                return response
            except Exception as e:
                logger.error(f"Error in refinement request: {str(e)}")
                return {'error': str(e)}

        # Process regular file changes
        validator = DjangoCodeValidator()
        max_validation_attempts = 3

        for file_path, content in files_data.items():
            try:
                # Skip invalid file paths
                if not file_path or not isinstance(file_path, str):
                    logger.warning("Invalid file path, skipping")
                    response['metadata']['files_skipped'] += 1
                    continue

                # Initial content normalization
                normalized_content = None
                if isinstance(content, (dict, list)):
                    try:
                        normalized_content = json.dumps(content, indent=2)
                    except Exception as e:
                        logger.error(f"Error converting content to JSON for {file_path}: {str(e)}")
                        response['metadata']['files_skipped'] += 1
                        continue
                elif isinstance(content, str):
                    normalized_content = content
                else:
                    normalized_content = str(content)

                # Validate and refine content
                current_content = normalized_content
                is_valid = False
                validation_issues = []

                for attempt in range(max_validation_attempts):
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
                        logger.info(f"File {file_path} validated successfully on attempt {attempt + 1}")
                        break

                    # Store issues for potential refinement
                    validation_issues = issues

                    if attempt < max_validation_attempts - 1:
                        # Prepare refinement prompt
                        refinement_prompt = f"""
                        Please fix the following validation issues in {file_path}:
                        {', '.join(issues)}

                        Current content:
                        {current_content}

                        Requirements:
                        1. Fix all validation issues
                        2. Maintain the same functionality
                        3. Ensure proper syntax and imports
                        4. Return only the fixed content
                        """

                        # Get refined content
                        try:
                            refined_result = await call_ai_api_async(
                                prompt=refinement_prompt,
                                max_tokens=4096,
                                temperature=0.2 + (attempt * 0.1)
                            )
                            if refined_result:
                                current_content = refined_result
                                continue
                        except Exception as e:
                            logger.error(f"Refinement attempt {attempt + 1} failed: {str(e)}")

                    logger.warning(f"Validation failed for {file_path} after {attempt + 1} attempts: {issues}")

                if not is_valid:
                    response['metadata']['files_skipped'] += 1
                    logger.error(f"Failed to validate {file_path} after {max_validation_attempts} attempts")

            except Exception as e:
                logger.error(f"Error processing {file_path}: {str(e)}")
                response['metadata']['files_skipped'] += 1
                continue

        if not response['files']:
            logger.error("No valid files in response")
            return {'error': 'No valid code changes were generated'}

        logger.info(f"Processed {response['metadata']['files_processed']} files successfully")
        return response

    except Exception as e:
        logger.error(f"Error in call_ai_multi_file: {str(e)}")
        logger.error(traceback.format_exc())
        return {'error': str(e)}

async def process_batch_with_retries(batch: Dict[str, Dict], max_retries: int = 3) -> Dict[str, str]:
    """Process a batch of files with retries"""
    for attempt in range(max_retries):
        try:
            # Process files in parallel within the batch
            tasks = []
            for file_path, file_data in batch.items():
                # Prepare file-specific prompt
                file_type = file_data.get('file_type', 'generic')
                prompt_template = get_prompt_template(file_type)
                
                # Only include relevant context files
                context = {}
                for k, v in file_data.get('context', {}).items():
                    if k in batch or k.startswith('static/'):
                        context[k] = v
                
                prompt = prompt_template.format(
                    file_path=file_path,
                    file_type=file_type,
                    change_desc=file_data.get('change_desc', ''),
                    context=json.dumps(context),
                    original_content=str(file_data.get('original_content', '')),
                    static_files=json.dumps([k for k in context.keys() if k.startswith('static/')]),
                    url_patterns=json.dumps(file_data.get('context', {}).get('url_patterns', []))
                )
                
                # Calculate available tokens for this file
                content_tokens = len(str(file_data.get('original_content', ''))) // 3
                context_tokens = len(json.dumps(context)) // 3
                max_completion_tokens = min(4096, 32000 - content_tokens - context_tokens - 1000)
                
                task = asyncio.create_task(call_ai_api_async(
                    prompt=prompt,
                    max_tokens=max_completion_tokens
                ))
                tasks.append((file_path, task))
            
            # Wait for all tasks to complete
            results = {}
            for file_path, task in tasks:
                try:
                    result = await task
                    if result:
                        # Validate the generated code
                        if validate_generated_code(file_path, result):
                            results[file_path] = result
                        else:
                            logger.warning(f"Generated code validation failed for {file_path}")
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {str(e)}")
            
            if results:  # If we got any valid results, return them
                return results
                
            # If we got no results but have more retries, continue
            if attempt < max_retries - 1:
                logger.warning(f"Batch processing attempt {attempt + 1} failed, retrying...")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue
                
        except Exception as e:
            logger.error(f"Error in batch processing attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise  # Re-raise the last error if we're out of retries
    
    return {} 