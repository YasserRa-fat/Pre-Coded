from django.urls import path
from .views import (
    PostDelete,
    post_create,
    PostUpdate,
    PostDetail,
    CreateComment,
    UpdateComment,
    CommentDelete,
)

urlpatterns = [
    path("create/", post_create, name="post_create"),
    path("comment/<int:pk>", CreateComment.as_view(), name="add_comment"),
    path("update_comment/<int:pk>", UpdateComment.as_view(), name="update_comment"),
    path("update/<str:pk>", PostUpdate.as_view(), name="post_update"),
    path("delete/<str:pk>", PostDelete.as_view(), name="delete"),
    path("comment_delete/<str:pk>", CommentDelete.as_view(), name="delete_comment"),
    path("post/<int:pk>", PostDetail.as_view(), name="detail"),
]