from typing import Dict, List, Tuple, Optional
import logging
from .template_validator import AITemplateResponseValidator, ValidationIssue
from .ai_api_client import make_ai_api_call
from dataclasses import dataclass
from .json_validator import JSONValidator
import json

logger = logging.getLogger(__name__)

@dataclass
class TemplateValidationResult:
    is_valid: bool
    content: str
    issues: List[ValidationIssue]
    file_path: str

class TemplateAIIntegration:
    """Integration layer between template validation and AI editing"""
    
    def __init__(self):
        self.validator = AITemplateResponseValidator()
        
    async def process_template_response(self, response: Dict[str, Dict], context: Dict) -> Dict[str, str]:
        """Process and validate AI responses for template files"""
        # First validate the entire response as JSON
        is_valid, parsed_response, error_msg = JSONValidator.validate_and_parse(json.dumps(response))
        if not is_valid:
            logger.error(f"Invalid JSON response: {error_msg}")
            # Try fallback extraction
            parsed_response = JSONValidator.extract_json_with_regex(json.dumps(response))
            if not parsed_response:
                logger.error("Failed to extract valid JSON from response")
                return {}
        
        validated_responses = {}
        
        for file_path, file_info in parsed_response.items():
            if not isinstance(file_info, dict) or 'content' not in file_info:
                logger.error(f"Invalid response format for {file_path}")
                continue
                
            content = file_info['content']
            validation_result = await self.validate_and_fix_template(file_path, content, context)
            
            if validation_result.is_valid:
                validated_responses[file_path] = validation_result.content
            else:
                logger.warning(f"Template validation failed for {file_path}: {validation_result.issues}")
                # Fall back to original content if fixes failed
                validated_responses[file_path] = content
                
        return validated_responses
        
    async def validate_and_fix_template(self, file_path: str, content: str, context: Dict) -> TemplateValidationResult:
        """Validate and fix a single template file"""
        # Initial validation
        fixed_content, issues = await self.validator.validate_and_fix(content, context)
        
        if not issues:
            return TemplateValidationResult(True, fixed_content, [], file_path)
            
        # If first fix attempt failed, try more targeted approach
        try:
            targeted_content = await self._try_targeted_fixes(file_path, fixed_content, issues, context)
            if targeted_content:
                # Validate the targeted fixes
                is_valid, remaining_issues = self.validator.template_validator.validate_template(targeted_content)
                if is_valid:
                    return TemplateValidationResult(True, targeted_content, [], file_path)
                else:
                    logger.warning(f"Targeted fixes produced new issues for {file_path}: {remaining_issues}")
        except Exception as e:
            logger.error(f"Error during targeted fixes for {file_path}: {str(e)}")
            
        return TemplateValidationResult(False, content, issues, file_path)
        
    async def _try_targeted_fixes(self, file_path: str, content: str, issues: List[ValidationIssue], context: Dict) -> Optional[str]:
        """Attempt more targeted fixes using file-specific context"""
        # Create a specialized prompt based on file type and issues
        file_type = self._get_template_type(file_path)
        specialized_prompt = self._create_specialized_prompt(file_type, issues, content)
        
        try:
            fixed_content = await make_ai_api_call(specialized_prompt)
            if fixed_content:
                return fixed_content
        except Exception as e:
            logger.error(f"Error in targeted fix attempt: {str(e)}")
            
        return None
        
    def _get_template_type(self, file_path: str) -> str:
        """Determine template type from file path"""
        if 'base.html' in file_path:
            return 'base'
        elif '/components/' in file_path:
            return 'component'
        elif '/includes/' in file_path:
            return 'include'
        elif '/layouts/' in file_path:
            return 'layout'
        else:
            return 'view'
            
    def _create_specialized_prompt(self, template_type: str, issues: List[ValidationIssue], content: str) -> str:
        """Create a specialized prompt based on template type"""
        type_specific_instructions = {
            'base': """
This is a base template that other templates extend.
- Ensure proper block definitions
- Maintain core layout structure
- Keep all static file references
- Preserve meta tags and SEO elements
""",
            'component': """
This is a reusable component template.
- Keep component self-contained
- Ensure all required context variables are used
- Maintain component styling references
- Check for proper include syntax
""",
            'include': """
This is an included template snippet.
- Keep it focused and minimal
- Ensure context variables are passed correctly
- Check for proper template inheritance
- Maintain any required dependencies
""",
            'layout': """
This is a layout template.
- Preserve structural elements
- Maintain responsive design elements
- Keep all block definitions
- Ensure proper extends syntax
""",
            'view': """
This is a view template.
- Maintain all form handling
- Preserve view-specific logic
- Keep all required blocks
- Ensure proper model variable usage
"""
        }
        
        return f"""Fix the Django template issues while following these specific guidelines for {template_type} templates:

{type_specific_instructions[template_type]}

Current issues to fix:
{chr(10).join(f"- {i.description} ({i.context})" for i in issues)}

Original template content:
{content}

Provide only the fixed template content that resolves these issues while maintaining all functionality and following the type-specific guidelines above."""

async def validate_template_response(response: Dict[str, Dict], context: Dict) -> Dict[str, str]:
    """Convenience function for template validation"""
    integration = TemplateAIIntegration()
    return await integration.process_template_response(response, context) 