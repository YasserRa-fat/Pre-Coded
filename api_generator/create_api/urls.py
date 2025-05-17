# create_api/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .views import (
    CurrentUserAPIView,
    RegisterView,
    parse_model,
    GenerateModelCodeAPIView,
    SaveModelFileAPIView,
    ProjectListCreateAPIView,
    ProjectDetailAPIView,
    ModelFileDetailAPIView,
    AppListCreateAPIView,
    parse_viewfile,
    SaveViewFileAPIView,
    ViewFileDetailAPIView,
    ViewFileListAPIView,
    GenerateModelSummaryAPIView,
    FormFileDetailAPIView,
    SaveFormFileAPIView,
    parse_formfile,
    FormFileListAPIView,
    SettingsFileDetailAPIView,
    URLFileDetailAPIView,
    ProjectFileDetailAPIView,
    AppFileViewSet,
    AppDetailAPIView,
    ProjectURLFileListCreateAPIView,
    ProjectURLFileDetailAPIView,
    AppURLFileListCreateAPIView,
    AppURLFileDetailAPIView,
    AppAppFileListCreateAPIView,
    AppAppFileDetailAPIView,
    SaveFormFileContentAPIView,
    SaveViewFileCodeOnlyAPIView,
    ProjectMediaFileDetailAPIView,
    ProjectMediaFileListCreateAPIView,
    ProjectStaticFileDetailAPIView,
    ProjectStaticFileListCreateAPIView,
    AppTemplateFileDetailAPIView,
    AppTemplateFileListCreateAPIView,
    ProjectTemplateFileDetailAPIView,
    ProjectTemplateFileListCreateAPIView,
    ModelFileListCreateAPIView,
    RunProjectAPIView,
    AIConversationViewSet, 
     DebugDBAlias, # <— make sure this is imported
     CookieTokenObtainPairView,
     preview_view,
     PreviewOneView,
     ApplyChangesAPIView,
     FullPreviewDiffAPIView,
     PreviewRunAPIView,
)

# router for your AI endpoints
router = DefaultRouter()
router.register(r'ai/conversations', AIConversationViewSet, basename='ai-conv')

appfile_list   = AppFileViewSet.as_view({'get': 'list',   'post':   'create'})
appfile_detail = AppFileViewSet.as_view({'get': 'retrieve','put':    'update','delete':'destroy'})

