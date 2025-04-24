from django.db import models
from django.contrib.auth.models import User
from PIL import Image

# Generated models.py file

class Post(models.Model):
    title = models.CharField(max_length=255)
    post_type = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    image = models.ImageField(upload_to="posts_images", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    comment = models.ForeignKey('Comment', on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        img = Image.open(self.image.path)
        if img.height > 400 or img.width > 400:
            output_size = (400, 400)
            img.thumbnail(output_size)
            img.save(self.image.path)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['-created_at']

class Comment(models.Model):
    content = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created',)

    def __str__(self):
        return 'Comment by {}'.format(self.content)