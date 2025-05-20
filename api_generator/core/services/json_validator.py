import json
import re
import logging
from typing import Optional, Tuple, Dict, Any, List
import traceback
from pathlib import Path
import os

logger = logging.getLogger(__name__)

class JSONValidator:
    """Centralized service for handling JSON validation and cleaning"""

    @staticmethod
    def is_feature_related(content: str) -> bool:
        """Dynamically detect if content is related to any feature by analyzing patterns"""
        if not content:
            return False
            
        # Use regex to find common feature patterns
        patterns = [
            r'class\s+\w+(?:View|Form|Model|Mixin)',  # Class definitions
            r'def\s+\w+(?:_view|_data|_api|_endpoint)',  # Function definitions
            r'@\w+(?:_required|_view|_api)',  # Decorators
            r'{% (?:block|extends|include)',  # Template tags
            r'<(?:div|section|canvas)\s+(?:id|class)=[\'"]\w+[\'"]\s*>',  # HTML elements
            r'function\s+\w+\s*\(',  # JavaScript functions
            r'const\s+\w+\s*=\s*(?:function|class|{)',  # JavaScript declarations
            r'import\s+.*from\s+[\'"].*[\'"]',  # Import statements
            r'@\w+\.?\w+.*\n*\s*def',  # Decorated functions
            r'<script[^>]*>.*?</script>',  # Script tags
            r'<style[^>]*>.*?</style>',  # Style tags
            r'url\([\'"].*?[\'"]\)',  # URL patterns
            r'@media\s+\w+',  # Media queries
            r'new\s+\w+\(',  # JavaScript instantiation
        ]
        
        # Debug feature detection
        JSONValidator._debug_feature_detection(content, patterns)
        
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE | re.DOTALL):
                return True
                
        return False

    @staticmethod
    async def get_dynamic_structure(file_path: str, content: str, file_type: str) -> str:
        """Generate dynamic structure for a file"""
        try:
            # First try local import
            try:
                from .ai_editor import make_ai_api_call
            except ImportError:
                # Fallback to direct import
                from core.services.ai_editor import make_ai_api_call
                
            logger.debug(f"Validating dynamic structure for {file_path}")
            
            # Debug current structure
            JSONValidator._debug_structure_validation(file_path, content, file_type)
            
            structure_prompt = f"""You are a code structure validator. Your task is to validate and complete this {file_type} file structure.

Input file path: {file_path}
Current content sample:
```
{content[:500]}...
```

CRITICAL REQUIREMENTS:
1. Preserve ALL existing functionality
2. Only add missing structural elements
3. For templates: Add proper extends/blocks if missing
4. For Python: Add necessary imports and class/function structure
5. For JS: Add proper module/function structure
6. Return ONLY the complete, valid code
7. Do not make assumptions about specific features
8. Keep all code dynamic and reusable
9. Remove any hardcoded feature names or paths
10. Use dependency injection and configuration where possible

Return the complete, valid file content with proper structure."""

            logger.debug("Making initial structure validation call")
            validated_content = await make_ai_api_call(
                prompt=structure_prompt,
                max_tokens=2048,
                temperature=0.2
            )
            
            # Debug validated structure
            if validated_content:
                logger.debug("Validating updated structure")
                JSONValidator._debug_structure_validation(file_path, validated_content, file_type)
            else:
                logger.error("No content returned from validation")

            return validated_content
                
        except Exception as e:
            logger.error(f"Error in dynamic structure validation: {str(e)}")
            logger.error(traceback.format_exc())
            return content

    @staticmethod
    def clean_ai_response(response: str) -> str:
        """Clean AI response to prepare for JSON parsing"""
        if not response:
            return ""

        logger.debug("=== Cleaning AI Response ===")
        logger.debug("Original response begins with: %s", response[:50] if len(response) > 50 else response)

        # Remove any prefixes before the first JSON bracket
        if '{' in response:
            json_start = response.find('{')
            if json_start > 0:
                prefix = response[:json_start].strip()
                if prefix and not ':' in prefix[-1:]:  # Not a JSON key:value pair
                    logger.debug("Removing non-JSON prefix: %s", prefix)
                response = response[json_start:]

        # Remove any content after the last }
        json_end = response.rfind('}')
        if json_end != -1:
            if len(response) > json_end + 1:
                suffix = response[json_end+1:].strip()
                if suffix:
                    logger.debug("Removing non-JSON suffix")
            response = response[:json_end + 1]

        # Remove code block markers
        response = re.sub(r'```json\s*', '', response)
        response = re.sub(r'```\s*$', '', response)

        # Remove comments
        response = re.sub(r'//.*$', '', response, flags=re.MULTILINE)
        response = re.sub(r'/\*.*?\*/', '', response, flags=re.DOTALL)

        # Fix common JSON formatting issues
        response = JSONValidator._fix_json_formatting(response)

        logger.debug("Cleaned response begins with: %s", response[:50] if len(response) > 50 else response)
        return response

    @staticmethod
    def _fix_json_formatting(json_str: str) -> str:
        """Fix common JSON formatting issues"""
        try:
            # Remove any BOM or special characters at the start
            if json_str.startswith('\ufeff'):
                json_str = json_str[1:]

            # Normalize line endings
            json_str = json_str.replace('\r\n', '\n').replace('\r', '\n')
            
            # Fix improper whitespace and tabs
            json_str = re.sub(r'[\t ]+', ' ', json_str)  # Normalize spaces and tabs
            json_str = re.sub(r'\n\s*\n', '\n', json_str)  # Remove empty lines
            
            # Fix escaped underscores (common in AI responses)
            json_str = re.sub(r'\\\_', '_', json_str)
            
            # Fix .DSStore entries (common in file listings)
            json_str = re.sub(r'\.DSStore', '.ds_store', json_str)
            
            # Remove trailing commas before closing brackets
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
            
            # Fix missing commas between properties
            json_str = re.sub(r'"\s*}\s*"', '"},\n"', json_str)
            json_str = re.sub(r'"\s*{\s*"', '",\n"', json_str)
            
            # Fix property names not in quotes
            json_str = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', json_str)
            
            # Fix escaped quotes in property names
            json_str = re.sub(r'\\+"([^"]+)\\+":', r'"\1":', json_str)
            
            # Fix missing quotes around property values
            json_str = re.sub(r':\s*([^",\{\[\]\}\s][^,\{\[\]\}\s]*)\s*([,\}\]])', r': "\1"\2', json_str)
            
            # Balance brackets
            open_curly = json_str.count('{')
            close_curly = json_str.count('}')
            open_square = json_str.count('[')
            close_square = json_str.count(']')

            # Add missing closing brackets
            if open_curly > close_curly:
                json_str += '}' * (open_curly - close_curly)
            if open_square > close_square:
                json_str += ']' * (open_square - close_square)

            # Remove extra closing brackets
            if close_curly > open_curly:
                json_str = re.sub(r'}' * (close_curly - open_curly) + '$', '', json_str)
            if close_square > open_square:
                json_str = re.sub(r']' * (close_square - open_square) + '$', '', json_str)

            # Try to parse and re-serialize to ensure valid JSON
            try:
                parsed = json.loads(json_str)
                return json.dumps(parsed, indent=4)
            except json.JSONDecodeError:
                return json_str

        except Exception as e:
            logger.error(f"Error in _fix_json_formatting: {str(e)}")
            return json_str

    @staticmethod
    def handle_backtick_code_blocks(text: str) -> str:
        """Replace backtick-quoted code blocks with properly escaped JSON strings"""
        try:
            return re.sub(
                r'`([^`]*)`',
                lambda m: json.dumps(m.group(1)),
                text
            )
        except Exception as e:
            logger.error(f"Error handling backtick code blocks: {str(e)}")
            return text

    @classmethod
    async def validate_and_parse(cls, text: str, detect_features=False) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Validate and parse AI-generated JSON with enhanced debugging"""
        if not text:
            return False, None, "Empty response text"
            
        try:
            logger.debug("=== Starting Response Validation ===")
            logger.debug("Feature detection: %s", detect_features)
            logger.debug("Input text length: %d", len(text))
            
            # Clean and normalize JSON
            cleaned_text = cls._clean_json_response(text)
            
            try:
                parsed = json.loads(cleaned_text)
                logger.debug("Successfully parsed JSON")
                
                # Basic structure validation
                if isinstance(parsed, dict):
                    # Convert any non-dict files section to dict
                    if 'files' in parsed and not isinstance(parsed['files'], dict):
                        logger.debug("Converting files section to dict")
                        files_content = str(parsed['files'])
                        parsed['files'] = {}
                        if ':' in files_content:
                            for line in files_content.split('\n'):
                                if ':' in line:
                                    key, value = line.split(':', 1)
                                    parsed['files'][key.strip()] = value.strip()
                    
                    return True, parsed, None
                    
                return False, None, "Invalid JSON structure"
                
            except json.JSONDecodeError as e:
                logger.error("JSON decode error: %s", str(e))
                cls._debug_json_error(cleaned_text, e)
                return False, None, str(e)
                
        except Exception as e:
            logger.error("Error in validate_and_parse: %s", str(e))
            logger.error(traceback.format_exc())
            return False, None, str(e)

    @classmethod
    def preprocess_json(cls, text: str) -> str:
        """Preprocess JSON with separated concerns"""
        logger.debug("=== Starting JSON Preprocessing ===")
        
        try:
            # Remove markdown markers first
            text = cls._remove_markdown_markers(text)
            
            # Handle backtick-quoted content
            text = cls._handle_backtick_content(text)
            
            # Attempt to extract JSON if we still can't parse it
            try:
                json.loads(text)
            except json.JSONDecodeError:
                # Try to find a valid JSON object in the text
                if '{' in text and '}' in text:
                    first_brace = text.find('{')
                    last_brace = text.rfind('}')
                    if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
                        logger.debug("Extracting JSON object from text")
                        text = text[first_brace:last_brace+1]
            
            # Fix escape sequences
            text = cls._fix_escape_sequences(text)
            
            # Try to parse JSON to validate
            try:
                json.loads(text)
                logger.debug("JSON validation successful after preprocessing")
            except json.JSONDecodeError as e:
                logger.error("JSON still invalid after preprocessing: %s", str(e))
                cls._debug_json_error(text, e)
            
            return text
            
        except Exception as e:
            logger.error("Error in preprocessing: %s", str(e))
            logger.error(traceback.format_exc())
            return text

    @staticmethod
    def _debug_json_error(text: str, error: json.JSONDecodeError):
        """Debug helper for JSON errors"""
        logger.error("=== JSON Error Analysis ===")
        logger.error("Error type: %s", type(error))
        logger.error("Error message: %s", str(error))
        logger.error("Position: line %d, column %d, char %d", error.lineno, error.colno, error.pos)
        
        # Show context around error
        lines = text.split('\n')
        if error.lineno <= len(lines):
            start = max(0, error.lineno - 2)
            end = min(len(lines), error.lineno + 2)
            context = '\n'.join("%d: %s" % (i+1, line) for i, line in enumerate(lines[start:end], start + 1))
            logger.error("Context around error:\n%s", context)
            logger.error("Error position: %s^", ' ' * (error.colno - 1))

    @staticmethod
    def _handle_backtick_content(text: str) -> str:
        """Handle backtick-quoted content in JSON responses"""
        logger.debug("=== Handling Backtick Content ===")
        logger.debug("Input text sample: %s", text[:100])
        
        try:
            # Track if we're inside a JSON string
            in_json_string = False
            in_backtick = False
            result = []
            i = 0
            
            while i < len(text):
                char = text[i]
                
                if char == '"' and (i == 0 or text[i-1] != '\\'):
                    in_json_string = not in_json_string
                    result.append(char)
                elif char == '`' and not in_json_string:
                    # Found a backtick outside JSON string
                    if not in_backtick:
                        # Start of backtick block - replace with JSON string start
                        in_backtick = True
                        result.append('"')
                    else:
                        # End of backtick block - replace with JSON string end
                        in_backtick = False
                        result.append('"')
                else:
                    if in_backtick:
                        # Inside backtick block - escape special characters
                        if char == '"':
                            result.append('\\"')
                        elif char == '\n':
                            result.append('\\n')
                        elif char == '\r':
                            result.append('\\r')
                        elif char == '\\':
                            result.append('\\\\')
                        else:
                            result.append(char)
                    else:
                        result.append(char)
                i += 1
                
            processed = ''.join(result)
            logger.debug("Processed text sample: %s", processed[:100])
            return processed
            
        except Exception as e:
            logger.error("Error handling backtick content: %s", str(e))
            logger.error(traceback.format_exc())
            return text

    @staticmethod
    def _handle_control_chars(text: str) -> str:
        """Handle control characters in JSON"""
        logger.debug("=== Processing Control Characters ===")
        logger.debug(f"Input length: {len(text)}")
        
        # Remove or replace control characters
        cleaned = ""
        for i, char in enumerate(text):
            if ord(char) < 32 and char not in '\n\r\t':
                logger.debug(f"Found control char at pos {i}: {ord(char)}")
                continue
            cleaned += char
        
        logger.debug(f"After control char processing length: {len(cleaned)}")
        return cleaned

    @staticmethod
    def _handle_newlines(text: str) -> str:
        """Handle newlines in JSON strings"""
        logger.debug("=== Processing Newlines ===")
        
        def escape_string_newlines(match):
            content = match.group(1)
            escaped = content.replace('\n', '\\n')
            logger.debug(f"Escaped newlines in string sample:\n{escaped[:100]}...")
            return f'"{escaped}"'
        
        # Escape newlines inside JSON strings
        processed = re.sub(r'"([^"]*)"', escape_string_newlines, text)
        logger.debug(f"After newline processing sample:\n{processed[:200]}")
        return processed

    @classmethod
    def extract_json_with_regex(cls, text):
        """Extract JSON using regex when JSON parsing fails"""
        try:
            logger.debug("Attempting regex-based JSON extraction")
            
            # Try to find a JSON object ignoring any prefixes or suffixes
            match = re.search(r'(\{[\s\S]*\})', text, re.DOTALL)
            if match:
                json_str = match.group(1)
                try:
                    return json.loads(cls.preprocess_json(json_str))
                except Exception as parse_error:
                    logger.error(f"JSON parsing failed after regex extraction: {str(parse_error)}")
                
            # Try to extract files map
            files = {}
            file_matches = re.finditer(r'"([^"]+)":\s*"([^"]+)"', text)
            for match in file_matches:
                files[match.group(1)] = match.group(2)
                
            if files:
                return {"files": files}
                
            return None
            
        except Exception as e:
            logger.error(f"Regex extraction failed: {str(e)}")
            return None
            
    @classmethod
    async def ensure_complete_file_content(cls, files_dict, request_text=None):
        """Ensure all file contents are complete files, not just fragments."""
        logger.debug("=== Starting Dynamic Content Validation ===")
        
        # Process each file
        dynamic_updates = {}
        
        # Track feature files and their relationships
        feature_files = []
        view_files = []
        template_files = []
        
        # Create a mapping of templates by their app
        template_by_app = {}
        
        # First pass: Identify all feature-related files and their types
        for file_path, content in files_dict.items():
            logger.debug(f"Processing file: {file_path}")
            
            # Use dynamic feature detection
            if cls.is_feature_related(content):
                feature_files.append(file_path)
                
                if file_path.endswith('views.py'):
                    view_files.append(file_path)
                    logger.debug(f"Found view file with features: {file_path}")
                elif file_path.endswith('.html'):
                    template_files.append(file_path)
                    
                    # Extract app from template path
                    app_name = None
                    path_parts = file_path.split('/')
                    
                    # Handle different template path formats
                    if len(path_parts) >= 2:
                        # Case 1: app/templates/template.html
                        if 'templates' in path_parts:
                            template_index = path_parts.index('templates')
                            if template_index > 0:
                                app_name = path_parts[template_index-1]
                        # Case 2: app/template.html
                        else:
                            app_name = path_parts[0]
                    
                    if app_name:
                        if app_name not in template_by_app:
                            template_by_app[app_name] = []
                        template_by_app[app_name].append(file_path)
                        logger.debug(f"Associated template {file_path} with app {app_name}")
                    
                    logger.debug(f"Found template file with features: {file_path}")
                    
                # Validate and update file structure based on type
                if file_path.endswith('.py'):
                    logger.debug(f"Validating Python file structure: {file_path}")
                    dynamic_updates[file_path] = await cls.get_dynamic_structure(file_path, content, "python")
                elif file_path.endswith('.html'):
                    logger.debug(f"Validating template file structure: {file_path}")
                    dynamic_updates[file_path] = await cls.get_dynamic_structure(file_path, content, "template")
                elif file_path.endswith('.js'):
                    logger.debug(f"Validating JavaScript file structure: {file_path}")
                    dynamic_updates[file_path] = await cls.get_dynamic_structure(file_path, content, "javascript")
        
        # Second pass: Ensure view-template relationships are properly handled
        if template_files and not view_files:
            logger.debug("Templates found but no corresponding views")
            
            # For each template, find its corresponding existing view file
            for app_name, app_templates in template_by_app.items():
                view_path = f"{app_name}/views.py"
                logger.debug(f"Looking for existing view file: {view_path}")
                
                # Only update existing view files, never create new ones
                if view_path in files_dict:
                    logger.debug(f"Using existing view file: {view_path}")
                    view_content = files_dict[view_path]
                    dynamic_updates[view_path] = await cls.get_dynamic_structure(view_path, view_content, "python")
                else:
                    logger.debug(f"View file {view_path} not found - skipping")

        # Apply all updates
        for file_path, updated_content in dynamic_updates.items():
            logger.debug(f"Applying validated updates to {file_path}")
            files_dict[file_path] = updated_content

        # Run strict AI review on all files
        files_dict = await cls.strict_ai_review(files_dict, request_text)

        return files_dict

    @staticmethod
    def _debug_response_format(text: str):
        """Debug helper to identify response format"""
        logger.debug("=== Response Format Analysis ===")
        first_char = text.strip()[0] if text.strip() else 'empty'
        logger.debug("First character: %s", first_char)
        logger.debug("Starts with JSON: %s", text.strip().startswith('{'))
        logger.debug("Contains recommendations: %s", 'RECOMMENDATIONS:' in text)
        logger.debug("First 100 chars:\n%s", text[:100])

    @staticmethod
    def _convert_recommendations_to_json(text: str) -> str:
        """Convert recommendations format to JSON"""
        logger.debug("Converting recommendations to JSON format")
        if not text.strip().startswith('RECOMMENDATIONS:'):
            return text
            
        try:
            # Extract file content sections if they exist
            file_content_start = text.find('```')
            files_json = {}
            
            if file_content_start != -1:
                # Process file contents
                parts = text.split('```')
                for i in range(1, len(parts), 2):
                    if i + 1 < len(parts):
                        file_header = parts[i].strip().split('\n')[0]
                        file_content = parts[i+1].strip()
                        if file_header:
                            files_json[file_header] = file_content
            
            # Create proper JSON structure
            response_json = {
                "files": files_json,
                "recommendations": [
                    line.strip()[2:].strip() 
                    for line in text.split('\n') 
                    if line.strip() and line.strip()[0].isdigit()
                ]
            }
            
            logger.debug("Converted to JSON structure with %d files", len(files_json))
            return json.dumps(response_json)
            
        except Exception as e:
            logger.error("Error converting recommendations to JSON: %s", str(e))
            return text

    @staticmethod
    def _sanitize_file_content(content: str) -> str:
        """Sanitize file content within JSON"""
        logger.debug("Sanitizing file content")
        try:
            # Escape quotes in HTML attributes
            content = re.sub(r'(\s+\w+)="([^"]*)"', r'\1=\"\2\"', content)
            # Escape newlines
            content = content.replace('\n', '\\n')
            # Escape backslashes
            content = content.replace('\\', '\\\\')
            # Escape quotes
            content = content.replace('"', '\\"')
            logger.debug("File content sanitized successfully")
            return content
        except Exception as e:
            logger.error("Error sanitizing file content: %s", str(e))
            return content

    @classmethod
    async def sanitize_ai_response(cls, response_text: str, detect_features=False, request_text=None) -> str:
        """Main sanitization entry point with enhanced debugging"""
        if not response_text:
            return ""
            
        # Debug the response format
        cls._debug_response_format(response_text)
        
        try:
            # First try to convert recommendations format if present
            if 'RECOMMENDATIONS:' in response_text:
                logger.debug("Detected recommendations format")
                response_text = cls._convert_recommendations_to_json(response_text)
                
            # Clean up JSON structure
            cleaned_text = cls.preprocess_json(response_text)
            
            try:
                # Parse and re-sanitize file contents
                data = json.loads(cleaned_text)
                if isinstance(data, dict) and 'files' in data:
                    # Basic response data check without any validation requirements
                    if detect_features:
                        logger.debug("Feature detection active")
                        
                    # Store original file contents for before/after diff
                    original_files = {}
                    for file_path in data['files'].keys():
                        original_files[file_path] = data['files'][file_path]
                        
                    # First sanitize individual file contents
                    for file_path, content in data['files'].items():
                        # Validate file path length and content
                        if len(file_path) > 255:  # Standard filesystem limit
                            logger.warning(f"File path too long, truncating: {file_path[:50]}...")
                            continue
                            
                        # Clean and validate content
                        cleaned_content = cls._sanitize_file_content(content)
                        if cleaned_content:
                            data['files'][file_path] = cleaned_content
                        
                    # Ensure file content completeness using dynamic AI assistance
                    if detect_features:
                        data['files'] = await cls.ensure_complete_file_content(data['files'], request_text)
                        
                        # Track changes for diffing
                        if 'original_files' not in data:
                            data['original_files'] = {}
                            
                        # Store original versions of files for diff
                        for file_path, new_content in data['files'].items():
                            if file_path in original_files and original_files[file_path] != new_content:
                                logger.debug(f"Tracking file changes for: {file_path}")
                                data['original_files'][file_path] = original_files[file_path]
                        
                cleaned_text = json.dumps(data)
                logger.debug("Successfully sanitized and validated JSON structure")
                return cleaned_text
            except json.JSONDecodeError as e:
                logger.error("Error in JSON validation: %s", str(e))
                logger.error("Problematic JSON:\n%s", cleaned_text[:200])
                cls._debug_json_error(cleaned_text, e)
                return ""
                
        except Exception as e:
            logger.error("Error in sanitize_ai_response: %s", str(e))
            logger.error(traceback.format_exc())
            return ""

    @staticmethod
    def _remove_markdown_markers(text: str) -> str:
        """Remove markdown markers from the text"""
        logger.debug("=== Removing Markdown Markers ===")
        logger.debug("Original text starts with: %s", text[:50])
        
        # Remove --- markers and surrounding whitespace
        cleaned = re.sub(r'\n*---\n*', '', text)
        
        # Remove "RESPONSE:" or similar prefixes before JSON content
        if '{' in cleaned:
            json_start = cleaned.find('{')
            if json_start > 0:
                prefix_text = cleaned[:json_start].strip()
                if prefix_text and not prefix_text.endswith(':'): # Not a JSON key
                    logger.debug("Removing prefix before JSON: %s", prefix_text)
                    cleaned = cleaned[json_start:]
        
        logger.debug("Text after removing markers starts with: %s", cleaned[:50])
        return cleaned

    @staticmethod
    def _fix_escape_sequences(text: str) -> str:
        """Fix invalid escape sequences in JSON strings"""
        logger.debug("=== Fixing Escape Sequences ===")
        logger.debug("Processing text with length: %d", len(text))
        
        try:
            # Track string boundaries and escape status
            in_string = False
            escaped = False
            result = []
            i = 0
            
            while i < len(text):
                char = text[i]
                
                if char == '"' and not in_string:
                    in_string = not in_string
                    result.append(char)
                elif char == '\\':
                    if escaped:
                        # Double backslash - keep both
                        result.append('\\\\')
                        escaped = False
                    else:
                        escaped = True
                        # Don't append yet - wait to see next char
                elif escaped:
                    # Handle escape sequences
                    valid_escapes = {'n', 'r', 't', '"', '/', 'b', 'f'}
                    if char in valid_escapes:
                        result.append('\\' + char)
                    else:
                        # Invalid escape - escape the backslash itself
                        logger.debug("Found invalid escape sequence: \\%s at position %d", char, i)
                        result.append('\\\\' + char)
                    escaped = False
                else:
                    result.append(char)
                i += 1
                
            if escaped:  # Handle trailing backslash
                result.append('\\\\')
                
            processed = ''.join(result)
            logger.debug("Fixed escape sequences. Sample of result: %s", processed[:100])
            return processed
            
        except Exception as e:
            logger.error("Error fixing escape sequences: %s", str(e))
            logger.error("Error context - text sample: %s", text[:100])
            return text

    @staticmethod
    def _debug_escape_sequences(text: str, error_pos: int = None):
        """Debug helper for escape sequence issues"""
        logger.debug("=== Debug Escape Sequences ===")
        if error_pos:
            start = max(0, error_pos - 20)
            end = min(len(text), error_pos + 20)
            context = text[start:end]
            pointer = " " * (min(20, error_pos - start)) + "^"
            logger.debug("Context around error:")
            logger.debug(context)
            logger.debug(pointer)
            
        # Find and log all escape sequences
        escapes = re.finditer(r'\\(.)', text)
        for match in escapes:
            pos = match.start()
            seq = match.group(0)
            char = match.group(1)
            logger.debug("Escape sequence at pos %d: %s (char: %s)", pos, seq, char)

    @staticmethod
    def _debug_json_structure(text: str, stage: str):
        """Debug helper to analyze JSON structure at different stages"""
        logger.debug("\n=== JSON Structure Analysis (%s) ===", stage)
        logger.debug("Text length: %d", len(text))
        logger.debug("First 100 chars:\n%s", text[:100])
        logger.debug("Last 100 chars:\n%s", text[-100:] if len(text) > 100 else text)
        logger.debug("Contains curly braces: { (%d) } (%d)", text.count('{'), text.count('}'))
        logger.debug("Contains quotes: ' (%d) \" (%d)", text.count("'"), text.count('"'))
        logger.debug("Contains backticks: ` (%d)", text.count('`'))
        logger.debug("Contains newlines: \\n (%d) actual newlines (%d)", text.count('\\n'), text.count(chr(10)))

    @staticmethod
    def _debug_json_content(text: str, error: Optional[json.JSONDecodeError] = None):
        """Debug helper for JSON content analysis"""
        logger.debug("\n=== JSON Content Analysis ===")
        try:
            # Check for common JSON issues
            issues = []
            if text.count('{') != text.count('}'):
                left_count = text.count('{')
                right_count = text.count('}')
                issues.append("Mismatched curly braces: left_count=%d, right_count=%d" % (left_count, right_count))
            if text.count('"') % 2 != 0:
                issues.append("Odd number of double quotes: %d" % text.count('"'))
            if '\\' in text and not '\\"' in text:
                issues.append("Contains unescaped backslashes")
            if text.strip().startswith('```') or text.strip().endswith('```'):
                issues.append("Contains markdown code blocks")
                
            if issues:
                logger.debug("Found potential JSON issues:")
                for issue in issues:
                    logger.debug("- %s", issue)
                    
            if error:
                logger.debug("\nJSON Error Details:")
                logger.debug("Error type: %s", type(error))
                logger.debug("Error message: %s", str(error))
                if hasattr(error, 'pos'):
                    context_start = max(0, error.pos - 50)
                    context_end = min(len(text), error.pos + 50)
                    logger.debug("Error context (±50 chars):\n%s", text[context_start:context_end])
                    logger.debug("Error position: %d", error.pos)
                    logger.debug("Character at error: %s", repr(text[error.pos]) if error.pos < len(text) else 'EOF')
                    
        except Exception as e:
            logger.error("Error in _debug_json_content: %s", str(e))

    @staticmethod
    def _debug_validation_error(text: str, error: Optional[json.JSONDecodeError] = None):
        """Debug helper for JSON validation errors"""
        logger.debug("\n=== JSON Validation Error Analysis ===")
        logger.debug("Input text length: %d", len(text))
        logger.debug("First 100 chars:\n%s", text[:100])
        
        if error:
            logger.debug("Error type: %s", type(error))
            logger.debug("Error message: %s", str(error))
            if hasattr(error, 'pos'):
                context_start = max(0, error.pos - 50)
                context_end = min(len(text), error.pos + 50)
                logger.debug("Error context (±50 chars):\n%s", text[context_start:context_end])
                logger.debug("Character at error: %s", repr(text[error.pos]) if error.pos < len(text) else 'EOF')
        
        # Check for common issues
        issues = []
        if text.count('{') != text.count('}'):
            left_count = text.count('{')
            right_count = text.count('}')
            issues.append("Mismatched braces: left_count=%d, right_count=%d" % (left_count, right_count))
        if text.count('"') % 2 != 0:
            issues.append("Odd number of quotes: %d" % text.count('"'))
        if '```' in text:
            issues.append("Contains markdown code blocks")
            
        # Generic file relationship validation - no specific feature assumptions
        if len(text) > 200:  # Only validate substantial responses
            logger.debug("Checking for basic file relationships")
            
            # Check for general project structure issues rather than specific features
            missing_components = []
            if 'views.py' not in text and ('.html' in text or 'template' in text.lower()):
                missing_components.append("server-side view code")
            if '.html' not in text and ('render' in text.lower() or 'template' in text.lower()):
                missing_components.append("HTML template")
                
            if missing_components:
                logger.debug("Response may need additional components: %s", ", ".join(missing_components))
            
        if issues:
            logger.debug("Potential issues found:")
            for issue in issues:
                logger.debug("- %s", issue)

    @staticmethod
    def _debug_analytics_response(response_dict: Dict[str, Any]):
        """Debug helper for analytics response validation"""
        logger.debug("\n=== Analytics Response Analysis ===")
        
        if not isinstance(response_dict, dict):
            logger.error("Response is not a dictionary")
            return
            
        if 'files' not in response_dict:
            logger.error("Response missing 'files' key")
            return
            
        files = response_dict['files']
        logger.debug("Files in response: %s", list(files.keys()))
        
        # Check for required analytics files
        view_files = [f for f in files.keys() if f.endswith('views.py')]
        template_files = [f for f in files.keys() if f.endswith('.html')]
        js_files = [f for f in files.keys() if f.endswith('.js')]
        
        logger.debug("View files: %s", view_files)
        logger.debug("Template files: %s", template_files)
        logger.debug("JS files: %s", js_files)
        
        # Validate view file content
        for view_file in view_files:
            content = files[view_file]
            logger.debug("Analyzing view file: %s", view_file)
            if 'JsonResponse' not in content:
                logger.warning("View may be missing JSON response handling")
            if 'datetime' not in content:
                logger.warning("View may be missing datetime imports")
            if 'def get_analytics_data' not in content:
                logger.warning("View may be missing analytics data endpoint")
                
        # Validate template file content
        for template_file in template_files:
            content = files[template_file]
            logger.debug("Analyzing template file: %s", template_file)
            if 'analytics-graph' not in content:
                logger.warning("Template may be missing analytics graph container")
            if 'static' not in content:
                logger.warning("Template may be missing static file references")
                
        # Validate JS file content
        for js_file in js_files:
            content = files[js_file]
            logger.debug("Analyzing JS file: %s", js_file)
            if 'fetch(' not in content:
                logger.warning("JS may be missing AJAX calls")
            if 'chart' not in content.lower():
                logger.warning("JS may be missing chart initialization")

    @classmethod
    async def strict_ai_review(cls, files_dict: Dict[str, str], request_text: str = None) -> Dict[str, str]:
        """Strict AI reviewer to validate and fix issues in generated files"""
        logger.debug("=== Starting Strict AI Review ===")
        
        try:
            # Track files that need fixes
            files_to_fix = {}
            
            for file_path, content in files_dict.items():
                logger.debug(f"Reviewing file: {file_path}")
                
                # Basic validation checks
                issues = []
                
                # Check file path length
                if len(file_path) > 255:
                    issues.append("File path exceeds maximum length")
                    
                # Check content size
                if len(content) > 1_000_000:  # 1MB limit
                    issues.append("File content too large")
                    
                # Dynamic feature detection
                if cls.is_feature_related(content):
                    logger.debug(f"Detected feature-related content in {file_path}")
                    
                    # Validate file structure based on type
                    if file_path.endswith('.py'):
                        if 'import' not in content[:500]:
                            issues.append("Missing imports section")
                    elif file_path.endswith('.html'):
                        if '{% block' not in content and '{% extends' not in content:
                            issues.append("Missing template inheritance")
                    elif file_path.endswith('.js'):
                        if 'function' not in content and '=>' not in content:
                            issues.append("Missing function definitions")
                            
                if issues:
                    logger.debug(f"Issues found in {file_path}: {issues}")
                    files_to_fix[file_path] = {
                        'content': content,
                        'issues': issues
                    }
                    
            # Fix issues using AI assistance
            if files_to_fix:
                logger.debug(f"Attempting to fix {len(files_to_fix)} files")
                fixed_files = await cls.get_dynamic_structure(
                    file_path=str(files_to_fix.keys()),
                    content=str(files_to_fix),
                    file_type="multiple"
                )
                
                # Update files with fixes
                if fixed_files:
                    try:
                        fixed_data = json.loads(fixed_files)
                        if isinstance(fixed_data, dict) and 'files' in fixed_data:
                            for file_path, fixed_content in fixed_data['files'].items():
                                if file_path in files_dict:
                                    files_dict[file_path] = fixed_content
                                    logger.debug(f"Applied fixes to {file_path}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Error parsing fixed files: {str(e)}")
                        
            return files_dict
            
        except Exception as e:
            logger.error(f"Error in strict AI review: {str(e)}")
            logger.error(traceback.format_exc())
            return files_dict

    @staticmethod
    def _remove_comments(text: str) -> str:
        """Remove both inline and block comments from JSON while preserving string content"""
        result = []
        in_string = False
        in_block_comment = False
        in_line_comment = False
        string_char = None
        i = 0
        
        while i < len(text):
            char = text[i]
            
            # Handle string boundaries
            if char in ['"', "'"] and (i == 0 or text[i-1] != '\\'):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
            
            # Only process comments outside of strings
            if not in_string:
                # Handle block comments
                if char == '/' and i + 1 < len(text) and text[i + 1] == '*' and not in_line_comment:
                    in_block_comment = True
                    i += 2
                    continue
                elif char == '*' and i + 1 < len(text) and text[i + 1] == '/' and in_block_comment:
                    in_block_comment = False
                    i += 2
                    continue
                # Handle line comments
                elif char == '/' and i + 1 < len(text) and text[i + 1] == '/' and not in_block_comment:
                    in_line_comment = True
                    i += 2
                    continue
                elif char == '\n' and in_line_comment:
                    in_line_comment = False
                    result.append(char)  # Keep the newline
                    i += 1
                    continue
            
            # Add character if not in a comment
            if not in_block_comment and not in_line_comment:
                result.append(char)
            
            i += 1
        
        return ''.join(result)

    @staticmethod
    def _clean_json_response(text: str) -> str:
        """Clean and normalize JSON response text"""
        logger.debug("Cleaning JSON response")
        
        try:
            # Remove any non-JSON prefix
            json_start = text.find('{')
            if json_start > 0:
                text = text[json_start:]
                
            # Remove any non-JSON suffix
            json_end = text.rfind('}')
            if json_end != -1:
                text = text[:json_end + 1]
                
            # Remove markdown code blocks
            text = re.sub(r'```\s*json\s*', '', text)
            text = re.sub(r'```', '', text)
            
            # Remove comments using the enhanced comment removal
            text = JSONValidator._remove_comments(text)
            
            # Fix common JSON formatting issues
            text = re.sub(r',(\s*[}\]])', r'\1', text)  # Remove trailing commas
            text = re.sub(r'([^"\\])"([^":{},\[\]\s]+"?\s*:)', r'\1",\2', text)  # Fix missing commas
            text = re.sub(r'([^"\\])"([^"]*?)"(?!\s*[,}\]])', r'\1","\2"', text)  # Fix string delimiters
            
            # Try to parse and re-serialize to ensure valid JSON
            try:
                data = json.loads(text)
                return json.dumps(data)
            except json.JSONDecodeError as e:
                logger.debug(f"Initial parse failed: {str(e)}, attempting recovery")
                
                # Try to extract valid JSON object
                matches = re.findall(r'({[^}]*})', text)
                for match in matches:
                    try:
                        data = json.loads(match)
                        if isinstance(data, dict) and data:  # Valid non-empty dict
                            return json.dumps(data)
                    except:
                        continue
                        
                # If no valid JSON found, try to build one from content
                if '"files"' in text:
                    files_content = re.findall(r'"files"\s*:\s*{([^}]*)}', text)
                    if files_content:
                        try:
                            reconstructed = '{' + f'"files":{{{files_content[0]}}}' + '}'
                            data = json.loads(reconstructed)
                            return json.dumps(data)
                        except:
                            pass
                            
                return text
                
        except Exception as e:
            logger.error(f"Error cleaning JSON response: {str(e)}")
            return text

    @classmethod
    async def resolve_view_path_from_template(cls, template_path: str) -> Optional[str]:
        """Dynamically resolve the corresponding view path from a template path"""
        logger.debug(f"Resolving view path from template: {template_path}")
        
        try:
            # Templates are already organized by app, extract the app name directly
            path_parts = template_path.split('/')
            app_name = None
            
            if len(path_parts) >= 2:
                # Case 1: app/templates/template.html
                if 'templates' in path_parts:
                    template_index = path_parts.index('templates')
                    if template_index > 0:
                        app_name = path_parts[template_index-1]
                # Case 2: app/template.html
                else:
                    app_name = path_parts[0]
            
            if app_name:
                view_path = f"{app_name}/views.py"
                logger.debug(f"Resolved view path: {view_path}")
                return view_path
            
            # If we get here, we couldn't determine the app, so return None
            logger.debug("Could not determine app from template path")
            return None
            
        except Exception as e:
            logger.error(f"Error resolving view path: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    @staticmethod
    def _debug_feature_detection(content: str, patterns: List[str]):
        """Debug helper for feature detection"""
        logger.debug("=== Feature Detection Analysis ===")
        logger.debug(f"Content length: {len(content)}")
        logger.debug("First 100 chars:\n%s", content[:100])
        
        for pattern in patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                logger.debug(f"Pattern '{pattern}' matched: {match.group(0)}")
                context_start = max(0, match.start() - 50)
                context_end = min(len(content), match.end() + 50)
                logger.debug(f"Match context:\n{content[context_start:context_end]}")

    @staticmethod
    def _debug_structure_validation(file_path: str, content: str, file_type: str):
        """Debug helper for structure validation"""
        logger.debug("\n=== Structure Validation Analysis ===")
        logger.debug(f"File: {file_path}")
        logger.debug(f"Type: {file_type}")
        logger.debug(f"Content length: {len(content)}")
        logger.debug("First 100 chars:\n%s", content[:100])
        
        # Check for common structural elements
        if file_type == "python":
            imports = re.findall(r'^import\s+.*$|^from\s+.*\s+import\s+.*$', content, re.MULTILINE)
            classes = re.findall(r'^class\s+\w+.*:$', content, re.MULTILINE)
            functions = re.findall(r'^def\s+\w+\s*\(.*\):$', content, re.MULTILINE)
            
            logger.debug("Python structure:")
            logger.debug(f"- Imports: {len(imports)}")
            logger.debug(f"- Classes: {len(classes)}")
            logger.debug(f"- Functions: {len(functions)}")
            
        elif file_type == "template":
            extends = re.findall(r'{%\s*extends\s+[\'"].*?[\'"]\s*%}', content)
            blocks = re.findall(r'{%\s*block\s+\w+\s*%}', content)
            includes = re.findall(r'{%\s*include\s+[\'"].*?[\'"]\s*%}', content)
            
            logger.debug("Template structure:")
            logger.debug(f"- Extends: {len(extends)}")
            logger.debug(f"- Blocks: {len(blocks)}")
            logger.debug(f"- Includes: {len(includes)}")
            
        elif file_type == "javascript":
            functions = re.findall(r'function\s+\w+\s*\(.*?\)', content)
            classes = re.findall(r'class\s+\w+\s*{', content)
            imports = re.findall(r'import\s+.*?from\s+[\'"].*?[\'"]\s*;?', content)
            
            logger.debug("JavaScript structure:")
            logger.debug(f"- Functions: {len(functions)}")
            logger.debug(f"- Classes: {len(classes)}")
            logger.debug(f"- Imports: {len(imports)}")
