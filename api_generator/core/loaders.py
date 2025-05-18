from django.template.loaders.base import Loader
from django.template import Origin, TemplateDoesNotExist
from create_api.models import TemplateFile, AIChangeRequest
import logging
import json
import threading
from core.thread_local import thread_local
import re

logger = logging.getLogger(__name__)

class DatabaseLoader(Loader):
    is_usable = True

    def get_template_sources(self, template_name):
        """Get template source with proper error handling"""
        try:
            # First try exact path match
            tf = TemplateFile.objects.filter(path=template_name).first()
            
            if not tf:
                # Try with templates/ prefix if not found
                prefixed_path = f"templates/{template_name}"
                tf = TemplateFile.objects.filter(path=prefixed_path).first()
            
            if tf:
                yield Origin(
                    name=f"db://{template_name}",
                    template_name=template_name,
                    loader=self
                )
            else:
                logger.warning(f"Template not found in database: {template_name}")
                return
                
        except Exception as e:
            logger.error(f"Error loading template {template_name}: {str(e)}")
            return

    def get_contents(self, origin):
        """Get template contents with preview handling and validation"""
        preview_mode = getattr(thread_local, 'preview_mode', None)
        preview_diff = getattr(thread_local, 'preview_diff', None)
        logger.debug(f"DatabaseLoader.get_contents: origin={origin.template_name}, "
                     f"preview_mode={preview_mode}, has_preview_diff={preview_diff is not None}")
        
        try:
            # Handle preview mode
            if preview_mode == "after" and preview_diff:
                diff_key = f"templates/{origin.template_name}"
                patched = preview_diff.get(diff_key)
                if patched:
                    logger.debug(f"Using after-preview diff for {origin.template_name}")
                    # Validate template syntax
                    self.validate_template(patched, origin.template_name)
                    return patched

            # Try exact path match first
            tf = TemplateFile.objects.filter(path=origin.template_name).first()
            
            if not tf:
                # Try with templates/ prefix if not found
                prefixed_path = f"templates/{origin.template_name}"
                tf = TemplateFile.objects.filter(path=prefixed_path).first()
            
            if tf:
                content = tf.content or ""
                # Validate template syntax
                self.validate_template(content, origin.template_name)
                return content
            else:
                logger.error(f"Template not found: {origin.template_name}")
                raise TemplateDoesNotExist(f"Template {origin.template_name} does not exist")

        except TemplateFile.DoesNotExist:
            logger.error(f"Template not found: {origin.template_name}")
            raise TemplateDoesNotExist(f"Template {origin.template_name} does not exist")
        except Exception as e:
            logger.error(f"Error loading template {origin.template_name}: {str(e)}")
            raise TemplateDoesNotExist(f"Error loading template {origin.template_name}: {str(e)}")

    def validate_template(self, content, template_name):
        """Validate template syntax"""
        from django.template import Template, TemplateSyntaxError
        try:
            Template(content)
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error in {template_name}: {str(e)}")
            # Try to fix common syntax errors
            fixed_content = self.fix_template_syntax(content)
            try:
                Template(fixed_content)
                logger.info(f"Fixed template syntax for {template_name}")
                return fixed_content
            except TemplateSyntaxError as e:
                logger.error(f"Could not fix template syntax for {template_name}: {str(e)}")
                raise
        return content

    def fix_template_syntax(self, content):
        """Fix common template syntax errors"""
        # Fix unclosed tags
        tag_pairs = {
            '{% if': '{% endif %}',
            '{% for': '{% endfor %}',
            '{% block': '{% endblock %}',
            '{% with': '{% endwith %}'
        }
        
        lines = content.split('\n')
        stack = []
        fixed_lines = []
        
        for line in lines:
            fixed_lines.append(line)
            for opening, closing in tag_pairs.items():
                if opening in line:
                    stack.append(closing)
                elif any(closing in line for closing in tag_pairs.values()):
                    if stack:
                        stack.pop()
                        
        # Add missing closing tags
        while stack:
            fixed_lines.append(stack.pop())
            
        # Fix variable syntax
        content = '\n'.join(fixed_lines)
        content = re.sub(r'{{(\w+)}}', r'{{ \1 }}', content)  # Add spaces inside {{ }}
        content = re.sub(r'{%(\w+)%}', r'{% \1 %}', content)  # Add spaces inside {% %}
        
        return content
