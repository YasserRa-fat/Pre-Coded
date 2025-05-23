import json
import re
import logging
from typing import Optional, Tuple, Dict, Any, List
import traceback
from pathlib import Path
import os
import ast

logger = logging.getLogger(__name__)

class JSONValidator:
    """Centralized service for handling JSON validation and cleaning"""

    PLACEHOLDER_PATTERNS = [
        '...',
        '...content...',
        '...complete file content with your changes...',
        '...existing code...',
        '...rest of the code...',
        '// ... existing code ...',
        '# ... existing code ...',
        '<!-- ... existing code ... -->',
        '{/* ... existing code ... */}',
        '/* ... existing code ... */'
    ]

    FILE_TYPE_PATTERNS = {
        'python': {
            'required': [r'(?:^|\n)(?:import|from)\s+\w+'],
            'optional': [r'class\s+\w+', r'def\s+\w+', r'@\w+']
        },
        'template': {
            'required': [r'{%.*?%}|{{.*?}}|<!DOCTYPE\s+html|<html'],
            'optional': [r'<div', r'<script', r'<style']
        },
        'javascript': {
            'required': [r'(?:^|\n)(?:import|export|function|class|const|let|var)\s+\w+'],
            'optional': [r'addEventListener', r'querySelector', r'document\.']
        },
        'css': {
            'required': [r'[.#]?\w+\s*{'],
            'optional': [r'@media', r'@import', r'@keyframes']
        }
    }

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
    async def validate_and_parse(cls, text: str | dict) -> tuple[bool, dict, str]:
        """
        Validate and parse AI response with comprehensive error checking and detailed reporting.
        Returns tuple of (is_valid: bool, data: Optional[dict], error_message: Optional[str])
        """
        if not text:
            return False, None, "Empty response"
            
        try:
            logger.debug("=== Starting Comprehensive JSON Validation ===")
            
            # If input is already a dictionary, validate its structure
            if isinstance(text, dict):
                logger.debug("Input is already a dictionary, validating structure")
                if 'files' not in text:
                    return False, None, "Missing 'files' key in dictionary"
                    
                # Process file contents if present
                if isinstance(text['files'], dict):
                    for file_path, content in text['files'].items():
                        if isinstance(content, str):
                            # Skip placeholder content
                            if cls._is_placeholder_content(content):
                                logger.debug(f"Skipping placeholder content for {file_path}")
                                continue
                            # Handle code content
                            text['files'][file_path] = cls._handle_code_content(content)
                
                return True, text, None
                
            # If input is string, proceed with normal validation
            logger.debug(f"Input text length: {len(text)}")
            
            # Phase 1: Pre-processing and initial cleaning
            logger.debug("Phase 1: Pre-processing")
            text = cls.preprocess_json(text)
            
            # Phase 2: Parse JSON
            try:
                data = json.loads(text)
                
                # Process file contents
                if isinstance(data, dict) and 'files' in data:
                    for file_path, content in data['files'].items():
                        if isinstance(content, str):
                            # Skip placeholder content
                            if cls._is_placeholder_content(content):
                                logger.debug(f"Skipping placeholder content for {file_path}")
                                continue
                            # Handle code content
                            data['files'][file_path] = cls._handle_code_content(content)
                
                # Ensure required structure
                if isinstance(data, dict):
                    if 'files' not in data:
                        data['files'] = {}
                    if 'description' not in data:
                        data['description'] = "Generated from AI response"
                    if 'dependencies' not in data:
                        data['dependencies'] = {"python": [], "js": []}
                
                return True, data, None
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {str(e)}")
                cls._debug_json_error(text, e)
                
                # Try recovery
                recovered_data = await cls._attempt_json_recovery(text, e)
                if recovered_data:
                    logger.info("Successfully recovered JSON data")
                    return True, recovered_data, None
                    
                error_msg = cls._format_json_error(e, text)
                return False, None, error_msg
                
        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            logger.error(traceback.format_exc())
            return False, None, f"Validation error: {str(e)}"

    @classmethod
    def _remove_response_prefix(cls, text: str) -> str:
        """Remove common response prefixes"""
        prefixes = ['RESPONSE:', 'JSON:', 'OUTPUT:', 'RESULT:']
        text = text.strip()
        for prefix in prefixes:
            if text.upper().startswith(prefix):
                return text[len(prefix):].strip()
        return text

    @classmethod
    def _handle_multiple_json_objects(cls, text: str) -> str:
        """Handle cases with multiple JSON objects"""
        if '}{' in text:  # Multiple objects - take the first complete one
            return text[:text.find('}{') + 1]
        return text

    @classmethod
    def _validate_structure(cls, text: str) -> List[str]:
        """Validate basic JSON structure"""
        issues = []
        
        # Check for basic JSON indicators
        if not ('{' in text and '}' in text):
            issues.append("No valid JSON object structure found")
            return issues
        
        # Check bracket balance
        brace_count = text.count('{') - text.count('}')
        if brace_count != 0:
            issues.append(f"Unbalanced braces: {abs(brace_count)} {'extra' if brace_count > 0 else 'missing'} closing braces")
        
        # Check quote balance
        quote_count = text.count('"') % 2
        if quote_count != 0:
            issues.append("Unbalanced quotes")
        
        return issues

    @classmethod
    async def _attempt_json_recovery(cls, text: str, error: json.JSONDecodeError) -> Optional[dict]:
        """Attempt to recover from JSON parsing errors"""
        try:
            # Try fixing common issues
            fixed_text = cls._fix_common_json_issues(text)
            return json.loads(fixed_text)
        except:
            try:
                # Try extracting valid JSON object
                extracted = cls.extract_json_with_regex(text)
                if extracted:
                    return extracted
            except:
                return None

    @classmethod
    def _fix_common_json_issues(cls, text: str) -> str:
        """Fix common JSON formatting issues"""
        # Remove trailing commas
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        
        # Fix missing commas
        text = re.sub(r'([^"\\])"([^":{},\[\]\s]+"?\s*:)', r'\1",\2', text)
        
        # Fix unescaped quotes
        text = re.sub(r'(?<!\\)"(?![\s,}\]])', r'\"', text)
        
        return text

    @classmethod
    def _format_json_error(cls, error: json.JSONDecodeError, text: str) -> str:
        """Format JSON error with context"""
        error_context = text[max(0, error.pos-50):min(len(text), error.pos+50)]
        error_pointer = " " * (min(50, error.pos)) + "^"
        return f"JSON decode error: {str(error)}\nContext:\n{error_context}\n{error_pointer}"

    @classmethod
    def _validate_file_path(cls, path: str) -> Tuple[bool, List[str]]:
        """Validate file path"""
        issues = []
        
        if not isinstance(path, str):
            return False, [f"Invalid path type: {type(path)}"]
        
        if not path:
            return False, ["Empty file path"]
        
        if len(path) > 255:
            issues.append("File path exceeds maximum length")
        
        if '..' in path:
            issues.append("Path contains parent directory traversal")
        
        if '\\' in path:
            issues.append("Path contains backslashes (use forward slashes)")
        
        return len(issues) == 0, issues

    @classmethod
    async def _validate_file_content(cls, file_path: str, content: str) -> tuple[bool, str, list[str]]:
        """Validate and process file content based on file type"""
        if not content:
            return False, "", ["Empty file content"]
            
        issues = []
        try:
            # Handle placeholder content
            if cls._is_placeholder_content(content):
                logger.debug(f"Placeholder content detected in {file_path}")
                return True, content, ["Placeholder content will be replaced with actual implementation"]
            
            # Get file type from extension
            ext = os.path.splitext(file_path)[1].lower()
            
            # Process based on file type
            if ext in ['.py', '.pyw']:
                # Basic Python validation
                try:
                    ast.parse(content)
                except SyntaxError as e:
                    issues.append(f"Python syntax error: {str(e)}")
                    return False, content, issues
                
                # Check for basic structure but don't require it
                if not re.search(r'(?:^|\\n)(?:import|from)\\s+\\w+', content):
                    issues.append("Missing imports (warning)")
                if not re.search(r'(?:class|def)\\s+\\w+', content):
                    issues.append("No classes or functions defined (warning)")
                
            elif ext in ['.html', '.htm']:
                # Basic template validation
                if not ('{% extends' in content or '<!DOCTYPE' in content or '<html' in content):
                    issues.append("Missing template structure (warning)")
                if not re.search(r'{%.*?%}|{{.*?}}', content):
                    issues.append("No template tags found (warning)")
                
            elif ext in ['.js', '.jsx']:
                # Basic JS validation
                if not re.search(r'function\\s+\\w+|class\\s+\\w+|const\\s+\\w+|let\\s+\\w+|var\\s+\\w+', content):
                    issues.append("Missing JavaScript declarations (warning)")
                
            elif ext in ['.css', '.scss', '.sass']:
                # Basic CSS validation
                if not re.search(r'[.#]?\\w+\\s*{', content):
                    issues.append("No CSS rules found (warning)")
            
            # Always return True unless there are critical errors
            # Warnings are just logged but don't invalidate the content
            critical_issues = [i for i in issues if "warning" not in i.lower()]
            if critical_issues:
                return False, content, critical_issues
            
            return True, content, issues
            
        except Exception as e:
            logger.error(f"Error validating {file_path}: {str(e)}")
            return False, content, [f"Validation error: {str(e)}"]

    @classmethod
    def _is_placeholder_content(cls, content: str) -> bool:
        """Check if content is a placeholder that needs to be implemented"""
        if not isinstance(content, str):
            return False
            
        # Common placeholder patterns
        patterns = [
            r'^\.{3,}$',  # Just dots
            r'^\.{3,}.*\.{3,}$',  # Dots with text in between
            r'^\.{3,}.*$',  # Dots at start with text
            r'^.*\.{3,}$',  # Text with dots at end
            r'^\s*<placeholder>.*</placeholder>\s*$',
            r'^\s*TODO:.*$',
            r'^\s*IMPLEMENT:.*$',
            r'^\s*#\s*\.{3,}\s*$',  # Python comment with dots
            r'^\s*//\s*\.{3,}\s*$',  # JS comment with dots
            r'^\s*/\*\s*\.{3,}\s*\*/\s*$',  # CSS comment with dots
            r'^\s*complete\s+file\s+content\s+with\s+your\s+changes\s*$',  # Common AI placeholder
            r'^\s*existing\s+code\s*$',  # Common code placeholder
            r'^\s*content\s*$',  # Simple content placeholder
            r'^\s*your\s+changes\s*$'  # Changes placeholder
        ]
        
        # Check if content matches any placeholder pattern
        content = content.strip()
        return any(re.match(pattern, content, re.DOTALL | re.IGNORECASE) for pattern in patterns)

    @classmethod
    def _validate_dependencies(cls, dependencies: Any) -> List[str]:
        """Validate dependencies structure"""
        issues = []
        
        if not isinstance(dependencies, dict):
            return ["'dependencies' must be a dictionary"]
        
        required_fields = {'python', 'js'}
        missing_fields = required_fields - set(dependencies.keys())
        if missing_fields:
            issues.append(f"Missing dependency fields: {', '.join(missing_fields)}")
        
        for dep_type, deps in dependencies.items():
            if not isinstance(deps, list):
                issues.append(f"Dependencies for {dep_type} must be a list")
            else:
                # Clean and validate each dependency
                dependencies[dep_type] = [str(d).strip() for d in deps if str(d).strip()]
        
        return issues

    @staticmethod
    def _normalize_file_path(path: str) -> str:
        """Normalize file path to consistent format"""
        if not path:
            return ""
        # Convert to forward slashes and remove any leading/trailing slashes
        clean_path = path.replace('\\', '/').strip('/')
        # Remove any parent directory traversal
        while '../' in clean_path:
            clean_path = clean_path.replace('../', '')
        return clean_path

    @classmethod
    def preprocess_json(cls, text: str | dict) -> str | dict:
        """Preprocess JSON with enhanced code content handling"""
        logger.debug("=== Starting JSON Preprocessing ===")
        
        try:
            # If input is already a dictionary, return it as is
            if isinstance(text, dict):
                logger.debug("Input is already a dictionary, skipping preprocessing")
                return text
                
            # Remove markdown code block markers
            text = text.replace('```json\n', '').replace('```', '')
            
            # Remove RESPONSE: prefix if present
            if text.strip().upper().startswith('RESPONSE:'):
                text = text[text.upper().find('RESPONSE:') + 9:].strip()
            
            # Find the actual JSON content
            json_start = text.find('{')
            json_end = text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                text = text[json_start:json_end]
            
            # First pass: Extract placeholders to preserve them
            placeholders = {}
            placeholder_count = 0
            
            # Save placeholders using regex pattern matching
            for pattern in cls.PLACEHOLDER_PATTERNS:
                # Escape special regex characters in the pattern
                escaped_pattern = re.escape(pattern)
                # Create a regex pattern that matches the placeholder with optional quotes and ellipsis
                regex_pattern = f'(?:"({escaped_pattern})")|(?:({escaped_pattern}))|(?:"([^"]*?{escaped_pattern}[^"]*?)")|(?:([^"]*?{escaped_pattern}[^"]*?))'
                
                def save_placeholder(match):
                    nonlocal placeholder_count
                    # Get the matched content from any of the groups
                    content = next((g for g in match.groups() if g is not None), None)
                    if content:
                        key = f"__PLACEHOLDER_{placeholder_count}__"
                        placeholders[key] = content
                        placeholder_count += 1
                        return f'"{key}"'
                    return match.group(0)
                
                text = re.sub(regex_pattern, save_placeholder, text)
            
            # Second pass: Extract code content
            code_blocks = {}
            code_block_count = 0
            
            def save_code_block(match):
                nonlocal code_block_count
                content = match.group(1)
                # Skip if it's a placeholder or contains a placeholder
                if any(p in content for p in cls.PLACEHOLDER_PATTERNS) or any(p in content for p in placeholders.values()):
                    return f'"{content}"'
                placeholder = f"__CODE_BLOCK_{code_block_count}__"
                code_blocks[placeholder] = content
                code_block_count += 1
                return f'"{placeholder}"'
            
            # Extract code content from JSON strings
            text = re.sub(r'"((?:[^"\\]|\\.)*)"', save_code_block, text)
            
            # Fix common JSON formatting issues
            text = cls._fix_json_formatting(text)
            
            # Process each code block
            for placeholder, content in code_blocks.items():
                # Skip if it contains a placeholder
                if any(p in content for p in placeholders.values()):
                    continue
                # Properly escape newlines
                content = content.replace('\n', '\\n')
                # Escape quotes
                content = content.replace('"', '\\"')
                # Fix double escaping
                content = content.replace('\\\\n', '\\n')
                content = content.replace('\\\\"', '\\"')
                # Replace placeholder with processed content
                text = text.replace(f'"{placeholder}"', f'"{content}"')
            
            # Restore placeholders
            for key, content in placeholders.items():
                # Ensure proper escaping for placeholders
                escaped_content = content.replace('"', '\\"').replace('\n', '\\n')
                text = text.replace(f'"{key}"', f'"{escaped_content}"')
            
            # Final cleanup
            text = text.strip()
            
            # Remove trailing commas
            text = re.sub(r',(\s*[}\]])', r'\1', text)
            
            # Validate the result
            try:
                json.loads(text)
                logger.debug("JSON validation successful after preprocessing")
            except json.JSONDecodeError as e:
                logger.error(f"JSON still invalid after preprocessing: {str(e)}")
                cls._debug_json_error(text, e)
            
            return text
            
        except Exception as e:
            logger.error(f"Error in preprocessing: {str(e)}")
            logger.error(traceback.format_exc())
            return text

    @staticmethod
    def _fix_json_formatting(text: str) -> str:
        """Fix common JSON formatting issues"""
        # Remove trailing commas
        text = re.sub(r',(\s*[}\]])', r'\1', text)
        
        # Fix missing quotes around property names
        text = re.sub(r'([{,]\s*)(\w+)(:)', r'\1"\2"\3', text)
        
        # Fix missing commas between elements
        text = re.sub(r'(["}\]])\s*({"?\w+"|[\[{])', r'\1,\2', text)
        
        # Fix spaces in property names
        text = re.sub(r'"([^"]+)\s+([^"]+)":', r'"\1\2":', text)
        
        # Fix unescaped newlines in strings
        text = re.sub(r'(?<!\\)\n', '\\n', text)
        
        return text

    @staticmethod
    def _handle_code_content(content: str) -> str:
        """Process code content to ensure proper escaping"""
        # Escape newlines
        content = content.replace('\n', '\\n')
        
        # Escape quotes
        content = content.replace('"', '\\"')
        
        # Fix any double escaping
        content = content.replace('\\\\n', '\\n')
        content = content.replace('\\\\"', '\\"')
        
        # Handle template tags
        content = content.replace('{%', '\\{%')
        content = content.replace('%}', '%\\}')
        content = content.replace('{{', '\\{{')
        content = content.replace('}}', '\\}}')
        
        return content

    @staticmethod
    def _debug_json_error(text: str | dict, error: Optional[json.JSONDecodeError] = None):
        """Debug helper for JSON content analysis"""
        logger.debug("\n=== JSON Content Analysis ===")
        try:
            # If input is a dictionary, convert to string for analysis
            if isinstance(text, dict):
                try:
                    text = json.dumps(text)
                except Exception as e:
                    logger.error(f"Error converting dictionary to string: {str(e)}")
                    return
            
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

    @staticmethod
    def _extract_template_tags(text: str) -> tuple[str, list]:
        """Extract Django template tags and replace with placeholders"""
        template_tags = []
        
        def save_tag(match):
            tag = match.group(0)
            template_tags.append(tag)
            return f"__TEMPLATE_TAG_{len(template_tags)-1}__"
            
        # Extract {% %} and {{ }} tags
        pattern = r'{%[^}]+%}|{{[^}]+}}'
        processed = re.sub(pattern, save_tag, text)
        
        return processed, template_tags

    @staticmethod
    def _restore_template_tags(text: str, template_tags: list) -> str:
        """Restore Django template tags from placeholders"""
        result = text
        for i, tag in enumerate(template_tags):
            placeholder = f'"__TEMPLATE_TAG_{i}__"'
            # Properly escape the tag for JSON
            escaped_tag = json.dumps(tag)[1:-1]  # Remove outer quotes
            result = result.replace(placeholder, escaped_tag)
        return result

    @staticmethod
    def _clean_code_blocks(text: str) -> str:
        """Clean code blocks and preserve their content"""
        # Remove markdown code block markers but keep content
        text = re.sub(r'```(?:json|python|html|javascript|js)?\n', '', text)
        text = re.sub(r'```', '', text)
        
        # Remove RESPONSE: prefix if present
        text = re.sub(r'^RESPONSE:\s*', '', text.strip())
        
        # Find the actual JSON content
        json_start = text.find('{')
        json_end = text.rfind('}')
        if json_start >= 0 and json_end > json_start:
            text = text[json_start:json_end + 1]
        
        return text.strip()

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