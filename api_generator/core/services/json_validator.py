import json
import re
import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

class JSONValidator:
    """Centralized service for handling JSON validation and cleaning"""

    @staticmethod
    def clean_ai_response(response: str) -> str:
        """Clean AI response to prepare for JSON parsing"""
        if not response:
            return ""

        # Remove any content before the first {
        json_start = response.find('{')
        if json_start != -1:
            response = response[json_start:]

        # Remove any content after the last }
        json_end = response.rfind('}')
        if json_end != -1:
            response = response[:json_end + 1]

        # Remove code block markers
        response = re.sub(r'```json\s*', '', response)
        response = re.sub(r'```\s*$', '', response)

        # Remove comments
        response = re.sub(r'//.*$', '', response, flags=re.MULTILINE)
        response = re.sub(r'/\*.*?\*/', '', response, flags=re.DOTALL)

        # Fix common JSON formatting issues
        response = JSONValidator._fix_json_formatting(response)

        return response

    @staticmethod
    def _fix_json_formatting(json_str: str) -> str:
        """Fix common JSON formatting issues"""
        # Remove trailing commas before closing brackets
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        
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

    @staticmethod
    def validate_and_parse(text: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Validate and parse JSON text
        Returns: (is_valid, parsed_json, error_message)
        """
        if not text:
            return False, None, "Empty input"

        # Clean the response first
        cleaned_text = JSONValidator.clean_ai_response(text)
        
        # Handle backtick code blocks
        cleaned_text = JSONValidator.handle_backtick_code_blocks(cleaned_text)

        try:
            parsed = json.loads(cleaned_text)
            return True, parsed, ""
        except json.JSONDecodeError as e:
            error_msg = f"JSON parsing error: {str(e)}"
            logger.error(f"{error_msg}\nProblematic JSON: {cleaned_text}")
            return False, None, error_msg

    @staticmethod
    def extract_json_with_regex(text: str) -> Optional[Dict[str, Any]]:
        """Fallback method to extract JSON-like data using regex when parsing fails"""
        result = {}
        
        # Try to extract common patterns
        patterns = {
            "files": r'"files"\s*:\s*{([^}]+)}',
            "description": r'"description"\s*:\s*"([^"]+)"',
            "dependencies": r'"dependencies"\s*:\s*{([^}]+)}'
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.DOTALL)
            if match:
                if key in ["files", "dependencies"]:
                    # Parse the inner content
                    inner_content = match.group(1)
                    inner_dict = {}
                    # Extract key-value pairs
                    pairs = re.findall(r'"([^"]+)"\s*:\s*([^,}]+)', inner_content)
                    for k, v in pairs:
                        try:
                            # Try to parse value as JSON
                            inner_dict[k] = json.loads(v)
                        except:
                            # Fall back to string if parsing fails
                            inner_dict[k] = v.strip().strip('"')
                    result[key] = inner_dict
                else:
                    result[key] = match.group(1)

        return result if result else None 