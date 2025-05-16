import re
from typing import Dict, List, Optional, Set, Tuple
from django.template import Template, Context, TemplateSyntaxError
import logging

logger = logging.getLogger(__name__)

class TemplateValidator:
    """Utility class for validating and fixing Django templates"""
    
    @staticmethod
    def extract_blocks(content: str) -> Dict[str, str]:
        """Extract all template blocks and their content"""
        blocks = {}
        block_pattern = r'{%\s*block\s+(\w+)\s*%}(.*?){%\s*endblock\s*%}'
        matches = re.finditer(block_pattern, content, re.DOTALL)
        for match in matches:
            block_name = match.group(1)
            block_content = match.group(2).strip()
            blocks[block_name] = block_content
        return blocks

    @staticmethod
    def extract_includes(content: str) -> Set[str]:
        """Extract all included template paths"""
        include_pattern = r'{%\s*include\s+[\'"]([^\'"]+)[\'"]'
        return set(re.findall(include_pattern, content))

    @staticmethod
    def extract_static_files(content: str) -> Set[str]:
        """Extract all static file references"""
        static_pattern = r'{%\s*static\s+[\'"]([^\'"]+)[\'"]'
        return set(re.findall(static_pattern, content))

    @staticmethod
    def fix_template_syntax(content: str) -> str:
        """Fix common template syntax issues"""
        fixes = [
            # Fix spacing in tags
            (r'{%\s*(\w+)\s*%}', r'{% \1 %}'),
            (r'{{\s*(\w+)\s*}}', r'{{ \1 }}'),
            
            # Fix URL tags
            (r'{%\s*url\s+(\w+)\s*%}', r"{% url '\1' %}"),
            
            # Fix if/for block syntax
            (r'{%\s*if\s+(.+?)\s*%}', r'{% if \1 %}'),
            (r'{%\s*for\s+(.+?)\s*%}', r'{% for \1 %}'),
            
            # Fix endblock tags
            (r'{%\s*endblock\s+\w+\s*%}', r'{% endblock %}'),
            
            # Fix static tags
            (r'{%\s*static\s+([\'"])([^\'"]+)\1\s*%}', r'{% static "\2" %}'),
            
            # Fix include tags
            (r'{%\s*include\s+([\'"])([^\'"]+)\1\s*%}', r'{% include "\2" %}'),
            
            # Fix extends tags
            (r'{%\s*extends\s+([\'"])([^\'"]+)\1\s*%}', r'{% extends "\2" %}'),
        ]
        
        fixed = content
        for pattern, replacement in fixes:
            fixed = re.sub(pattern, replacement, fixed)
        return fixed

    @staticmethod
    def validate_template(content: str) -> Tuple[bool, Optional[str]]:
        """Validate template syntax and return (is_valid, error_message)"""
        try:
            Template(content)
            return True, None
        except TemplateSyntaxError as e:
            return False, str(e)

    @staticmethod
    def wrap_content(content: str, base_template: str = 'base.html') -> str:
        """Wrap template content with proper extends and block tags"""
        # Extract existing blocks
        blocks = TemplateValidator.extract_blocks(content)
        
        # Remove existing extends and load tags
        content = re.sub(r'{%\s*extends\s+[\'"].*?[\'"]\s*%}\n?', '', content)
        content = re.sub(r'{%\s*load\s+.*?%}\n?', '', content)
        
        # Build the wrapped template
        wrapped = [
            f'{{% extends "{base_template}" %}}',
            '{% load static %}',
        ]
        
        # Add blocks
        if blocks:
            # If blocks exist, preserve them
            for block_name, block_content in blocks.items():
                wrapped.append(f'{{% block {block_name} %}}\n{block_content}\n{{% endblock %}}')
        else:
            # If no blocks, wrap everything in content block
            wrapped.append('{% block content %}\n' + content.strip() + '\n{% endblock %}')
        
        return '\n'.join(wrapped)

    @staticmethod
    def clean_template(content: str) -> str:
        """Clean template content by removing unwanted tags and normalizing whitespace"""
        # Remove extends tags
        content = re.sub(r'{%\s*extends\s+[\'"]\w+\.html[\'"]\s*%}\n?', '', content)
        
        # Remove load static tags
        content = re.sub(r'{%\s*load\s+static\s*%}\n?', '', content)
        
        # Remove block tags but keep content
        content = re.sub(r'{%\s*block\s+\w+\s*%}\n?', '', content)
        content = re.sub(r'{%\s*endblock\s*%}\n?', '', content)
        
        # Normalize whitespace
        lines = [line.strip() for line in content.split('\n')]
        return '\n'.join(line for line in lines if line)

