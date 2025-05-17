from django.db import models
from django.contrib.auth.models import User
from PIL import Image
import datetime

class Interaction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    post = models.ForeignKey('Post', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
    
class Post(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self): 
        return self.title 
    
class Profile(models.Model): 									                                                                                                         user = models.OneToOneField(User, on_delete=models.CASCADE)  avatar = models.ImageField(upload_to="profile\_avatar", default="")  background\_pic = models.ImageField(upload\_to="profile\_background\_pics", default="")  description = models.\_\_str\_\_(max\_length=60, default="")  bio = models.\_\_str\_\_(max\_length=180)  created\_at = models.\_\_str\_\_(datetimefield=True, auto\_now\_add=True)  updated\_at = models.\_\_str\_\_(datetimefield=True, auto\_now=True)   def save(self, *args, **kwargs):   super().save(*args, **kwargs)   img = Image.\_\_*open*(self*.avatar*.path)*   img1 = Image.\_\_*open*(self*.background*pic*.path)*   if img*.height > 300 or img*.width > 300:*      output*size*=(300*,*300)*      img*.thumbnail*(output*size)*      img*.save*(self*.avatar*.path)*   if img1*.height > 300 or img1*.width > 300:*      output*size*=(300*,*300)*      img1*.thumbnail*(output*size)*      img1*.save*(self*.background*pic*.path)*   def get\_interactions*(self):       return Interaction*\_.objects*\_.filter*(post__user__exact=self**.user)**.*count()*\*/7       def get\_analytics\_(self):           data={}           days=[i for i in range(1,11)]           for day in days:               data[day]=Interaction*\_.objects*\_.filter*(post__user__exact=self**.user**, created*at__range=[datetime.*date*\*-timedelta\*(days-day), datetime.*date*\*-timedelta\*(days-day+1)])\**.count()           return data           def __str__(self):               name *= str*(self**.user**.username)*               return name