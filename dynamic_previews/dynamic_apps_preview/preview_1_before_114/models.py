from django.db import models

from django.db import models
from django.contrib.auth.models import User
from PIL import Image
import datetime

# Create your models here.


class Profile(models.Model):
    class Meta:
        app_label = 'project_1'
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    avatar = models.ImageField(upload_to="profile_avatar", default="")
    background_pic = models.ImageField(upload_to="profile_background_pics", default="")
    description = models.CharField(max_length=60, default="")
    bio = models.CharField(max_length=180)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        img = Image.open(self.avatar.path)
        img1 = Image.open(self.background_pic.path)
        if img.height > 300 or img.width > 300:
            output_size = (300, 300)
            img.thumbnail(output_size)
            img.save(self.avatar.path)
        if img1.height > 300 or img.width > 300:
            output_size = (300, 300)
            img1.thumbnail(output_size)
            img1.save(self.background_pic.path)

    def __str__(self):
        name = str(self.user.username)
        return namefrom django.db import models
from django.contrib.auth.models import User
from PIL import Image


# Create your models here.
class Post(models.Model):
    class Meta:
        app_label = 'project_1'
    title = models.CharField(max_length=255)
    post_type = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    image = models.ImageField(upload_to="posts_images", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

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
        ordering = ["-created_at"]


class Comment(models.Model):
    class Meta:
        app_label = 'project_1'
    content = models.TextField()
    post = models.ForeignKey(Post, related_name="comments", on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        ordering = ("-created",)

    def __str__(self):
        return "Comment by {}".format(self.content)