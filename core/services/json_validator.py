import re
import json

# ... existing code ...

async def sanitize_ai_response(response_text, detect_analytics=True, request_text=None):
    """
    Sanitize AI response to fix markdown formatting, escaped characters,
    and other issues that might affect rendering in the diff modal.
    """
    if not isinstance(response_text, str):
        return response_text
    
    # Remove markdown code block markers
    response_text = re.sub(r'```[a-z]*\n', '', response_text)
    response_text = re.sub(r'```', '', response_text)
    
    # Convert escaped newlines to actual newlines
    response_text = response_text.replace('\\n', '\n')
    
    # Remove HTML comments in templates that might interfere with parsing
    response_text = re.sub(r'<!--.*?-->', '', response_text)
    
    # Remove any truncation markers
    response_text = response_text.replace('...', '')
    
    # Fix any remaining escaped characters that might cause issues
    response_text = response_text.replace('\\"', '"')
    
    # Remove any markdown formatting indicators
    response_text = re.sub(r'\*\*|\*|__|\|', '', response_text)
    
    # Remove ```python, ```html, etc. language indicators
    response_text = re.sub(r'---\n+```[a-z]*\n', '', response_text)
    
    # Try to convert to JSON if the text starts with a curly brace
    if response_text.strip().startswith('{'):
        try:
            # Parse as JSON to validate and format
            json_data = json.loads(response_text)
            
            # Process file content in JSON
            if 'files' in json_data and isinstance(json_data['files'], dict):
                for file_path, content in json_data['files'].items():
                    if isinstance(content, str):
                        # Sanitize file content
                        json_data['files'][file_path] = content.replace('\\n', '\n')
            
            # Convert back to JSON string with proper formatting
            return json.dumps(json_data)
        except Exception as e:
            # If JSON parsing fails, continue with the original sanitized text
            pass
    
    return response_text 