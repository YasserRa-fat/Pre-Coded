import ast
import re
import logging
import os
import json
from typing import Dict, List, Tuple, Optional
from django.conf import settings

logger = logging.getLogger(__name__)

class DjangoCodeValidator:
    """Validates generated code for Django projects"""
    
    def __init__(self, project_context: Optional[Dict] = None):
        self.project_context = project_context or {}
        
    def validate_file(self, file_path: str, content: str | dict) -> Tuple[bool, List[str]]:
        """
        Validate a file based on its type and project context
        Returns: (is_valid, list_of_issues)
        """
        try:
            logger.debug(f"Validating file: {file_path}")
            
            # Handle JSON response
            if isinstance(content, str) and content.replace(' ', '').replace('\n', '').startswith('{'):
                try:
                    logger.debug("Content appears to be JSON, attempting to parse")
                    json_content = json.loads(content)
                    if isinstance(json_content, dict) and 'files' in json_content:
                        # Validate each file in the response
                        logger.debug("Found files dictionary in JSON content")
                        all_valid = True
                        all_issues = []
                        for file_path, file_content in json_content['files'].items():
                            logger.debug(f"Validating nested file: {file_path}")
                            is_valid, issues = self.validate_file(file_path, file_content)
                            if not is_valid:
                                all_valid = False
                            all_issues.extend(issues)
                        return all_valid, all_issues
                except json.JSONDecodeError:
                    logger.debug("Content is not valid JSON, proceeding with normal validation")
                    pass

            # Convert content to string if needed
            normalized_content = None
            if isinstance(content, dict):
                try:
                    logger.debug("Converting dictionary content to JSON string")
                    normalized_content = json.dumps(content, indent=2)
                except Exception as e:
                    logger.error(f"Error converting dictionary content: {str(e)}")
                    return False, [f"Error converting dictionary content to string: {str(e)}"]
            elif isinstance(content, str):
                normalized_content = content
            else:
                try:
                    logger.debug(f"Converting {type(content)} content to string")
                    normalized_content = str(content)
                except Exception as e:
                    logger.error(f"Error converting content to string: {str(e)}")
                    return False, [f"Error converting content to string: {str(e)}"]
                    
            # Skip validation for empty content
            if not normalized_content or not normalized_content.replace(' ', '').replace('\n', ''):
                logger.debug("Empty content, skipping validation")
                return True, []
                
            # Determine file type
            file_type = self._get_file_type(file_path)
            logger.debug(f"Determined file type: {file_type}")
            
            # Special handling for static files
            if file_path.startswith('static/'):
                logger.debug("Static file detected")
                if file_path.endswith('.js'):
                    return self._validate_javascript(file_path, normalized_content)
                elif file_path.endswith('.css'):
                    return self._validate_css(file_path, normalized_content)
                elif file_path.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
                    logger.debug("Image file, skipping validation")
                    return True, []  # Skip validation for image files
                logger.debug("Other static file, accepting without validation")
                return True, []  # Accept other static files without validation
            
            # Validate based on file type
            if file_type == 'python':
                logger.debug("Validating Python file")
                return self._validate_python(file_path, normalized_content)
            elif file_type == 'template':
                logger.debug("Validating template file")
                return self._validate_template(file_path, normalized_content)
            elif file_type == 'javascript':
                logger.debug("Validating JavaScript file")
                return self._validate_javascript(file_path, normalized_content)
            elif file_type == 'css':
                logger.debug("Validating CSS file")
                return self._validate_css(file_path, normalized_content)
            elif file_type == 'json':
                logger.debug("Validating JSON file")
                return self._validate_json(file_path, normalized_content)
            else:
                # For unknown file types, just check if it's valid text
                logger.debug("Unknown file type, checking text encoding")
                try:
                    normalized_content.encode('utf-8')
                    return True, []
                except UnicodeError:
                    return False, ["Invalid text encoding"]
                    
        except Exception as e:
            logger.error(f"Validation error: {str(e)}")
            return False, [f"Validation error: {str(e)}"]
            
    def _normalize_path(self, file_path: str) -> str:
        """Normalize file path for cross-platform compatibility"""
        logger.debug(f"Normalizing path: {file_path}")
        # Convert Windows backslashes to forward slashes
        normalized = file_path.replace('\\', '/')
        # Remove any drive letter prefix (e.g., C:)
        if ':' in normalized:
            normalized = normalized.split(':', 1)[1]
        # Ensure path starts with /
        if not normalized.startswith('/'):
            normalized = '/' + normalized
        logger.debug(f"Normalized path: {normalized}")
        return normalized
        
    def _validate_basic_syntax(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Basic syntax validation for all file types"""
        logger.debug(f"Performing basic syntax validation for {file_path}")
        issues = []
        
        # Check for common encoding issues
        try:
            content.encode('utf-8')
        except UnicodeEncodeError:
            logger.warning(f"Invalid Unicode characters in {file_path}")
            issues.append("File contains invalid Unicode characters")
            
        # Check for consistent line endings
        if '\r\n' in content and '\n' in content.replace('\r\n', ''):
            logger.warning(f"Mixed line endings in {file_path}")
            issues.append("Mixed line endings (CRLF and LF)")
            
        # Check for trailing whitespace
        if any(line.rstrip() != line for line in content.splitlines()):
            logger.warning(f"Trailing whitespace in {file_path}")
            issues.append("Lines contain trailing whitespace")
            
        return len(issues) == 0, issues
        
    def _get_file_type(self, file_path: str) -> str:
        """Determine file type from path"""
        logger.debug(f"Determining file type for {file_path}")
        if file_path.endswith('.py'):
            if any(x in file_path for x in ['/views/', 'views.py']):
                logger.debug("Identified as view file")
                return 'view'
            elif any(x in file_path for x in ['/models/', 'models.py']):
                logger.debug("Identified as model file")
                return 'model'
            elif any(x in file_path for x in ['/forms/', 'forms.py']):
                logger.debug("Identified as form file")
                return 'form'
            elif 'urls.py' in file_path:
                logger.debug("Identified as urls file")
                return 'urls'
            elif 'tests.py' in file_path:
                logger.debug("Identified as test file")
                return 'test'
            elif 'admin.py' in file_path:
                logger.debug("Identified as admin file")
                return 'admin'
            elif 'apps.py' in file_path:
                logger.debug("Identified as app file")
                return 'app'
            elif 'settings.py' in file_path:
                logger.debug("Identified as settings file")
                return 'settings'
            logger.debug("Identified as generic Python file")
            return 'python'
        elif file_path.endswith('.html'):
            if '/templates/' in file_path:
                if 'analytics' in file_path.lower():
                    logger.debug("Identified as analytics template")
                    return 'analytics_template'
                logger.debug("Identified as template file")
                return 'template'
            logger.debug("Identified as HTML file")
            return 'html'
        elif file_path.endswith('.js'):
            if '/static/' in file_path:
                if 'analytics' in file_path.lower() or 'chart' in file_path.lower():
                    logger.debug("Identified as analytics JavaScript")
                    return 'analytics_js'
                logger.debug("Identified as static JavaScript")
                return 'static_js'
            logger.debug("Identified as JavaScript file")
            return 'javascript'
        elif file_path.endswith('.css'):
            if '/static/' in file_path:
                if 'analytics' in file_path.lower() or 'chart' in file_path.lower():
                    logger.debug("Identified as analytics CSS")
                    return 'analytics_css'
                logger.debug("Identified as static CSS")
                return 'static_css'
            logger.debug("Identified as CSS file")
            return 'css'
        elif file_path.endswith('.json'):
            logger.debug("Identified as JSON file")
            return 'json'
        elif file_path.endswith('.md'):
            logger.debug("Identified as Markdown file")
            return 'markdown'
        logger.debug("Identified as generic file")
        return 'generic'
        
    def _validate_python(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Validate Python syntax and imports"""
        issues = []
        try:
            ast.parse(content)
        except SyntaxError as e:
            return False, [f"Python syntax error: {str(e)}"]
            
        # Check for common issues
        if 'import' not in content and 'from' not in content:
            issues.append("No imports found")
            
        # Check indentation
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            if line.strip() and (len(line) - len(line.lstrip())) % 4 != 0:
                issues.append(f"Line {i}: Indentation is not a multiple of 4 spaces")
                
        # Check for unused imports
        try:
            tree = ast.parse(content)
            imports = set()
            used = set()
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for name in node.names:
                        imports.add(name.name)
                elif isinstance(node, ast.Name):
                    used.add(node.id)
                    
            unused = imports - used
            if unused:
                issues.append(f"Unused imports: {', '.join(unused)}")
                
        except Exception as e:
            logger.warning(f"Error checking imports in {file_path}: {str(e)}")
            
        return len(issues) == 0, issues
        
    def _validate_view(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Validate Django view code"""
        is_valid, issues = self._validate_python(file_path, content)
        if not is_valid:
            return False, issues
            
        # Check for Django view essentials
        if 'from django' not in content:
            issues.append("Missing Django imports")
            
        view_patterns = [
            r'class\s+\w+View\(',
            r'class\s+\w+\(.*View\)',
            r'def\s+\w+\(request',
        ]
        
        has_view = any(re.search(pattern, content) for pattern in view_patterns)
        if not has_view:
            issues.append("No Django view found")
            
        # Check for common view patterns
        if 'request' in content and 'HttpResponse' not in content and 'render' not in content:
            issues.append("View may be missing response object")
            
        # Check for proper request handling
        if 'request.POST' in content and 'csrf' not in content:
            issues.append("POST request handler missing CSRF protection")
            
        return len(issues) == 0, issues
        
    def _validate_model(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Validate Django model code"""
        is_valid, issues = self._validate_python(file_path, content)
        if not is_valid:
            return False, issues
            
        if 'from django.db import models' not in content:
            issues.append("Missing Django models import")
            
        if not re.search(r'class\s+\w+\(models\.Model\)', content):
            issues.append("No Django model class found")
            
        # Check for common model patterns
        if 'models.Model' in content:
            # Check for __str__ method
            if '__str__' not in content:
                issues.append("Model missing __str__ method")
                
            # Check for proper field definitions
            field_patterns = [
                r'models\.\w+Field\(',
                r'models\.\w+Key\(',
                r'models\.ManyToManyField\('
            ]
            if not any(re.search(pattern, content) for pattern in field_patterns):
                issues.append("No model fields defined")
                
        return len(issues) == 0, issues
        
    def _validate_analytics_template(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Validate analytics-specific template code"""
        is_valid, issues = self._validate_template(file_path, content)
        
        # Check for required analytics elements
        required_elements = {
            'chart_container': (r'<div[^>]*id=[\'"]chart-container[\'"]', "Missing chart container div"),
            'analytics_container': (r'<div[^>]*id=[\'"]analytics-container[\'"]', "Missing analytics container div"),
            'static_load': (r'{%\s*load\s+static\s*%}', "Missing static files loading"),
            'chart_js': (r'<script[^>]*src=[\'"][^\'"]*/chart.*\.js[\'"]', "Missing chart.js script"),
            'analytics_css': (r'<link[^>]*href=[\'"][^\'"]*/analytics.*\.css[\'"]', "Missing analytics stylesheet")
        }
        
        for element, (pattern, message) in required_elements.items():
            if not re.search(pattern, content, re.IGNORECASE):
                issues.append(message)
        
        # Check for data attributes
        data_attributes = [
            'data-chart-type',
            'data-chart-data',
            'data-chart-options'
        ]
        
        for attr in data_attributes:
            if attr not in content:
                issues.append(f"Missing {attr} attribute for chart configuration")
        
        # Return valid if we have at least the basic structure
        has_basic_structure = (
            'chart-container' in content and
            'analytics-container' in content and
            'script' in content and
            'static' in content
        )
        
        return has_basic_structure, issues
        
    def _validate_analytics_js(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Validate analytics-specific JavaScript code"""
        is_valid, issues = self._validate_javascript(file_path, content)
        
        # Check for required analytics functionality
        required_functions = {
            'initialization': (r'function\s+init(ialize)?Chart', "Missing chart initialization function"),
            'data_loading': (r'(fetch|axios|ajax)\s*\(', "Missing data loading mechanism"),
            'error_handling': (r'try\s*{.*}\s*catch', "Missing error handling"),
            'responsiveness': (r'(window|chart)\s*\.\s*addEventListener\s*\(\s*[\'"]resize[\'"]', "Missing responsive handling")
        }
        
        for func, (pattern, message) in required_functions.items():
            if not re.search(pattern, content, re.DOTALL):
                issues.append(message)
        
        # Check for chart library usage
        chart_libraries = [
            r'new\s+Chart\(',
            r'Plotly\.newPlot\(',
            r'd3\.select\(',
            r'Highcharts\.chart\('
        ]
        
        has_chart_lib = any(re.search(pattern, content) for pattern in chart_libraries)
        if not has_chart_lib:
            issues.append("No recognized chart library initialization found")
        
        # Check for data processing
        data_processing = [
            r'\.map\(',
            r'\.filter\(',
            r'\.reduce\(',
            r'JSON\.parse\('
        ]
        
        has_data_processing = any(re.search(pattern, content) for pattern in data_processing)
        if not has_data_processing:
            issues.append("Missing data processing logic")
        
        # Return valid if we have the essential components
        has_essentials = (
            has_chart_lib and
            'addEventListener' in content and
            ('try' in content and 'catch' in content) and
            ('fetch' in content or 'axios' in content or 'ajax' in content)
        )
        
        return has_essentials, issues
        
    def _validate_analytics_css(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Validate analytics-specific CSS code"""
        is_valid, issues = self._validate_css(file_path, content)
        
        # Check for required analytics styling
        required_styles = {
            'containers': (r'\.(chart|analytics)-container\s*{', "Missing container styling"),
            'responsive': (r'@media\s*screen', "Missing responsive design rules"),
            'dimensions': (r'(width|height)\s*:', "Missing dimension specifications"),
            'layout': (r'(flex|grid)\s*:', "Missing modern layout properties")
        }
        
        for style, (pattern, message) in required_styles.items():
            if not re.search(pattern, content):
                issues.append(message)
        
        # Check for responsive breakpoints
        breakpoints = [
            r'@media[^{]+max-width',
            r'@media[^{]+min-width'
        ]
        
        has_breakpoints = any(re.search(pattern, content) for pattern in breakpoints)
        if not has_breakpoints:
            issues.append("Missing responsive breakpoints")
        
        # Check for chart-specific styling
        chart_styles = [
            r'\.chart\s*{[^}]*height',
            r'\.chart\s*{[^}]*width',
            r'\.chart\s*{[^}]*position'
        ]
        
        has_chart_styles = any(re.search(pattern, content) for pattern in chart_styles)
        if not has_chart_styles:
            issues.append("Missing chart-specific styling")
        
        # Return valid if we have the essential styles
        has_essentials = (
            '.chart-container' in content and
            '@media' in content and
            ('width' in content or 'height' in content) and
            ('flex' in content or 'grid' in content)
        )
        
        return has_essentials, issues
        
    def _validate_template(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Validate Django template code"""
        issues = []
        
        # Check for basic template structure
        if not ('{% extends' in content or '<html' in content.lower()):
            issues.append("No template inheritance or HTML structure found")
            
        # Check for balanced template tags
        if content.count('{%') != content.count('%}'):
            issues.append("Mismatched template tags")
            
        # Check for balanced blocks
        block_starts = len(re.findall(r'{%\s*block\s+\w+\s*%}', content))
        block_ends = len(re.findall(r'{%\s*endblock\s*%}', content))
        if block_starts != block_ends:
            issues.append("Mismatched template blocks")
            
        # Check for proper DOCTYPE and meta tags
        if '<html' in content.lower():
            if '<!DOCTYPE html>' not in content:
                issues.append("Missing DOCTYPE declaration")
            if '<meta charset=' not in content.lower():
                issues.append("Missing charset meta tag")
                
        # Check for accessibility
        if 'alt=' not in content and '<img' in content:
            issues.append("Images missing alt attributes")
            
        return len(issues) == 0, issues
        
    def _validate_javascript(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Basic JavaScript validation"""
        issues = []
        
        # Check for basic syntax issues
        if content.count('{') != content.count('}'):
            issues.append("Mismatched curly braces")
            
        if content.count('(') != content.count(')'):
            issues.append("Mismatched parentheses")
            
        # Check for common JS patterns
        if 'function' in content and 'return' not in content:
            issues.append("Functions missing return statements")
            
        if 'new Promise' in content and '.catch' not in content:
            issues.append("Promise without error handling")
            
        # Check for proper semicolon usage
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if line and not line.endswith(';') and not line.endswith('{') and not line.endswith('}'):
                issues.append(f"Line {i}: Missing semicolon")
                
        return len(issues) == 0, issues
        
    def _validate_css(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Basic CSS validation"""
        issues = []
        
        # Check for basic syntax issues
        if content.count('{') != content.count('}'):
            issues.append("Mismatched curly braces")
            
        # Check for vendor prefixes
        prefixes = ['-webkit-', '-moz-', '-ms-', '-o-']
        for prefix in prefixes:
            if prefix in content and not all(p in content for p in prefixes):
                issues.append("Inconsistent use of vendor prefixes")
                break
                
        # Check for !important usage
        if '!important' in content:
            issues.append("Use of !important found - consider refactoring")
            
        # Check for proper media queries
        if '@media' in content:
            media_queries = re.findall(r'@media[^{]+{', content)
            for query in media_queries:
                if 'screen' not in query and 'print' not in query:
                    issues.append("Media query missing screen/print specification")
                    
        return len(issues) == 0, issues
        
    def _validate_generic(self, file_path: str, content: str) -> Tuple[bool, List[str]]:
        """Generic file validation"""
        return True, []  # Accept any content for unknown file types 