from django.shortcuts import render, get_object_or_404, redirect, HttpResponse
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    DeleteView,
    UpdateView,
)
from .models import Post, Comment
from .forms import CRUDFORM, CommentForm
from django.urls import reverse, reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils.text import slugify
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from datetime import timedelta
import json

# Create your views here.
class PostList(ListView):
    model = Post
    context_object_name = "posts"
    template_name = "feed.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            # Get comments from the last 10 days
            end_date = timezone.now()
            start_date = end_date - timedelta(days=10)
            
            # Get comment counts per day
            comments = Comment.objects.filter(
                post__user=self.request.user,
                created__range=(start_date, end_date)
            ).annotate(
                date=TruncDate('created')
            ).values('date').annotate(
                count=Count('id')
            ).order_by('date')

            # Prepare data for Chart.js
            dates = []
            counts = []
            current_date = start_date.date()
            
            while current_date <= end_date.date():
                dates.append(current_date.strftime('%Y-%m-%d'))
                count = next(
                    (item['count'] for item in comments if item['date'] == current_date),
                    0
                )
                counts.append(count)
                current_date += timedelta(days=1)

            context['comment_labels'] = json.dumps(dates)
            context['comment_data'] = json.dumps(counts)
        
        return context

# ... rest of the existing views ... 