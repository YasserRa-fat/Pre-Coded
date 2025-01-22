from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class UserModel(models.Model):
    VISIBILITY_CHOICES = [
        ('private', 'Private'),
        ('public', 'Public'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    model_name = models.CharField(max_length=255)
    fields = models.JSONField()  # Store fields as a JSON object
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='private')
    created_at = models.DateTimeField(auto_now_add=True)
    full_code = models.TextField(null=True)
    def __str__(self):
        return self.model_name
