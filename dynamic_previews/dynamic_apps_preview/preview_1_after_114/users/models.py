from django.db import models
from django.contrib.auth.models import User
from PIL import Image
import datetime

class Interaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey('Post', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Post(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):  # __unicode__ on Python 2 
        return self.title  # or something more complex if needed, like self.title + ' - ' + self.user.__str__()  # for example: "My first post - John Doe" instead of just "My first post"  # noqa: E501,W505  # noqa: E501,W505  # noqa: E501,W505  # noqa: E501,W505  # noqa: E501,W505  # noqa: E501,W505  # noqa: E266,E302,E326,E416,W293,W391