"""
URL configuration for api_generator project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path,include

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from create_api.views import CurrentUserAPIView, GenerateAPIView,AvailableModelsAPIView
from rest_framework.routers import DefaultRouter
from create_api.views import UserModelViewSet

router = DefaultRouter()
router.register(r'usermodels', UserModelViewSet)
urlpatterns = [
   
    path('api/', include('create_api.urls')),
    path('generate-api/', GenerateAPIView.as_view(), name='generate-api'),
    path('available-models/', AvailableModelsAPIView.as_view(), name='available-models'),
    path('', include(router.urls)),



]
