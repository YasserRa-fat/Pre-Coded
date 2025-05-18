import ast
import re
import os
from typing import Tuple, List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class DjangoCodeValidator:
    """Validates Django code files for syntax and common issues"""
    
    def __init__(self, project_context: Dict[str, Any]):
        self.project_context = project_context
        self.file_validators = {
            '.py': self.validate_python_file,
            '.html': self.validate_template_file,
            '.js': self.validate_js_file,
            '.css': self.validate_css_file,
            '.json': self.validate_json_file
        }

    def validate_file(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Validate a file based on its extension"""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            validator = self.file_validators.get(ext)
            
            if not validator:
                return True, []  # Skip validation for unknown file types
                
            return validator(content)
            
        except Exception as e:
            logger.error(f"Error validating {file_path}: {str(e)}")
            return False, [str(e)]

    def validate_python_file(self, content: str) -> Tuple[bool, List[str]]:
        """Validate Python file for syntax and common Django issues"""
        issues = []
        
        # Check for syntax errors
        try:
            ast.parse(content)
        except SyntaxError as e:
            issues.append(f"Syntax error: {str(e)}")
            return False, issues
            
        # Check for common Django imports
        if 'models.py' in content.lower():
            if 'from django.db import models' not in content:
                issues.append("Missing 'from django.db import models' in models.py")
                
        if 'views.py' in content.lower():
            if 'from django.shortcuts import render' not in content:
                issues.append("Missing 'from django.shortcuts import render' in views.py")
                
        # Check for common patterns
        if 'class Meta:' in content and not re.search(r'class\s+Meta:', content):
            issues.append("Invalid Meta class definition")
            
        # Check for proper model definitions
        if 'models.Model' in content:
            model_pattern = r'class\s+\w+\(models\.Model\):'
            if not re.search(model_pattern, content):
                issues.append("Invalid model class definition")
                
        return len(issues) == 0, issues

    def validate_template_file(self, content: str) -> Tuple[bool, List[str]]:
        """Validate Django template file"""
        issues = []
        
        # Check for basic template syntax
        try:
            # Check for unmatched template tags
            open_tags = []
            for match in re.finditer(r'{%\s*(.*?)\s*%}', content):
                tag = match.group(1).split()[0]
                if tag.startswith('end'):
                    if not open_tags or f"end{open_tags[-1]}" != tag:
                        issues.append(f"Unmatched template tag: {tag}")
                    else:
                        open_tags.pop()
                elif tag in ['if', 'for', 'block', 'with']:
                    open_tags.append(tag)
                    
            if open_tags:
                issues.append(f"Unclosed template tags: {', '.join(open_tags)}")
                
            # Check for variable syntax
            var_pattern = r'{{[^}]*}}'
            if not re.match(var_pattern, content) and '{{' in content:
                issues.append("Invalid variable syntax")
                
        except Exception as e:
            issues.append(f"Template syntax error: {str(e)}")
            
        return len(issues) == 0, issues

    def validate_js_file(self, content: str) -> Tuple[bool, List[str]]:
        """Validate JavaScript file"""
        issues = []
        
        try:
            # Check for basic syntax issues
            if content.count('{') != content.count('}'):
                issues.append("Unmatched curly braces")
                
            if content.count('(') != content.count(')'):
                issues.append("Unmatched parentheses")
                
            # Check for common JS issues
            if 'new Array()' in content:
                issues.append("Use [] instead of new Array()")
                
            if 'new Object()' in content:
                issues.append("Use {} instead of new Object()")
                
        except Exception as e:
            issues.append(f"JavaScript validation error: {str(e)}")
            
        return len(issues) == 0, issues

    def validate_css_file(self, content: str) -> Tuple[bool, List[str]]:
        """Validate CSS file"""
        issues = []
        
        try:
            # Check for basic syntax
            if content.count('{') != content.count('}'):
                issues.append("Unmatched curly braces in CSS")
                
            # Check for invalid properties
            for line in content.split('\n'):
                if ':' in line and ';' not in line.strip():
                    issues.append("Missing semicolon in CSS declaration")
                    
            # Check for vendor prefixes
            vendor_prefixes = ['-webkit-', '-moz-', '-ms-', '-o-']
            for prefix in vendor_prefixes:
                if prefix in content:
                    issues.append(f"Consider using autoprefixer instead of {prefix}")
                    
        except Exception as e:
            issues.append(f"CSS validation error: {str(e)}")
            
        return len(issues) == 0, issues

    def validate_json_file(self, content: str) -> Tuple[bool, List[str]]:
        """Validate JSON file"""
        import json
        issues = []
        
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            issues.append(f"Invalid JSON: {str(e)}")
            
        return len(issues) == 0, issues 