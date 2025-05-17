from django.db import models
from django.contrib.auth.models import User
from PIL import Image
import datetime as dt

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
     class Meta:         ordering = ["-created_at"]         def last_10days_comments(self):             today = dt.date.today()             startdate = today - dt.timedelta(days=10)             commentslist = Comment \ .objects \ .filter(post__id__exact=self \ .id)\ .filter(created__range=[startdate, today])\ .values('user')\ .annotate(counts=models\ .Count('user'))\ .order\_by()             return commentslist          class AnalyticsGraphData:              def __init__(self):                  self.\_\_data={}              def add\_data\_point\_to\_graph\_data (self, date , data\_point ):                  if date in self.\_\_data:                      self.\_\_data[date].append (data\_point )                  else:                      self.\_\_data[date] = [ data\_point ]              def get\_graph\_data (self ):                  return self.\_\__data          analyticsgraphdataforpost=\ AnalyticsGraphData()          for comment in self \ .last\_10days\_comments():              analyticsgraphdataforpost\_.add\_data\_point\_to\_graph\_data (comment \['created'\]\_.date(), comment \['counts'\])          return analyticsgraphdataforpost\_.get\_graph\_data()          @property          def analyticsgraph (self ):              return self \ .analyticsgraphdataself\_.get('analytics')