import logging
from typing import Dict, Any, Optional
from django.template.loader import render_to_string
from django.conf import settings
from pathlib import Path
from ..models import TemplateFile

logger = logging.getLogger(__name__)

class TemplateService:
    def __init__(self, project):
        self.project = project
        
    async def generate_template(
        self,
        template_type: str,
        template_name: str,
        defaults: Dict[str, Any]
    ) -> Optional[str]:
        """Generate a template based on type and configuration"""
        try:
            # Get base template configuration
            base_config = defaults.get('base', {})
            type_config = defaults.get(template_type, {})
            
            # Merge configurations
            config = {**base_config, **type_config}
            
            # Get template context
            context = self.get_template_context(template_type, template_name, config)
            
            # Try different template paths
            template_paths = [
                f"base/base_{template_type}.html",
                f"templates/base/base_{template_type}.html",
                f"base_{template_type}.html",
                f"{template_type}.html"
            ]
            
            template = None
            for path in template_paths:
                try:
                    template = TemplateFile.objects.get(
                        project=self.project,
                        path=path
                    )
                    if template and template.content:
                        break
                except TemplateFile.DoesNotExist:
                    continue
                    
            if not template or not template.content:
                logger.error(f"No valid template found for type {template_type}")
                # Return minimal fallback template
                fallback_content = self.get_fallback_template(template_type, template_name)
                from django.template import Template, Context
                template = Template(fallback_content)
                return template.render(Context(context))
            
            # Render template with context
            from django.template import Template, Context
            template = Template(template.content)
            rendered = template.render(Context(context))
            
            return rendered
            
        except Exception as e:
            logger.error(f"Error generating template: {str(e)}")
            return None
            
    def get_template_context(
        self,
        template_type: str,
        template_name: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get context for template rendering"""
        context = {
            'project_name': self.project.name,
            'template_name': template_name,
            'css_framework': config.get('css_framework', 'bootstrap'),
            'css_version': config.get('css_version', '5.1.3'),
            'meta_tags': config.get('meta_tags', ['charset', 'viewport']),
            'required_blocks': config.get('required_blocks', ['title', 'content']),
        }
        
        # Add type-specific context
        if template_type == 'list':
            context.update({
                'pagination': config.get('pagination', True),
                'items_per_page': config.get('items_per_page', 10),
                'show_actions': config.get('show_actions', True),
            })
        elif template_type == 'detail':
            context.update({
                'show_navigation': config.get('show_navigation', True),
                'show_timestamps': config.get('show_timestamps', True),
            })
        elif template_type == 'form':
            context.update({
                'method': config.get('method', 'post'),
                'enctype': config.get('enctype', 'multipart/form-data'),
                'show_errors': config.get('show_errors', True),
            })
            
        return context 

    def get_fallback_template(self, template_type: str, template_name: str) -> str:
        """Get a minimal fallback template when the requested one is not found"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{template_name}</title>
        </head>
        <body>
            <div class="container">
                <h1>{template_name}</h1>
                <p>Template type: {template_type}</p>
                <p>This is a fallback template. The original template was not found.</p>
            </div>
        </body>
        </html>
        """ 