from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import Profile


class RegisterForm(UserCreationForm):
    email = forms.EmailField(max_length=254)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]


class ProfileForm(forms.ModelForm):
    description = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control"})
    )
    bio = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    avatar = forms.ImageField(widget=forms.FileInput(attrs={"class": "form-control"}))
    background_pic = forms.ImageField(
        widget=forms.FileInput(attrs={"class": "form-control"})
    )

    class Meta:
        model = Profile
        fields = ["description", "bio", "avatar", "background_pic"]
