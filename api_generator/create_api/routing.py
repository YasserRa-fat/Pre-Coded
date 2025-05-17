# create_api/routing.py

from django.urls import re_path
from create_api.consumers import ProjectConsumer  # or whatever your consumer is called

websocket_urlpatterns = [
    re_path(r"^ws/projects/(?P<project_id>\d+)/ai/$", ProjectConsumer.as_asgi()),
]
