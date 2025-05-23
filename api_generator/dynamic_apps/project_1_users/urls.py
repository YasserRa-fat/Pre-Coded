from django.urls import path
from .views import (
    Profile,
    RegisterView,
    Login,
    ProfileUpdate,
    profile_details,
    logout_view,
)


urlpatterns = [
    # path("", Home.as_view(), name="home"),
    path("home/", Profile.as_view(), name="home"),
    path("login/", Login.as_view(), name="login"),
    path("register/", RegisterView.as_view(), name="register"),
    path("update/<int:pk>", ProfileUpdate.as_view(), name="update"),
    path("logout/", logout_view, name="logout"),
    path("details/", profile_details, name="details"),
]