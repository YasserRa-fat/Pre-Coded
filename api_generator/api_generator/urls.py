import ast
import types
import builtins
import importlib
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from rest_framework.routers import DefaultRouter
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from create_api.models import URLFile
from create_api.views import (
    CurrentUserAPIView,
    GenerateAPIView,
    AvailableModelsAPIView,
    upload_files,
    GenerateModelCodeAPIView,
    UserModelViewSet,
    PreviewRunAPIView
)
from django.urls import re_path  # or path with converters
from core.views import serve_db_static, serve_db_media,serve_drf_static
def sanitize_content(content):
    return content.replace('\xa0', ' ')  # Replace non-breaking spaces

urlpatterns = []

# 1) base on-disk urlpatterns
if settings.ROOT_URLCONF and settings.ROOT_URLCONF != __name__:
    try:
        disk = importlib.import_module(settings.ROOT_URLCONF)
        urlpatterns = list(getattr(disk, "urlpatterns", []))
    except ImportError:
        pass

# 2) admin & fixed API endpoints
urlpatterns += [
    path("admin/", admin.site.urls),
    path("api/", include("create_api.urls")),
    path("generate-api/", GenerateAPIView.as_view(), name="generate-api"),
    path("available-models/", AvailableModelsAPIView.as_view(), name="available-models"),
    path("upload-files/", upload_files, name="upload_files"),
     # 1) DB‐backed static first
    re_path(r'^static/(?P<path>.*)$', serve_db_static, name='db_static'),
       # 1) DRF browsable‐API assets from disk
    re_path(r'^static/rest_framework/(?P<path>.*)$', serve_drf_static),

    # 2) DB‐backed static after that
    re_path(r'^static/(?P<path>.*)$', serve_db_static, name='db_static'),
    # 2) DB‐backed media next
    re_path(r'^media/(?P<path>.*)$', serve_db_media, name='db_media'),
]

# 3) project-level URLFiles (with AST)
for urlfile in URLFile.objects.filter(app__isnull=True):
    pid = urlfile.project.id
    module_tag = f"project_{pid}"
    namespace = module_tag
    raw_code = sanitize_content(urlfile.content)

    app_names = [app.name for app in urlfile.project.apps.all()]
    module_prefix = f"projects.{module_tag}.apps"

    try:
        tree = ast.parse(raw_code)

        class URLTransformer(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                if node.module:
                    root = node.module.split(".", 1)[0]
                    if root in app_names:
                        node.module = f"{module_prefix}.{node.module}"
                return node

            def visit_Call(self, node):
                if isinstance(node.func, ast.Name) and node.func.id == "include":
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        modstr = node.args[0].value
                        root = modstr.split(".", 1)[0]
                        if root in app_names:
                            node.args[0].value = f"{module_prefix}.{modstr}"
                return self.generic_visit(node)

        tree = URLTransformer().visit(tree)
        ast.fix_missing_locations(tree)
        compiled = compile(tree, filename=f"<project_{pid}_urls>", mode="exec")

        # Custom import to redirect local app modules
        real_import = builtins.__import__
        def db_import(name, globals=None, locals=None, fromlist=(), level=0):
            root = name.split(".", 1)[0]
            if root in app_names:
                name = f"{module_prefix}.{name}"
            return real_import(name, globals, locals, fromlist, level)

        exec_globals = {
            "__name__": f"projects.{module_tag}",
            "__builtins__": {**builtins.__dict__, "__import__": db_import},
        }

        exec(compiled, exec_globals)

        if "urlpatterns" in exec_globals:
            urlpatterns.append(
                path(f"projects/{pid}/", include(exec_globals["urlpatterns"]))
            )
    except Exception as e:
            print(f"❌ Failed loading project {pid}: {e}")


# 4) app-level URLFiles
for urlfile in URLFile.objects.exclude(app__isnull=True):
    pid = urlfile.project.id
    module_tag = f"project_{pid}"
    appname = urlfile.app.name
    modstr = f"projects.{module_tag}.apps.{appname}.urls"
    try:
        importlib.import_module(modstr)
        urlpatterns.append(
               path(
        f"projects/{pid}/{appname}/",
        include(modstr),
    )
        )
        # print(f"✅ Added app-level URL patterns for project {pid}, app {appname}")
    except ImportError:
        print(f"❌ Failed to import app-level module: {modstr}")
        continue

# 5) DRF router
router = DefaultRouter()
router.register(r"usermodels", UserModelViewSet)
urlpatterns.append(path("", include(router.urls)))

# 6) Dynamic run-project route
class RunProjectAPIView(APIView):
    def post(self, request, project_pk):
        full_url = request.build_absolute_uri(f"/projects/{project_pk}/")
        return Response({'url': full_url}, status=status.HTTP_200_OK)

urlpatterns.append(
    path('projects/<int:project_id>/run/', RunProjectAPIView.as_view(), name='run-project'),
)
urlpatterns.append(
    path('projects/<int:project_id>/preview/run/',
         PreviewRunAPIView.as_view(), name='preview-run'),
)
# urlpatterns.append(
#     path(
#         f"projects/{pid}/",
#         include((exec_globals["urlpatterns"], namespace)),
#     )
# )

# Debug output
# print("✅ Final URL patterns:")
# for pattern in urlpatterns:
#     print(pattern)

# Optional: show key URLFile objects
# users_urlfile = URLFile.objects.filter(project_id=1, app__name='users', path='users/urls.py')
# posts_urlfile = URLFile.objects.filter(project_id=1, app__name='posts', path='posts/urls.py')
# print(users_urlfile, posts_urlfile)
