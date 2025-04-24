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
from .views import (CurrentUserAPIView, RegisterView, parse_model,GenerateModelCodeAPIView
, SaveModelFileAPIView,ProjectListCreateAPIView, ProjectDetailAPIView, ModelFileDetailAPIView, 
AppListCreateAPIView, parse_viewfile, SaveViewFileAPIView,ViewFileDetailAPIView, ViewFileListAPIView, GenerateModelSummaryAPIView
, FormFileDetailAPIView, SaveFormFileAPIView, parse_formfile,FormFileListAPIView,SettingsFileDetailAPIView,URLFileDetailAPIView,ProjectFileDetailAPIView,
AppFileViewSet,AppDetailAPIView,  ProjectURLFileListCreateAPIView,
    ProjectURLFileDetailAPIView,
    AppURLFileListCreateAPIView,
    AppURLFileDetailAPIView,AppAppFileListCreateAPIView, AppAppFileDetailAPIView,SaveFormFileContentAPIView,SaveViewFileCodeOnlyAPIView
    ,ProjectMediaFileDetailAPIView,ProjectMediaFileListCreateAPIView
    ,ProjectStaticFileDetailAPIView,ProjectStaticFileListCreateAPIView,AppTemplateFileDetailAPIView,AppTemplateFileListCreateAPIView,
    ProjectTemplateFileDetailAPIView,ProjectTemplateFileListCreateAPIView, RunProjectAPIView

)
appfile_list = AppFileViewSet.as_view({'get': 'list', 'post': 'create'})
appfile_detail = AppFileViewSet.as_view({'get': 'retrieve', 'put': 'update', 'delete': 'destroy'})

urlpatterns = [
       path('register/', RegisterView.as_view(), name='register'),
        path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('current_user/', CurrentUserAPIView.as_view(), name='current_user'),
    path('parse-model/', parse_model, name='parse_model'),
    path('generate-model-code/', GenerateModelCodeAPIView.as_view(), name='generate-model-code'),
        path('save-model-file/', SaveModelFileAPIView.as_view(), name='modelfile-create'),

    path('save-model-file/<int:pk>/', SaveModelFileAPIView.as_view(), name='modelfile-update'),
        path('projects/', ProjectListCreateAPIView.as_view(), name='project-list-create'),
    path('projects/<int:pk>/', ProjectDetailAPIView.as_view(), name='project-detail'),
        path('model-files/<int:pk>/', ModelFileDetailAPIView.as_view(), name='model-file-detail'),
        path('apps/', AppListCreateAPIView.as_view(), name='app-list-create'),
    path('model-file/', ModelFileDetailAPIView.as_view(), name='model-file-detail'),
    path('parse-viewfile/', parse_viewfile, name='parse-viewfile'),

  path('save-viewfile/', SaveViewFileAPIView.as_view(), name='save-viewfile'),
    path('viewfile/<int:pk>/', ViewFileDetailAPIView.as_view(), name='viewfile-detail'),
    path('settings-files/<int:pk>/', SettingsFileDetailAPIView.as_view(), name='settingsfile-detail'),
    path('url-files/<int:pk>/',      URLFileDetailAPIView.as_view(),     name='urlfile-detail'),
    path('project-files/<int:pk>/',  ProjectFileDetailAPIView.as_view(),  name='projectfile-detail'),
    path('viewfiles/', ViewFileListAPIView.as_view(), name='viewfile-list'),
        path('generate-model-summary/', GenerateModelSummaryAPIView.as_view(), name='generate_model_summary'),
         path('formfile/<int:pk>/', FormFileDetailAPIView.as_view(), name='formfile-detail'),
    path('save-formfile/', SaveFormFileAPIView.as_view(), name='save-formfile'),
    path('parse-formfile/', parse_formfile, name='parse-formfile'),
        path('formfile/', FormFileListAPIView.as_view(), name='formfile-list'),
path('app-files/<int:pk>/', appfile_detail, name='appfile-detail'),
path('app-files/', appfile_list, name='appfile-list'),
path('apps/<int:pk>/',AppDetailAPIView.as_view()),
path(
        'projects/<int:project_pk>/url-files/',
        ProjectURLFileListCreateAPIView.as_view(),
        name='project-urlfile-list'
    ),
    path(
        'projects/<int:project_pk>/url-files/<int:pk>/',
        ProjectURLFileDetailAPIView.as_view(),
        name='project-urlfile-detail'
    ),

    # app‑level URLFiles
    path(
        'apps/<int:app_pk>/url-files/',
        AppURLFileListCreateAPIView.as_view(),
        name='app-urlfile-list'
    ),
    path('apps/<int:app_pk>/url-files/<int:pk>/', AppURLFileDetailAPIView.as_view(), name='app-urlfile-detail'),

  path(
        'apps/<int:app_pk>/app-files/',
        AppAppFileListCreateAPIView.as_view(),
        name='app-appfile-list'
    ),

    # GET/PUT/DELETE → /api/apps/<app_pk>/app-files/<pk>/
    path(
        'apps/<int:app_pk>/app-files/<int:pk>/',
        AppAppFileDetailAPIView.as_view(),
        name='app-appfile-detail'
    ),
    path('save-formfile-content/',SaveFormFileContentAPIView.as_view()),
        path('save-code-only/<int:pk>/', SaveViewFileCodeOnlyAPIView.as_view(), name='save-code-only'),
# Project‐level template/static/media
path('projects/<int:project_pk>/template-files/',    ProjectTemplateFileListCreateAPIView.as_view(), name='project-templatefile-list'),
path('projects/<int:project_pk>/template-files/<int:pk>/', ProjectTemplateFileDetailAPIView.as_view(), name='project-templatefile-detail'),

path('projects/<int:project_pk>/static-files/',    ProjectStaticFileListCreateAPIView.as_view(), name='project-staticfile-list'),
path('projects/<int:project_pk>/static-files/<int:pk>/', ProjectStaticFileDetailAPIView.as_view(), name='project-staticfile-detail'),

path('projects/<int:project_pk>/media-files/',    ProjectMediaFileListCreateAPIView.as_view(), name='project-mediafile-list'),
path('projects/<int:project_pk>/media-files/<int:pk>/', ProjectMediaFileDetailAPIView.as_view(), name='project-mediafile-detail'),

# App‐level template/static/media
path('apps/<int:app_pk>/template-files/',    AppTemplateFileListCreateAPIView.as_view(), name='app-templatefile-list'),
path('apps/<int:app_pk>/template-files/<int:pk>/', AppTemplateFileDetailAPIView.as_view(), name='app-templatefile-detail'),
    path('projects/<int:project_pk>/run/', RunProjectAPIView.as_view(), name='run-project'),


]
