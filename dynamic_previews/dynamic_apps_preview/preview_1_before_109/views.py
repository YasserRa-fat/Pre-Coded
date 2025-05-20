from typing import Any
from django.shortcuts import render, HttpResponse
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.contrib import messages
from django.views.generic import (
    TemplateView,
    FormView,
    UpdateView,
    CreateView,
    RedirectView,
    View,
)
from django.contrib.auth.mixins import LoginRequiredMixin
from .forms import RegisterForm
from django.contrib.auth import login
from django.shortcuts import redirect
from .models import Profile
from .forms import ProfileForm
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required

# Create your views here.
# def index(request):
#     return render(request, "index.html")


# class Home(TemplateView):
#     template_name = "profile/home.html"


class ProfileUpdate(LoginRequiredMixin, UpdateView):
    model = Profile
    template_name = "profile/profile_update.html"
    form_class = ProfileForm

    def get_success_url(self):
        messages.info(self.request, "update Successful")
        return reverse_lazy("home")


class Profile(LoginRequiredMixin, TemplateView):
    template_name = "profile/profile.html"
    model = Profile


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def profile_details(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = request.user
            profile.save()
            return redirect("home")
        else:
            print(form.errors)
            return HttpResponse(form.errors)
    else:
        form = ProfileForm
        return render(request, "profile/profile_update.html", {"form": form})


class Login(LoginView):
    redirect_authenticated_user = True

    def get_success_url(self):
        messages.info(self.request, "Login Successful")
        return reverse_lazy("home")

    def form_invalid(self, form):
        messages.error(self.request, "Invalid Login")
        return super().form_invalid(form)


class RegisterView(FormView):
    form_class = RegisterForm
    redirect_authenticated_user = True
    success_url = reverse_lazy("details")
    template_name = "registration/register.html"

    def dispatch(self, request, *args: Any, **kwargs: Any):
        if request.user.is_authenticated:
            return redirect("home")
        return super(RegisterView, self).dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        if user:
            login(self.request, user)
        return super(RegisterView, self).form_valid(form)