class TemplateGenerator:
    """Utility class for generating Django templates"""
    
    @staticmethod
    def generate_list_template(model_name: str, fields: List[str]) -> str:
        """Generate a list view template for a model"""
        template = f"""
<div class="container mt-4">
    <h1>{model_name} List</h1>
    
    <div class="table-responsive">
        <table class="table table-striped">
            <thead>
                <tr>
                    {''.join(f'<th>{field}</th>' for field in fields)}
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {{% for object in object_list %}}
                <tr>
                    {''.join(f'<td>{{{{ object.{field} }}}}</td>' for field in fields)}
                    <td>
                        <a href="{{% url '{model_name.lower()}_detail' object.pk %}}" class="btn btn-info btn-sm">View</a>
                        <a href="{{% url '{model_name.lower()}_update' object.pk %}}" class="btn btn-warning btn-sm">Edit</a>
                        <a href="{{% url '{model_name.lower()}_delete' object.pk %}}" class="btn btn-danger btn-sm">Delete</a>
                    </td>
                </tr>
                {{% endfor %}}
            </tbody>
        </table>
    </div>
    
    <a href="{{% url '{model_name.lower()}_create' %}}" class="btn btn-primary">Add New {model_name}</a>
</div>
"""
        return template.strip()

    @staticmethod
    def generate_detail_template(model_name: str, fields: List[str]) -> str:
        """Generate a detail view template for a model"""
        template = f"""
<div class="container mt-4">
    <h1>{model_name} Detail</h1>
    
    <div class="card">
        <div class="card-body">
            {''.join(f'''
            <div class="mb-3">
                <strong>{field}:</strong>
                <span>{{{{ object.{field} }}}}</span>
            </div>''' for field in fields)}
        </div>
    </div>
    
    <div class="mt-3">
        <a href="{{% url '{model_name.lower()}_list' %}}" class="btn btn-secondary">Back to List</a>
        <a href="{{% url '{model_name.lower()}_update' object.pk %}}" class="btn btn-warning">Edit</a>
        <a href="{{% url '{model_name.lower()}_delete' object.pk %}}" class="btn btn-danger">Delete</a>
    </div>
</div>
"""
        return template.strip()

    @staticmethod
    def generate_form_template(model_name: str, is_update: bool = False) -> str:
        """Generate a create/update form template for a model"""
        title = f"{'Update' if is_update else 'Create'} {model_name}"
        template = f"""
<div class="container mt-4">
    <h1>{title}</h1>
    
    <form method="post" enctype="multipart/form-data">
        {{% csrf_token %}}
        
        <div class="card">
            <div class="card-body">
                {{{{ form.as_div }}}}
            </div>
        </div>
        
        <div class="mt-3">
            <button type="submit" class="btn btn-primary">Save</button>
            <a href="{{% url '{model_name.lower()}_list' %}}" class="btn btn-secondary">Cancel</a>
        </div>
    </form>
</div>
"""
        return template.strip()

    @staticmethod
    def generate_delete_template(model_name: str) -> str:
        """Generate a delete confirmation template for a model"""
        template = f"""
<div class="container mt-4">
    <h1>Delete {model_name}</h1>
    
    <div class="alert alert-danger">
        <p>Are you sure you want to delete this {model_name.lower()}?</p>
    </div>
    
    <form method="post">
        {{% csrf_token %}}
        <button type="submit" class="btn btn-danger">Confirm Delete</button>
        <a href="{{% url '{model_name.lower()}_list' %}}" class="btn btn-secondary">Cancel</a>
    </form>
</div>
"""
        return template.strip()