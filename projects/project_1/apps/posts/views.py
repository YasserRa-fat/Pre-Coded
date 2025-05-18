from django.views.generic import ListView, CreateView, DetailView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from .models import Post

class PostList(ListView):
    model = Post
    context_object_name = 'posts'
    template_name = 'project_1_posts/post_list.html'
    ordering = ['-created_at']

class PostCreate(LoginRequiredMixin, CreateView):
    model = Post
    fields = ['title', 'content', 'image']
    template_name = 'project_1_posts/post_form.html'
    success_url = reverse_lazy('posts:list')

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)

class PostDetail(DetailView):
    model = Post
    template_name = 'project_1_posts/post_detail.html'

class PostUpdate(LoginRequiredMixin, UpdateView):
    model = Post
    fields = ['title', 'content', 'image']
    template_name = 'project_1_posts/post_form.html'

    def get_success_url(self):
        return reverse_lazy('posts:detail', kwargs={'pk': self.object.pk})

class PostDelete(LoginRequiredMixin, DeleteView):
    model = Post
    template_name = 'project_1_posts/post_confirm_delete.html'
    success_url = reverse_lazy('posts:list') 