urlpatterns = [
    # --- auth & user endpoints ---
    path('register/',               RegisterView.as_view(),                    name='register'),
    path('token/',                  CookieTokenObtainPairView.as_view(),            name='token_obtain_pair'),
    path('token/refresh/',          TokenRefreshView.as_view(),               name='token_refresh'),
    path('current_user/',           CurrentUserAPIView.as_view(),             name='current_user'),

    # --- model parsing / codegen ---
    path('parse-model/',            parse_model,                              name='parse_model'),
    path('generate-model-code/',    GenerateModelCodeAPIView.as_view(),       name='generate-model-code'),
    path('save-model-file/',        SaveModelFileAPIView.as_view(),           name='modelfile-create'),
    path('save-model-file/<int:pk>/', SaveModelFileAPIView.as_view(),          name='modelfile-update'),
    path('generate-model-summary/', GenerateModelSummaryAPIView.as_view(),     name='generate_model_summary'),

    # --- project & app CRUD ---
    path('projects/',               ProjectListCreateAPIView.as_view(),       name='project-list-create'),
    path('projects/<int:pk>/',      ProjectDetailAPIView.as_view(),           name='project-detail'),
    path('apps/',                   AppListCreateAPIView.as_view(),           name='app-list-create'),
    path('apps/<int:pk>/',          AppDetailAPIView.as_view()),

    # --- file detail endpoints ---
    path('model-files/<int:pk>/',   ModelFileDetailAPIView.as_view(),         name='model-file-detail'),
    path('viewfiles/',              ViewFileListAPIView.as_view(),            name='viewfile-list'),
    path('viewfile/<int:pk>/',      ViewFileDetailAPIView.as_view(),          name='viewfile-detail'),
    path('save-viewfile/',          SaveViewFileAPIView.as_view(),            name='save-viewfile'),
    path('save-code-only/<int:pk>/',SaveViewFileCodeOnlyAPIView.as_view(),    name='save-code-only'),
        path(
        'projects/<int:project_pk>/apps/<int:app_pk>/app-files/',
        AppAppFileListCreateAPIView.as_view(),
        name='project-app-appfile-list'
    ),
    path(
        'projects/<int:project_pk>/apps/<int:app_pk>/app-files/<int:pk>/',
        AppAppFileDetailAPIView.as_view(),
        name='project-app-appfile-detail'
    ),
    path('formfile/<int:pk>/',      FormFileDetailAPIView.as_view(),          name='formfile-detail'),
    path('formfile/',               FormFileListAPIView.as_view(),            name='formfile-list'),
    path('save-formfile/',          SaveFormFileAPIView.as_view(),            name='save-formfile'),
    path('save-formfile-content/',  SaveFormFileContentAPIView.as_view(),     name='save-formfile-content'),
    path('parse-formfile/',         parse_formfile,                           name='parse-formfile'),
    path('parse-viewfile/',parse_viewfile),
    path('settings-files/<int:pk>/',SettingsFileDetailAPIView.as_view(),       name='settingsfile-detail'),
    path('url-files/<int:pk>/',     URLFileDetailAPIView.as_view(),            name='urlfile-detail'),
    path('project-files/<int:pk>/', ProjectFileDetailAPIView.as_view(),        name='projectfile-detail'),

    path('app-files/',              appfile_list,                             name='appfile-list'),
    path('app-files/<int:pk>/',     appfile_detail,                           name='appfile-detail'),
path('form‑files/',     FormFileListAPIView.as_view(),   name='formfile-list'),
    # --- URLFiles (project & app) ---
    path('projects/<int:project_pk>/url-files/',       ProjectURLFileListCreateAPIView.as_view(), name='project-urlfile-list'),
    path('projects/<int:project_pk>/url-files/<int:pk>/', ProjectURLFileDetailAPIView.as_view(),     name='project-urlfile-detail'),
    path('apps/<int:app_pk>/url-files/',               AppURLFileListCreateAPIView.as_view(),     name='app-urlfile-list'),
    path('apps/<int:app_pk>/url-files/<int:pk>/',      AppURLFileDetailAPIView.as_view(),         name='app-urlfile-detail'),

    # --- static / media / templates ---
    path('projects/<int:project_pk>/static-files/',    ProjectStaticFileListCreateAPIView.as_view(),  name='project-staticfile-list'),
    path('projects/<int:project_pk>/static-files/<int:pk>/', ProjectStaticFileDetailAPIView.as_view(), name='project-staticfile-detail'),
    path('projects/<int:project_pk>/media-files/',     ProjectMediaFileListCreateAPIView.as_view(),   name='project-mediafile-list'),
    path('projects/<int:project_pk>/media-files/<int:pk>/', ProjectMediaFileDetailAPIView.as_view(),   name='project-mediafile-detail'),
    path('projects/<int:project_pk>/template-files/',  ProjectTemplateFileListCreateAPIView.as_view(),name='project-templatefile-list'),
    path('projects/<int:project_pk>/template-files/<int:pk>/', ProjectTemplateFileDetailAPIView.as_view(), name='project-templatefile-detail'),

    path('apps/<int:app_pk>/static-files/',            ProjectStaticFileListCreateAPIView.as_view(),  name='app-staticfile-list'),
    path('apps/<int:app_pk>/static-files/<int:pk>/',   ProjectStaticFileDetailAPIView.as_view(),      name='app-staticfile-detail'),
    path('apps/<int:app_pk>/media-files/',             ProjectMediaFileListCreateAPIView.as_view(),   name='app-mediafile-list'),
    path('apps/<int:app_pk>/media-files/<int:pk>/',    ProjectMediaFileDetailAPIView.as_view(),       name='app-mediafile-detail'),
    path('apps/<int:app_pk>/template-files/',          AppTemplateFileListCreateAPIView.as_view(),    name='app-templatefile-list'),
    path('apps/<int:app_pk>/template-files/<int:pk>/', AppTemplateFileDetailAPIView.as_view(),       name='app-templatefile-detail'),
 path('model-files/',            ModelFileListCreateAPIView.as_view(), name='modelfile-list-create'),
    # --- run project endpoint ---
    path('projects/<int:project_pk>/run/',             RunProjectAPIView.as_view(),                  name='run-project'),
    path('debug-db/', DebugDBAlias.as_view(), name='debug-db'),
path("projects/<int:project_id>/preview/", preview_view, name="preview_project"),
path(
        "projects/<int:project_id>/preview/one/<int:change_id>/",
        PreviewOneView.as_view(),
        name="preview-one",
    ),
path(
        "projects/<int:project_id>/preview/diff/<int:change_id>/",
        FullPreviewDiffAPIView.as_view(),
        name="preview-diff"
    ),
    path(
        "projects/<int:project_id>/apply/<int:change_id>/",
        ApplyChangesAPIView.as_view(),
        name="apply-changes"
    ),
    path('projects/<int:project_id>/preview/run/', PreviewRunAPIView.as_view(), name='preview-run'),
]

# finally wire up our AI router
urlpatterns += router.urls
