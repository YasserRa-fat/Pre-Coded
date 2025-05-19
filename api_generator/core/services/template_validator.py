import re
from typing import Dict, List, Tuple, Optional
import logging
from dataclasses import dataclass
from enum import Enum
from .ai_api_client import make_ai_api_call

logger = logging.getLogger(__name__)

class TemplateElementType(Enum):
    DJANGO_TAG = "django_tag"
    STATIC_TAG = "static_tag"
    HTML_TAG = "html_tag"
    SCRIPT_TAG = "script_tag"
    STYLE_TAG = "style_tag"

@dataclass
class ValidationIssue:
    element_type: TemplateElementType
    description: str
    line_number: Optional[int] = None
    context: Optional[str] = None

class DjangoTemplateValidator:
    """Specialized validator for Django templates with AI response validation"""
    
    def __init__(self):
        self.django_tag_pattern = re.compile(r'{%\s*(.+?)\s*%}')
        self.static_tag_pattern = re.compile(r'{%\s*static\s+[\'"](.+?)[\'"]\s*%}')
        self.html_tag_pattern = re.compile(r'<(\w+)(?:\s+[^>]*)?>')
        self.closing_tag_pattern = re.compile(r'</(\w+)>')

    def validate_template(self, content: str) -> Tuple[bool, List[ValidationIssue]]:
        """Main validation method for Django templates"""
        issues = []
        
        # Check basic template structure
        structure_issues = self._validate_template_structure(content)
        issues.extend(structure_issues)
        
        # Validate Django template tags
        django_issues = self._validate_django_tags(content)
        issues.extend(django_issues)
        
        # Validate static file references
        static_issues = self._validate_static_tags(content)
        issues.extend(static_issues)
        
        # Validate HTML structure
        html_issues = self._validate_html_structure(content)
        issues.extend(html_issues)
        
        # Validate script tags
        script_issues = self._validate_script_tags(content)
        issues.extend(script_issues)
        
        return len(issues) == 0, issues

    def _validate_template_structure(self, content: str) -> List[ValidationIssue]:
        """Validate overall template structure"""
        issues = []
        
        # Check for malformed concatenation
        if "+" in content and not ('"' in content or "'" in content):
            issues.append(ValidationIssue(
                TemplateElementType.DJANGO_TAG,
                "Detected string concatenation in template",
                context="Found '+' operator outside string literals"
            ))
            
        # Check for proper extends tag at start
        if content.strip().startswith("{% extends"):
            extends_match = re.match(r'{%\s*extends\s+[\'"](.+?)[\'"]\s*%}', content)
            if not extends_match:
                issues.append(ValidationIssue(
                    TemplateElementType.DJANGO_TAG,
                    "Malformed extends tag",
                    context="extends tag should be in format: {% extends 'template_name.html' %}"
                ))
                
        return issues

    def _validate_django_tags(self, content: str) -> List[ValidationIssue]:
        """Validate Django template tags"""
        issues = []
        
        # Find all Django tags
        tags = self.django_tag_pattern.finditer(content)
        for tag in tags:
            tag_content = tag.group(1)
            
            # Check for malformed tags
            if "DJANGO_TAG_START" in tag_content or "DJANGO_TAG_END" in tag_content:
                issues.append(ValidationIssue(
                    TemplateElementType.DJANGO_TAG,
                    "Invalid Django tag format",
                    context=f"Found placeholder text in tag: {tag_content}"
                ))
                
            # Validate block tags have matching endblock
            if tag_content.startswith("block"):
                block_name = tag_content.split()[-1]
                if f"endblock {block_name}" not in content and f"endblock" not in content:
                    issues.append(ValidationIssue(
                        TemplateElementType.DJANGO_TAG,
                        f"Missing endblock for block {block_name}",
                        context=f"Block tag: {tag_content}"
                    ))
                    
        return issues

    def _validate_static_tags(self, content: str) -> List[ValidationIssue]:
        """Validate static file references"""
        issues = []
        
        # Find all static tags
        static_refs = self.static_tag_pattern.finditer(content)
        for ref in static_refs:
            file_path = ref.group(1)
            
            # Check for malformed paths
            if "\\" in file_path or "//" in file_path:
                issues.append(ValidationIssue(
                    TemplateElementType.STATIC_TAG,
                    "Invalid static file path",
                    context=f"Path contains invalid characters: {file_path}"
                ))
                
            # Check for concatenated paths
            if "+" in file_path:
                issues.append(ValidationIssue(
                    TemplateElementType.STATIC_TAG,
                    "Static path contains concatenation",
                    context=f"Path: {file_path}"
                ))
                
        return issues

    def _validate_html_structure(self, content: str) -> List[ValidationIssue]:
        """Validate HTML structure"""
        issues = []
        tag_stack = []
        
        # Find all opening and closing tags
        for line_num, line in enumerate(content.split('\n'), 1):
            # Opening tags
            for match in self.html_tag_pattern.finditer(line):
                tag = match.group(1)
                if tag not in ['br', 'img', 'input', 'hr']:  # Self-closing tags
                    tag_stack.append((tag, line_num))
                    
            # Closing tags
            for match in self.closing_tag_pattern.finditer(line):
                tag = match.group(1)
                if tag_stack and tag_stack[-1][0] == tag:
                    tag_stack.pop()
                else:
                    issues.append(ValidationIssue(
                        TemplateElementType.HTML_TAG,
                        f"Mismatched HTML tags",
                        line_number=line_num,
                        context=f"Found closing tag {tag} without matching opening tag"
                    ))
                    
        # Check for unclosed tags
        for tag, line_num in tag_stack:
            issues.append(ValidationIssue(
                TemplateElementType.HTML_TAG,
                f"Unclosed HTML tag: {tag}",
                line_number=line_num
            ))
            
        return issues

    def _validate_script_tags(self, content: str) -> List[ValidationIssue]:
        """Validate script tags and their content"""
        issues = []
        
        # Find all script tags
        script_tags = re.finditer(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
        for script in script_tags:
            script_content = script.group(1)
            
            # Check for malformed Django variables in JavaScript
            if '{{' in script_content and not re.search(r'{{.*?}}', script_content):
                issues.append(ValidationIssue(
                    TemplateElementType.SCRIPT_TAG,
                    "Malformed Django variable in JavaScript",
                    context=f"Script contains unclosed Django variable"
                ))
                
            # Check for concatenated Django tags
            if '+{%' in script_content or '%}+' in script_content:
                issues.append(ValidationIssue(
                    TemplateElementType.SCRIPT_TAG,
                    "Concatenated Django tags in JavaScript",
                    context="Found Django tags being concatenated with '+'"
                ))
                
        return issues

class AITemplateResponseValidator:
    """Validates and fixes AI-generated template responses"""
    
    def __init__(self):
        self.template_validator = DjangoTemplateValidator()
        
    async def validate_and_fix(self, content: str, context: Dict) -> Tuple[str, List[ValidationIssue]]:
        """Validate AI response and attempt to fix issues"""
        # Initial validation
        is_valid, issues = self.template_validator.validate_template(content)
        
        if not is_valid:
            # Group issues by type for targeted fixing
            issues_by_type = self._group_issues_by_type(issues)
            
            # Fix each type of issue
            content = await self._fix_template_issues(content, issues_by_type, context)
            
            # Revalidate after fixes
            is_valid, remaining_issues = self.template_validator.validate_template(content)
            
            return content, remaining_issues
            
        return content, []
        
    def _group_issues_by_type(self, issues: List[ValidationIssue]) -> Dict[TemplateElementType, List[ValidationIssue]]:
        """Group validation issues by their type"""
        grouped = {}
        for issue in issues:
            if issue.element_type not in grouped:
                grouped[issue.element_type] = []
            grouped[issue.element_type].append(issue)
        return grouped
        
    async def _fix_template_issues(self, content: str, issues_by_type: Dict[TemplateElementType, List[ValidationIssue]], context: Dict) -> str:
        """Fix template issues using targeted AI calls"""
        fixed_content = content
        
        for element_type, issues in issues_by_type.items():
            if element_type == TemplateElementType.DJANGO_TAG:
                fixed_content = await self._fix_django_tags(fixed_content, issues, context)
            elif element_type == TemplateElementType.STATIC_TAG:
                fixed_content = await self._fix_static_tags(fixed_content, issues, context)
            elif element_type == TemplateElementType.HTML_TAG:
                fixed_content = await self._fix_html_structure(fixed_content, issues, context)
            elif element_type == TemplateElementType.SCRIPT_TAG:
                fixed_content = await self._fix_script_tags(fixed_content, issues, context)
                
        return fixed_content
        
    async def _fix_django_tags(self, content: str, issues: List[ValidationIssue], context: Dict) -> str:
        """Fix Django template tag issues using specialized AI prompts"""
        # Collect all Django tag issues
        tag_issues = [i for i in issues if i.element_type == TemplateElementType.DJANGO_TAG]
        if not tag_issues:
            return content
            
        # Create specialized prompt for Django template tag fixes
        prompt = f"""Fix the following Django template tag issues in the template content. 
The template is a Django template and should follow Django template syntax strictly.
Do not use string concatenation or placeholder tags like DJANGO_TAG_START.

Issues found:
{chr(10).join(f"- {i.description} ({i.context})" for i in tag_issues)}

Original template content:
{content}

Provide only the fixed template content, maintaining all functionality but fixing the template tag issues.
Use proper Django template tag syntax like {{% extends 'base.html' %}}, {{% block content %}}, etc.
Ensure all blocks have matching endblock tags.
"""

        try:
            fixed_content = await make_ai_api_call(prompt)
            if fixed_content:
                # Validate the fixed content
                is_valid, new_issues = self.template_validator.validate_template(fixed_content)
                if not is_valid:
                    logger.warning(f"AI fix for Django tags produced new issues: {new_issues}")
                    return content
                return fixed_content
        except Exception as e:
            logger.error(f"Error fixing Django tags: {str(e)}")
            
        return content
        
    async def _fix_static_tags(self, content: str, issues: List[ValidationIssue], context: Dict) -> str:
        """Fix static file reference issues using specialized AI prompts"""
        static_issues = [i for i in issues if i.element_type == TemplateElementType.STATIC_TAG]
        if not static_issues:
            return content
            
        prompt = f"""Fix the following static file reference issues in the Django template.
Each static file reference should use the proper Django static tag syntax: {{% static 'path/to/file' %}}
Do not use string concatenation or backslashes in paths.

Issues found:
{chr(10).join(f"- {i.description} ({i.context})" for i in static_issues)}

Original template content:
{content}

Provide only the fixed template content with proper static file references.
Use forward slashes in paths and keep paths relative to the static directory.
"""

        try:
            fixed_content = await make_ai_api_call(prompt)
            if fixed_content:
                # Validate the fixed content
                is_valid, new_issues = self.template_validator.validate_template(fixed_content)
                if not is_valid:
                    logger.warning(f"AI fix for static tags produced new issues: {new_issues}")
                    return content
                return fixed_content
        except Exception as e:
            logger.error(f"Error fixing static tags: {str(e)}")
            
        return content
        
    async def _fix_html_structure(self, content: str, issues: List[ValidationIssue], context: Dict) -> str:
        """Fix HTML structure issues using specialized AI prompts"""
        html_issues = [i for i in issues if i.element_type == TemplateElementType.HTML_TAG]
        if not html_issues:
            return content
            
        prompt = f"""Fix the following HTML structure issues in the Django template.
Ensure all HTML tags are properly nested and closed.
Preserve all Django template tags and their functionality.

Issues found:
{chr(10).join(f"- {i.description} (Line {i.line_number}: {i.context})" for i in html_issues)}

Original template content:
{content}

Provide only the fixed template content with proper HTML structure.
Maintain all Django template functionality while fixing HTML issues.
"""

        try:
            fixed_content = await make_ai_api_call(prompt)
            if fixed_content:
                # Validate the fixed content
                is_valid, new_issues = self.template_validator.validate_template(fixed_content)
                if not is_valid:
                    logger.warning(f"AI fix for HTML structure produced new issues: {new_issues}")
                    return content
                return fixed_content
        except Exception as e:
            logger.error(f"Error fixing HTML structure: {str(e)}")
            
        return content
        
    async def _fix_script_tags(self, content: str, issues: List[ValidationIssue], context: Dict) -> str:
        """Fix script tag issues using specialized AI prompts"""
        script_issues = [i for i in issues if i.element_type == TemplateElementType.SCRIPT_TAG]
        if not script_issues:
            return content
            
        prompt = f"""Fix the following script tag issues in the Django template.
Ensure proper handling of Django variables and tags within JavaScript code.
Do not use string concatenation with Django template tags.

Issues found:
{chr(10).join(f"- {i.description} ({i.context})" for i in script_issues)}

Original template content:
{content}

Provide only the fixed template content with proper script tag handling.
Use proper Django template variable syntax in JavaScript: {{ variable|escapejs }}
Ensure proper escaping of Django variables in JavaScript context.
"""

        try:
            fixed_content = await make_ai_api_call(prompt)
            if fixed_content:
                # Validate the fixed content
                is_valid, new_issues = self.template_validator.validate_template(fixed_content)
                if not is_valid:
                    logger.warning(f"AI fix for script tags produced new issues: {new_issues}")
                    return content
                return fixed_content
        except Exception as e:
            logger.error(f"Error fixing script tags: {str(e)}")
            
        return content

    @classmethod
    def create_fix_prompt(cls, issue_type: TemplateElementType, issues: List[ValidationIssue], content: str) -> str:
        """Create a specialized prompt based on the type of issues"""
        base_prompts = {
            TemplateElementType.DJANGO_TAG: """
Fix Django template tag issues:
- Use proper Django template tag syntax: {% tag %}
- Ensure matching endblock tags
- No string concatenation
- No placeholder tags
""",
            TemplateElementType.STATIC_TAG: """
Fix static file references:
- Use {% static 'path/to/file' %} syntax
- Use forward slashes in paths
- No string concatenation
- Paths relative to static directory
""",
            TemplateElementType.HTML_TAG: """
Fix HTML structure:
- Properly nested tags
- All tags closed
- Preserve Django template tags
- Valid HTML5 structure
""",
            TemplateElementType.SCRIPT_TAG: """
Fix script tag issues:
- Proper Django variable handling in JS
- Use {{ variable|escapejs }}
- No concatenation with template tags
- Proper JavaScript syntax
"""
        }
        
        return f"""{base_prompts[issue_type]}

Issues to fix:
{chr(10).join(f"- {i.description} ({i.context})" for i in issues)}

Original content:
{content}

Provide only the fixed content that resolves these issues while maintaining all functionality.""" 