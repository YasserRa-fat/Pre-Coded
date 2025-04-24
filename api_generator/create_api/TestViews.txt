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

# from django.contrib.auth.mixins import LoginRequiredMixin


# Create your views here.
class PostList(ListView):
    model = Post
    context_object_name = "posts"
    template_name = "feed.html"


class PostDetail(DetailView):
    model = Post
    context_object_name = "post"
    template_name = "post_detail.html"


class CommentDetail(DetailView):
    model = Comment
    context_object_name = "comment"
    template_name = "post_detail.html"


class UpdateComment(UpdateView):
    model = Comment
    fields = ["content"]
    template_name = "comment_create.html"
    success_url = reverse_lazy("feed")

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.post_id = self.kwargs["pk"]
        return super().form_valid(form)

    def get_success_url(self):
        messages.info(self.request, "Login Successful")
        return reverse_lazy("feed")


class CreateComment(CreateView):
    model = Comment
    form_class = CommentForm
    template_name = "comment_create.html"
    success_url = reverse_lazy("feed")

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.post_id = self.kwargs["pk"]
        return super().form_valid(form)

    def get_success_url(self):
        messages.info(self.request, "Login Successful")
        return reverse_lazy("feed")


class CommentDelete(DeleteView):
    model = Comment
    template_name = "post_detail.html"
    success_url = reverse_lazy("feed")


@login_required
def post_create(request):
    if request.method == "POST":
        form = CRUDFORM(request.POST, request.FILES)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = request.user
            profile.save()
            return redirect("feed")
        else:
            print(form.errors)
            return HttpResponse(form.errors)
    else:
        form = CRUDFORM
        return render(request, "post_create.html", {"form": form})


# @login_required
# def add_comment(request):
#     if request.method == "POST":
#         form = CommentForm(request.POST, request.FILES)
#         if form.is_valid():
#             comment = form.save(commit=False)
#             comment.user = request.user
#             comment.save()
#             return redirect("feed")


#         else:
#             print(form.errors)
#             return HttpResponse(form.errors)
#     else:
#         form = CommentForm
#         return render(request, "comment_create.html", {"form": form})


# class PostCreate(CreateView):
#     model = Post
#     form_class = CRUDFORM
#     template_name = "post_create.html"
#     success_url = reverse_lazy("feed")

#     def form_valid(self, form):
#         form.instance.user = self.request.user
#         return super(PostCreate, self).form_valid(form)


class PostUpdate(UpdateView):
    model = Post
    form_class = CRUDFORM
    template_name = "post_create.html"
    success_url = reverse_lazy("feed")

    def form_valid(self, form):
        return super(PostUpdate, self).form_valid(form)


class PostDelete(DeleteView):
    model = Post
    template_name = "post_detail.html"
    success_url = reverse_lazy("feed")


# def post_detail(request, slug):
#     template_name = "post_detail.html"
#     post = get_object_or_404(Post, slug=slug)
#     comments = post.comments.filter(active=True)
#     new_comment = None  # Comment posted
#     if request.method == "POST":
#         comment_form = CommentForm(data=request.POST)
#         if comment_form.is_valid():
#             # Create Comment object but don't save to database yet
#             new_comment = comment_form.save(commit=False)
#             # Assign the current post to the comment
#             new_comment.post = post
#             # Save the comment to the database
#             new_comment.save()
#     else:
#         comment_form = CommentForm()
#     return render(
#         request,
#         template_name,
#         {
#             "post": post,
#             "comments": comments,
#             "new_comment": new_comment,
#             "comment_form": comment_form,
#         },
#     )
