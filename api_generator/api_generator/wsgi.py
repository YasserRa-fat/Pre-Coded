"""
WSGI config for api_generator project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""


from django.core.wsgi import get_wsgi_application

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api_generator.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django
django.setup()

from core.db_importer import install as install_db_finder
install_db_finder()

application = get_wsgi_application()