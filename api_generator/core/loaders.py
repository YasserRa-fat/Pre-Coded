# core/loaders.py
from django.template.loaders.base import Loader
from django.template import Origin, TemplateDoesNotExist
from create_api.models import TemplateFile

class DatabaseLoader(Loader):
    is_usable = True

    def get_template_sources(self, template_name):
        try:
            tf = TemplateFile.objects.get(path=template_name)
        except TemplateFile.DoesNotExist:
            return
        yield Origin(
            name=f"db://{template_name}",
            template_name=template_name,
            loader=self
        )

    def get_contents(self, origin):
        try:
            return TemplateFile.objects.get(path=origin.template_name).content
        except TemplateFile.DoesNotExist:
            raise TemplateDoesNotExist(origin)
