import logging
import json
import traceback
from core.services.api_calls import make_ai_api_call_robust
from django.utils.translation import gettext_lazy as _

async def call_ai_multi_file(conversation, prompt_text, files_data=None):
    """
    Call the AI service with multiple files and a prompt
    """
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("Starting multi-file AI call")
        logger.debug(f"Files data keys: {list(files_data.keys()) if files_data else 'None'}")
        
        # Load project ID from thread local or files data
        project_id = None
        if hasattr(thread_local, 'project_id'):
            project_id = thread_local.project_id
        elif files_data and 'project_id' in files_data:
            project_id = files_data['project_id']
        
        logger.info(f"Project ID: {project_id}")
        logger.info(f"App name: {files_data.get('app_name') if files_data else None}")
        
        # Get project context if available
        project_context = None
        if 'project_context' in files_data:
            project_context = files_data['project_context']
            # Log the structure for debugging
            logger.debug("=== Project Context Structure ===")
            for key, value in project_context.items():
                if isinstance(value, list):
                    logger.debug(f"{key}: {len(value)} items")
                    if value:
                        logger.debug(f"First item sample: {value[0]}")
                else:
                    logger.debug(f"{key}: {type(value)}")
        
        # Check for analytics feature request
        detect_analytics = False
        if isinstance(prompt_text, str) and any(word in prompt_text.lower() for word in ['analytics', 'chart', 'graph', 'dashboard']):
            detect_analytics = True
            logger.info("Detected analytics feature request in call_ai_multi_file")
        
        # Prepare conversation context
        input_data = {
            'conversation': getattr(conversation, 'id', None),
            'text': prompt_text
        }
        logger.debug(f"Input - conversation: {input_data['conversation']}, text length: {len(input_data['text'])}")
        
        # Process request by type
        if files_data and 'files' in files_data:
            # We have files data directly
            input_data['files'] = files_data.get('files', {})
            
            # Enhance prompts based on feature detection
            input_data['prompt_enhancements'] = {
                'detect_analytics': detect_analytics,
                'marked_changes': True,  # Always enable marked changes for better diffing
                'change_marker_format': {
                    'begin': '// BEGIN_CHANGE: description',
                    'end': '// END_CHANGE',
                    'delete_start': '// DELETE_START: description',
                    'delete_end': '// DELETE_END'
                }
            }
            
            # Add specific file format instructions based on detected file types
            file_type_instructions = {
                'python': """
For Python files, mark changes with:
// BEGIN_CHANGE: Add imports for analytics
from django.db.models import Count
from django.utils import timezone
// END_CHANGE
""",
                'html': """
For HTML templates, mark changes with:
// BEGIN_CHANGE: Add analytics section
<div class="analytics-section">
  <!-- Chart container -->
  <canvas id="analytics-chart"></canvas>
</div>
// END_CHANGE
""",
                'js': """
For JavaScript files, mark changes with:
// BEGIN_CHANGE: Add chart initialization
document.addEventListener('DOMContentLoaded', function() {
  // Chart code here
});
// END_CHANGE
"""
            }
            
            # Add file type specific instructions if we have any file types detected
            file_types = set()
            for file_path in input_data['files'].keys():
                if file_path.endswith('.py'):
                    file_types.add('python')
                elif file_path.endswith('.html'):
                    file_types.add('html')
                elif file_path.endswith('.js'):
                    file_types.add('js')
            
            file_format_instructions = ""
            for file_type in file_types:
                if file_type in file_type_instructions:
                    file_format_instructions += file_type_instructions[file_type] + "\n"
            
            if file_format_instructions:
                input_data['prompt_enhancements']['file_format_instructions'] = file_format_instructions
            
        elif files_data and 'context' in files_data:
            # We have project context data
            input_data['context'] = files_data.get('context', {})
            logger.debug(f"Files data keys: {list(files_data.keys())}")
        
        # Get existing view files
        view_files = []
        if project_context and 'views' in project_context:
            view_files = [view.get('path') for view in project_context.get('views', [])]
        logger.debug(f"Existing view files: {view_files}")
        
        # Enhance the prompt with instructions for marked changes
        additional_instructions = """
IMPORTANT: Instead of replacing entire files, please mark your changes using:

// BEGIN_CHANGE: description
new or modified code
// END_CHANGE

For deletions, use:
// DELETE_START: description
code to delete
// DELETE_END

This helps me apply your changes accurately while preserving the rest of the file.
DO NOT use markdown formatting (```python, etc.) in your response.
DO NOT use escaped newlines (\\n) - use actual line breaks.
"""
        
        # Add the additional instructions to the prompt text if it's a string
        if isinstance(prompt_text, str):
            enhanced_prompt = f"{prompt_text}\n\n{additional_instructions}"
            input_data['text'] = enhanced_prompt
        
        # Make API call
        response = await make_ai_api_call_robust(input_data, detect_analytics)
        
        if response:
            # Sanitize the response
            from core.services.json_validator import sanitize_ai_response
            sanitized_response = await sanitize_ai_response(response, detect_analytics=detect_analytics, request_text=prompt_text)
            return json.loads(sanitized_response) if sanitized_response else None
        
        return None
    except Exception as e:
        logger.error(f"Error in call_ai_multi_file: {str(e)}")
        logger.error(traceback.format_exc())
        return None 