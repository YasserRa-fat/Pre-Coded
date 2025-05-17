from django.db import models
from django.contrib.auth.models import User
from PIL import Image
import datetime

class Post(models.Model):
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
    										         class Meta:                                                                          ordering = ["-created_at"]                                                                class AnalyticsGraphDataManager(models.Manager):                                             def get_interactions_in_past_10days(self, user):                                                today = datetime.date today() - datetime .timedelta (days=10)                                comments = self .filter (post__user__id__exact=user .id , created__gte=today )              return comments .annotate (counts=Count('id')) .order\_by('-created')[:10]             class AnalyticsGraphData(models .Model ):              post = models .ForeignKey (Post , on\_delete=models .CASCADE )              user = models .ForeignKey (User , on\_delete=models .CASCADE )              objects = AnalyticsGraphDataManager ()              class Meta :               ordering \['-created'\]               def __str__(self):               return 'Analytics Graph Data for Post {} by User {}'.format (self .post\_id , self .user\_id )          class Meta:             ordering \['-created\_at'\]         