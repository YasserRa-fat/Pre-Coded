# create_api/views.py

from django.forms import ValidationError
from django.http import Http404,HttpResponseServerError
from rest_framework import generics, viewsets, status
from django.contrib.auth.models import User
from rest_framework.response import Response
from rest_framework.decorators import action
from core.services.ai_editor import call_ai
from django.db import transaction
from .serializers import (UserSerializer, UserModelSerializer, ModelFileSerializer,
 ProjectSerializer,AppSerializer, ViewFileSerializer,FormFileSerializer, ProjectFileSerializer,SettingsFileSerializer,
 URLFileSerializer,AppFileSerializer, MediaFileSerializer, TemplateFileSerializer, StaticFileSerializer,
     AIConversationSerializer,AIMessageSerializer,AIChangeRequestSerializer,
     AppSerializer,AppFileSerializer,AppFile,AppFileSerializer,AppFileSerializer,
)
from asgiref.sync import sync_to_async
from rest_framework.exceptions import NotFound
from django.shortcuts import get_object_or_404
from rest_framework.parsers import MultiPartParser, FormParser
from django.conf import settings
from django.urls import reverse
from django.shortcuts import render
from django.http import JsonResponse
from django.db import models, connection
from django.db.models import Q
import logging
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied
from django.core.management import call_command
from io import StringIO
from django.apps import apps
from .models import (UserModel, Project, ModelFile, App, ViewFile, FormFile, SettingsFile, StaticFile, 
URLFile, AppFile, CodeFile,MediaFile,ProjectFile,TemplateFile,AIConversation, AIMessage, AIChangeRequest)
from rest_framework.decorators import api_view, permission_classes
import random
from rest_framework.generics import RetrieveAPIView
from .utils import (
    extract_views_from_code, extract_models_from_code, extract_models_from_content,
    generate_view_ai_summary_batch, generate_ai_summary,
    generate_form_ai_summary_batch, extract_forms_from_code
)
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count
from django.db.models.functions import TruncDate
import json

logger = logging.getLogger(__name__)

# --- User & Authentication Endpoints ---

class CurrentUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class RegisterView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'status': 'Error', 'message': str(e)},
                            status=status.HTTP_400_BAD_REQUEST)


# --- Dynamic Model Creation Endpoints (existing ones) ---

def create_model(model_name, fields):
    # Dynamically create a model using provided field definitions.
    attrs = {field['name']: getattr(models, field['type'])() for field in fields}
    new_model = type(model_name, (models.Model,), attrs)
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(new_model)
    return new_model


def create_model_view(request):
    if request.method == 'POST':
        model_name = request.POST.get('model_name')
        full_code = request.POST.get('full_code')
        if not model_name or not full_code:
            return JsonResponse({'status': 'Error', 'message': 'Model name and code are required.'}, status=400)
        new_model = UserModel.objects.create(
            user=request.user,
            model_name=model_name,
            full_code=full_code,
            description=request.POST.get('description', ''),
            visibility=request.POST.get('visibility', 'private')
        )
        return JsonResponse({'status': 'Model created successfully', 'model': model_name})


def field_types_view(request):
    all_fields = [field.__name__ for field in models.Field.__subclasses__()]
    return JsonResponse({'field_types': all_fields})


class GenerateAPIView(APIView):
    """Example endpoint for dynamically generating API resources."""
    def post(self, request):
        model_name = request.data.get('model_name')
        full_code = request.data.get('full_code')
        if not model_name or not full_code:
            return Response({'error': 'Model name and code are required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        out = StringIO()
        try:
            call_command('generate_api', model_name=model_name, full_code=full_code, stdout=out)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({'message': out.getvalue()}, status=status.HTTP_200_OK)


class AvailableModelsAPIView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        models_data = {}
        for model in apps.get_models():
            fields = [field.name for field in model._meta.get_fields()]
            models_data[model.__name__] = fields
        return Response(models_data, status=200)


class AIConversationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing AI conversations.
    Provides standard CRUD operations for AIConversation model.
    """
    serializer_class = AIConversationSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Filter conversations to only return those belonging to the current user
        and optionally filtered by project_id
        """
        queryset = AIConversation.objects.filter(user=self.request.user)
        project_id = self.request.query_params.get('project_id', None)
        if project_id is not None:
            queryset = queryset.filter(project_id=project_id)
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Automatically set the user when creating a conversation"""
        serializer.save(user=self.request.user)

class UserModelViewSet(viewsets.ModelViewSet):
    queryset = UserModel.objects.all()
    serializer_class = UserModelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        filter_type = self.request.query_params.get('filter_type', None)
        if filter_type == 'my_models':
            return self.queryset.filter(user=user)
        elif filter_type == 'other_models':
            return self.queryset.filter(Q(visibility='public') & ~Q(user=user))
        else:
            return self.queryset.filter(Q(user=user) | Q(visibility='public'))

    def perform_create(self, serializer):
        try:
            serializer.save(user=self.request.user)
        except ValidationError as e:
            print("Validation error:", e.detail)
            raise

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)





@api_view(['POST'])
@permission_classes([AllowAny])
def upload_files(request):
    """
    Receives uploaded files, parses Django models from a models.py file, 
    and returns a diagram representation.
    """
    files = request.FILES.getlist('files')
    nodes = []
    edges = []  # Extend as needed
    for file in files:
        filename = file.name
        if filename == 'models.py':
            content = file.read().decode('utf-8')
            models_data = extract_models_from_content(content)
            for model in models_data:
                node_id = f"model-{model['name']}"
                nodes.append({
                    'id': node_id,
                    'type': 'default',
                    'position': {
                        'x': random.randint(100, 500),
                        'y': random.randint(100, 500)
                    },
                    'data': {
                        'model_name': model['name'],
                        'fields': model['fields'],
                        'label': f"{model['name']}\nFields: {', '.join(model['fields'])}"
                    }
                })
    return Response({'nodes': nodes, 'edges': edges})





@api_view(['POST'])
@permission_classes([AllowAny])
def parse_model(request):
    """
    Receives Django model code and returns a diagram representation with AI summaries.
    Expects JSON payload with key 'code'.
    """
    code = request.data.get('code', '')
    if not code:
        logger.error("No code provided in the payload.")
        return Response({"error": "No code provided."}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        models_data = extract_models_from_code(code)
        if not models_data:
            raise ValueError("No models could be extracted from the provided code.")
        
        nodes = []
        edges = []
        model_name_to_node_id = {}
        summaries = {}  # Aggregated summaries: model name -> AI summary

        # Build node mapping for models
        for model_info in models_data:
            model_name = model_info.get("name")
            if not model_name:
                continue
            node_id = f"model-{model_name}"
            model_name_to_node_id[model_name] = node_id

        # Create nodes with AI summaries
        for model_info in models_data:
            model_name = model_info.get("name")
            fields = model_info.get("fields", [])
            relationships = model_info.get("relationships", [])
            try:
                ai_description = generate_ai_summary(model_name, fields, relationships)
            except Exception as ai_error:
                logger.error(f"Error generating AI summary for model '{model_name}': {ai_error}")
                ai_description = "Error generating AI summary"
            summaries[model_name] = ai_description
            node_id = model_name_to_node_id.get(model_name)
            if node_id:
                nodes.append({
                    "id": node_id,
                    "type": "customModel",
                    "position": {
                        "x": random.randint(100, 500),
                        "y": random.randint(100, 500)
                    },
                    "data": {
                        "model_name": model_name,
                        "fields": fields,
                        "ai_description": ai_description,
                    }
                })

        # Create edges based on relationships
        for model_info in models_data:
            source_model = model_info.get("name")
            source_id = model_name_to_node_id.get(source_model)
            for rel in model_info.get("relationships", []):
                target_model = rel.get("target")
                if target_model in model_name_to_node_id:
                    target_id = model_name_to_node_id[target_model]
                    edge_id = f"edge-{source_model}-{target_model}"
                    edges.append({
                        "id": edge_id,
                        "source": source_id,
                        "target": target_id,
                        "data": {
                            "relation_type": rel.get("type", "ForeignKey")
                        }
                    })

        elements = nodes + edges
        return Response({"elements": elements, "summaries": summaries})
    
    except Exception as e:
        logger.error("Error in parse_model view: " + str(e))
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)




class GenerateModelSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            # Extract model details from the request payload
            model_name = request.data.get("model_name")
            fields = request.data.get("fields", [])
            relationships = request.data.get("relationships", [])

            if not model_name or not isinstance(fields, list) or not isinstance(relationships, list):
                return Response(
                    {"error": "Invalid input. Please provide 'model_name', 'fields', and 'relationships'."},
                    status=400
                )

            # Generate AI summary
            summary = generate_ai_summary(model_name, fields, relationships)

            # Return the generated summary
            return Response({"summary": summary}, status=200)

        except Exception as e:
            return Response({"error": str(e)}, status=500)

class SaveModelFileAPIView(generics.GenericAPIView):
    serializer_class = ModelFileSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, pk=None):
        data = request.data.copy()
        is_update = pk is not None
        instance = None
        status_code = status.HTTP_201_CREATED

        if is_update:
            # explicit-update via URL
            instance = get_object_or_404(
                ModelFile,
                pk=pk,
                project__user=request.user
            )
            data.setdefault('app', instance.app.id)
            status_code = status.HTTP_200_OK
        else:
            # create or implicit‑update by unique key
            app_id = data.get('app') or data.get('app_id')
            if not app_id:
                return Response({"app": ["This field is required."]},
                                status=status.HTTP_400_BAD_REQUEST)
            data['app'] = app_id

            # Peek first: do we already have a ModelFile with same (app, name)?
            # We assume `description` holds the filename (e.g. "models.py")
            existing = ModelFile.objects.filter(
                app__id=app_id,
                name=data.get('description')
            ).first()
            if existing:
                instance = existing
                status_code = status.HTTP_200_OK
                # Ensure serializer sees the right app
                data.setdefault('app', existing.app.id)

        serializer = self.get_serializer(
            instance=instance,
            data=data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        if instance is None:
            # CREATE
            app = serializer.validated_data['app']
            model_file = serializer.save(project=app.project)
        else:
            # UPDATE
            model_file = serializer.save()

        return Response(
            self.get_serializer(model_file).data,
            status=status_code
        )

    def put(self, request, pk=None):
        # allow PUT to flow into same codepath
        return self.post(request, pk=pk)

    def patch(self, request, pk=None):
        return self.post(request, pk=pk)
    
class GenerateModelCodeAPIView(generics.GenericAPIView):
    """
    Receives diagram elements (nodes and edges) and generates a complete models.py file.
    Relationships are generated solely from edges if both nodes exist in the diagram.
    Relationship fields already defined in node data are preserved, and extra fields are only appended if they're not duplicates.
    Custom built-in code (like the User field or image processing logic) is merged for known models.
    """
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        elements = request.data.get('elements', [])
        if not elements:
            return Response(
                {"error": "No elements data provided."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Separate nodes and edges.
        nodes = [elem for elem in elements if not elem.get('source')]
        edges = [elem for elem in elements if elem.get('source')]

        # Map node IDs to model names from parsed nodes.
        node_id_to_model = {}
        for node in nodes:
            data = node.get('data', {})
            model_name = data.get('model_name')
            if model_name:
                node_id_to_model[node['id']] = model_name

        # Header with built-in imports.
        lines = [
            "from django.db import models",
            "from django.contrib.auth.models import User",
            "from PIL import Image",
            "",
            "# Generated models.py file",
            ""
        ]

        # Use a dictionary to avoid duplicate relationship fields.
        # Key: (owner_model_id, ref_model, relation_type) → field definition.
        rel_field_keys = {}

        # Process edges to generate relationship fields.
        for edge in edges:
            source_id = edge.get('source')
            target_id = edge.get('target')
            # Only generate if both nodes exist.
            if source_id not in node_id_to_model or target_id not in node_id_to_model:
                continue

            edge_data = edge.get('data', {})
            source_card = edge_data.get('sourceCardinality', "")
            target_card = edge_data.get('targetCardinality', "")

            # Determine relationship type.
            if source_card == "1" and target_card == "1":
                relation_type = "OneToOneField"
            elif source_card == "N" and target_card == "N":
                relation_type = "ManyToManyField"
            else:
                relation_type = "ForeignKey"

            # For ForeignKey, force the "many" side to be the owner.
            if relation_type == "ForeignKey":
                if source_card == "1" and target_card == "N":
                    owner_model_id = target_id       # "N" side becomes owner.
                    ref_model = node_id_to_model[source_id]
                elif source_card == "N" and target_card == "1":
                    owner_model_id = source_id       # "N" side becomes owner.
                    ref_model = node_id_to_model[target_id]
                else:
                    owner_model_id = target_id
                    ref_model = node_id_to_model[source_id]
            else:
                # For OneToOneField or ManyToManyField, use default direction.
                owner_model_id = target_id
                ref_model = node_id_to_model[source_id]

            base_field_name = ref_model.lower()
            # Key to prevent duplicate relationship fields.
            key = (owner_model_id, ref_model, relation_type)
            if key in rel_field_keys:
                continue

            # Define the field.
            field_def = f"{base_field_name} = models.{relation_type}('{ref_model}', on_delete=models.CASCADE)"
            rel_field_keys[key] = field_def

        # Debug logs.
        print("DEBUG: Relationship fields (key: field def):", rel_field_keys)

        # Organize relationship fields per model.
        rel_fields_by_model = {}
        for (owner_model_id, ref_model, relation_type), field_def in rel_field_keys.items():
            rel_fields_by_model.setdefault(owner_model_id, []).append(field_def)

        print("DEBUG: Relationship fields by model:", rel_fields_by_model)

        # Generate model classes.
        for node in nodes:
            data = node.get('data', {})
            model_name = data.get('model_name')
            if not model_name:
                continue

            lines.append(f"class {model_name}(models.Model):")
            defined_field_names = set()

            # For known models (e.g. Comment), force extra relationship fields at the top.
            if model_name == "Comment" and node['id'] in rel_fields_by_model:
                for field_def in rel_fields_by_model[node['id']]:
                    gen_field = field_def.split('=')[0].strip()
                    if gen_field not in defined_field_names:
                        lines.append(f"    {field_def}")
                        defined_field_names.add(gen_field)

            # Process node's own fields.
            fields = data.get('fields', [])
            if fields and isinstance(fields, list) and len(fields) > 0:
                for field in fields:
                    if isinstance(field, dict):
                        field_name = field.get('name')
                        field_type = field.get('type', '')
                        field_params = field.get('params', '').strip()
                        # Skip relationship fields; they come from edges.
                        if field_type in ["ForeignKey", "OneToOneField", "ManyToManyField"]:
                            defined_field_names.add(field_name)
                            continue
                        if field_params:
                            lines.append(f"    {field_name} = models.{field_type}({field_params})")
                        else:
                            lines.append(f"    {field_name} = models.{field_type}()")
                        defined_field_names.add(field_name)
                    elif isinstance(field, str):
                        field_name = field.strip()
                        if field_name and field_name not in defined_field_names:
                            lines.append(f"    {field_name} = models.CharField(max_length=255)")
                            defined_field_names.add(field_name)

            # If no fields were added from the node's data and no extra fields exist, add "pass".
            if (not fields or len(fields) == 0) and (node['id'] not in rel_fields_by_model):
                lines.append("    pass")

            # For other models, if extra fields haven't been output yet, add them now.
            if model_name != "Comment" and node['id'] in rel_fields_by_model:
                for field_def in rel_fields_by_model[node['id']]:
                    gen_field = field_def.split('=')[0].strip()
                    if gen_field not in defined_field_names:
                        lines.append(f"    {field_def}")
                        defined_field_names.add(gen_field)

            # Merge custom built-in code.
            if model_name == "Post":
                if "user" not in defined_field_names:
                    lines.append("    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)")
                lines.append("")
                lines.append("    def save(self, *args, **kwargs):")
                lines.append("        super().save(*args, **kwargs)")
                lines.append("        img = Image.open(self.image.path)")
                lines.append("        if img.height > 400 or img.width > 400:")
                lines.append("            output_size = (400, 400)")
                lines.append("            img.thumbnail(output_size)")
                lines.append("            img.save(self.image.path)")
                lines.append("")
                lines.append("    def __str__(self):")
                lines.append("        return self.title")
                lines.append("")
                lines.append("    class Meta:")
                lines.append("        ordering = ['-created_at']")
            elif model_name == "Comment":
                if "user" not in defined_field_names:
                    lines.append("    user = models.ForeignKey(User, on_delete=models.CASCADE)")
                lines.append("")
                lines.append("    class Meta:")
                lines.append("        ordering = ('-created',)")
                lines.append("")
                lines.append("    def __str__(self):")
                lines.append("        return 'Comment by {}'.format(self.content)")
            else:
                lines.append("")
                lines.append("    def __str__(self):")
                lines.append("        return str(self.id)")
            lines.append("")

        generated_code = "\n".join(lines)
        return Response({"code": generated_code}, status=status.HTTP_200_OK)

class ProjectListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return (
            Project.objects.filter(Q(user=user) | Q(visibility='public'))
            .prefetch_related(
                'apps',
                'apps__model_files',
                'apps__view_files',
                'apps__form_files',
                'apps__app_template_files',
                'apps__app_files',
                'settings_files',
                'url_files',
                'project_files'
            )
        )

    def perform_create(self, serializer):
        # Set the user automatically before creating the project
        serializer.save(user=self.request.user)



class ProjectDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class   = ProjectSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return (
            Project.objects
                   .filter(Q(user=user) | Q(visibility='public'))
                   .prefetch_related(
                       # bring in the apps themselves
                       'apps',
                       # project‑level files (you already see these working)
                       'settings_files',
                       'url_files',
                       'project_files',
                       # NOW pull in *each* app's nested file relations:
                       'apps__model_files',
                       'apps__view_files',
                       'apps__form_files',
                       'apps__app_template_files',
                       'apps__app_files',
                   )
        )
class ProjectFileAccessMixin:
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # filter by project ownership or public visibility
        return self.queryset.filter(
            Q(project__user=user) | Q(project__visibility='public')
        )


class SettingsFileDetailAPIView(ProjectFileAccessMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = SettingsFile.objects.all()
    serializer_class = SettingsFileSerializer
    lookup_field = 'pk'  # matches URL `<int:pk>`


class URLFileDetailAPIView(ProjectFileAccessMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = URLFile.objects.all()
    serializer_class = URLFileSerializer
    lookup_field = 'pk'


class ProjectFileDetailAPIView(ProjectFileAccessMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = ProjectFile.objects.all()
    serializer_class = ProjectFileSerializer
    lookup_field = 'pk'

class ModelFileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ModelFileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        # First, check for an 'app_id' query parameter
        app_id = self.request.query_params.get('app_id')
        if app_id:
            try:
                # Use the automatically generated 'app_id' field
                return ModelFile.objects.get(app_id=app_id)
            except ModelFile.DoesNotExist:
                raise Http404("Model file not found for the given app.")
        
        # Fallback: check for a 'fileId' query parameter
        file_id = self.request.query_params.get('fileId')
        if file_id:
            try:
                return ModelFile.objects.get(pk=file_id)
            except ModelFile.DoesNotExist:
                raise Http404("Model file not found.")

        # Fallback to URL parameter 'pk' if provided
        pk = self.kwargs.get('pk')
        if pk:
            try:
                return ModelFile.objects.get(pk=pk)
            except ModelFile.DoesNotExist:
                raise Http404("Model file not found.")
        
        raise Http404("No model file identifier provided.")

    def get(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    

class AppDetailAPIView(RetrieveAPIView):
    queryset = App.objects.all()
    serializer_class = AppSerializer

    def get(self, request, *args, **kwargs):
        try:
            app = self.get_object()  # Retrieve app by ID
            return Response(self.get_serializer(app).data)
        except App.DoesNotExist:
            return Response({"detail": "App not found."}, status=status.HTTP_404_NOT_FOUND)

class AppListCreateAPIView(generics.ListCreateAPIView):
    """
    Lists all apps for a given project (via ?project_id=<id>) and
    allows creating a new app associated with a project.
    """
    serializer_class = AppSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        project_id = self.request.query_params.get('project_id')
        if project_id:
            return App.objects.filter(project_id=project_id, project__user=self.request.user)
        # If no project_id is provided, return an empty queryset
        return App.objects.none()

    def perform_create(self, serializer):
        project_id = self.request.data.get('project')
        try:
            project = Project.objects.get(id=project_id, user=self.request.user)
        except Project.DoesNotExist:
            raise PermissionDenied("Project not found or not owned by the user.")
        serializer.save(project=project)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

class AppFileViewSet(viewsets.ModelViewSet):
    queryset = AppFile.objects.all()
    serializer_class = AppFileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Return only AppFiles the user has access to through the related App > Project > User
        user = self.request.user
        return AppFile.objects.filter(app__project__user=user)

    def perform_create(self, serializer):
        return serializer.save()
class ProjectURLFileListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = URLFileSerializer

    def get_queryset(self):
        return URLFile.objects.filter(
            project_id=self.kwargs['project_pk'],
            app__isnull=True
        )

    def perform_create(self, serializer):
        serializer.save(
            project_id=self.kwargs['project_pk'],
            app=None
        )

class ProjectURLFileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = URLFileSerializer

    def get_queryset(self):
        return URLFile.objects.filter(
            project_id=self.kwargs['project_pk'],
            app__isnull=True
        )


# — App‑level URLFiles — #

class AppURLFileListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = URLFileSerializer

    def get_queryset(self):
        return URLFile.objects.filter(
            app_id=self.kwargs['app_pk']
        )

    def perform_create(self, serializer):
        serializer.save(
            project=serializer.validated_data.get('project') or 
                    serializer.context['request'].user.apps.get(pk=self.kwargs['app_pk']).project,
            app_id=self.kwargs['app_pk']
        )
class AppURLFileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = URLFileSerializer

    def get_queryset(self):
        app_pk = self.kwargs.get('app_pk')
        logger.info(f"Received request for app_pk: {app_pk}")
        return URLFile.objects.filter(app_id=app_pk)

    def get_object(self):
        queryset = self.get_queryset()
        obj = generics.get_object_or_404(queryset, pk=self.kwargs['pk'])
        logger.info(f"Retrieved object: {obj}")
        return obj
    
class AppAppFileListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = AppFileSerializer

    def get_app(self):
        try:
            return App.objects.get(pk=self.kwargs['app_pk'])
        except App.DoesNotExist:
            raise NotFound("App not found")

    def get_queryset(self):
        return AppFile.objects.filter(app_id=self.kwargs['app_pk'])

    def perform_create(self, serializer):
        app = self.get_app()
        serializer.save(app=app, project=app.project)


class AppAppFileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AppFileSerializer

    def get_queryset(self):
        # Only allow retrieving files belonging to this app
        return AppFile.objects.filter(app_id=self.kwargs['app_pk'])    
from django.http import JsonResponse
from rest_framework.response import Response

from rest_framework import status
import requests
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def parse_viewfile(request):
    """
    Parses the pasted Django view code and returns a diagram JSON containing:
      - A node for each view (with its AI-generated summary and model summary if available)
      - A node for each referenced model (if any, with its summary if available)
      - A node for each referenced form (if any)
      - Edges connecting views to models and forms.
    """
    code = request.data.get('code', '')
    if not code:
        return Response({"error": "No code provided."}, status=400)

    # Optional: Get the app_id to fetch the corresponding ModelFile's and FormFile's summaries.
    app_id = request.data.get('app_id')
    model_summaries = {}
    form_summaries = {}

    if app_id:
        # Load model_summaries
        model_file = ModelFile.objects.filter(app_id=app_id).first()
        if model_file:
            model_summaries = model_file.model_summaries or {}
            if not model_summaries and model_file.summary:
                for entry in model_file.summary.split("\n"):
                    parts = entry.split(":", 1)
                    if len(parts) == 2:
                        model_summaries[parts[0].strip()] = parts[1].strip()

        # Load form_summaries
        form_file = FormFile.objects.filter(app_id=app_id).first()
        if form_file:
            form_summaries = form_file.form_summaries or {}
            if not form_summaries and form_file.summary:
                for entry in form_file.summary.split("\n"):
                    parts = entry.split(":", 1)
                    if len(parts) == 2:
                        form_summaries[parts[0].strip()] = parts[1].strip()

    try:
        # Extract views from code.
        views_data = extract_views_from_code(code)
        if not views_data:
            raise ValueError("No views could be extracted from the provided code.")

        # Generate AI summaries if needed.
        all_have = all(view.get('ai_description','').strip() for view in views_data)
        summaries = (
            [view['ai_description'] for view in views_data]
            if all_have
            else generate_view_ai_summary_batch(views_data)
        )
        print("AI Summaries:", summaries)  # Debugging statement

        nodes, edges = [], []
        view_node_ids, model_node_ids, form_node_ids = {}, {}, {}

        # Build nodes
        for i, view in enumerate(views_data):
            view_name = view.get("name", f"View{i}")
            view_node_id = f"view-{view_name}"
            view_node_ids[view_name] = view_node_id

            # Process model summary
            raw_model_ref = view.get("model", "").strip()
            view_model_summary = ""
            if raw_model_ref and raw_model_ref.lower() != "not specified":
                model_refs = [s.strip() for s in raw_model_ref.split(",") if s.strip()]
                view_model_summary = ", ".join(
                    model_summaries.get(m, "") for m in model_refs if model_summaries.get(m)
                )

            # Process form summary
            raw_form_ref = view.get("form_class", "").strip()
            view_form_summary = ""
            if raw_form_ref and raw_form_ref.lower() != "not specified":
                form_refs = [s.strip() for s in raw_form_ref.split(",") if s.strip()]
                view_form_summary = ", ".join(
                    form_summaries.get(f, "") for f in form_refs if form_summaries.get(f)
                )

            # View node
            nodes.append({
                "id": view_node_id,
                "type": "customView",
                "position": {"x": 0, "y": 0},
                "data": {
                    "view_name":     view_name,
                    "view_type":     view.get("view_type", ""),
                    "model_reference": raw_model_ref,
                    "form_reference":  raw_form_ref,
                    "ai_description":  summaries[i],
                    "model_summary":   view_model_summary,
                    "form_summary":    view_form_summary,
                }
            })

            # Model nodes & edges
            if raw_model_ref and raw_model_ref.lower() != "not specified":
                for single_model in raw_model_ref.split(","):
                    single_model = single_model.strip()
                    if not single_model:
                        continue
                    if single_model not in model_node_ids:
                        model_node_ids[single_model] = f"model-{single_model}"
                        nodes.append({
                            "id": model_node_ids[single_model],
                            "type": "customModel",
                            "position": {"x": 0, "y": 0},
                            "data": {
                                "model_name":    single_model,
                                "model_summary": model_summaries.get(single_model, "")
                            }
                        })
                    edges.append({
                        "id": f"edge-{view_node_id}-{model_node_ids[single_model]}",
                        "source": view_node_id,
                        "target": model_node_ids[single_model],
                        "data": {"label": "references"}
                    })

            # Form nodes & edges
            if raw_form_ref and raw_form_ref.lower() != "not specified":
                for single_form in raw_form_ref.split(","):
                    single_form = single_form.strip()
                    if not single_form:
                        continue
                    if single_form not in form_node_ids:
                        form_node_ids[single_form] = f"form-{single_form}"
                        nodes.append({
                            "id": form_node_ids[single_form],
                            "type": "customForm",
                            "position": {"x": 0, "y": 0},
                            "data": {"form_name": single_form}
                        })
                    edges.append({
                        "id": f"edge-{view_node_id}-{form_node_ids[single_form]}",
                        "source": view_node_id,
                        "target": form_node_ids[single_form],
                        "data": {"label": "uses"}
                    })



        return Response({"elements": nodes + edges})

    except Exception as e:
        return Response({"error": str(e)}, status=400)


class ModelFileListCreateAPIView(generics.ListCreateAPIView):
    """
    GET  /api/model‑files/?app_id=<app_id>  → list all model files for that app
    POST /api/model‑files/                  → create a new model file
    """
    serializer_class = ModelFileSerializer

    def get_queryset(self):
        qs = ModelFile.objects.all()
        app_id = self.request.query_params.get('app_id')
        if app_id:
            qs = qs.filter(app__id=app_id)
        return qs
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import App, ViewFile
from .serializers import ViewFileSerializer

class SaveViewFileAPIView(APIView):
    def post(self, request, format=None):
        logger.debug("SaveViewFileAPIView called")
        data = request.data.copy()
        app_id = data.get('app_id')

        try:
            app = App.objects.get(id=app_id, project__user=request.user)
        except App.DoesNotExist:
            return Response(
                {"error": "App not found or not owned by user."},
                status=status.HTTP_404_NOT_FOUND
            )

        data.pop('app_id', None)
        data['app'] = app.pk

        model_file = ModelFile.objects.filter(app=app).first()
        model_summaries = model_file.model_summaries if model_file else {}

        diagram_data = data.get('diagram', {})
        nodes = diagram_data.get('nodes', [])
        view_summaries = {}

        for node in nodes:
            if node.get('type') == 'customView':
                view_name = node.get('data', {}).get('view_name', '').strip()
                view_summary = node.get('data', {}).get('ai_description', '').strip()
                if view_name:
                    view_summaries[view_name] = view_summary if view_summary else "No summary available."

                model_ref = node.get('data', {}).get('model_reference', '').strip()
                if model_ref and model_ref.lower() != "not specified":
                    if model_ref in model_summaries:
                        node.setdefault('data', {})['model_summary'] = model_summaries[model_ref]
                    else:
                        found_key = next((k for k in model_summaries if k.lower() == model_ref.lower()), None)
                        node.setdefault('data', {})['model_summary'] = model_summaries.get(found_key, "") if found_key else ""
                else:
                    node.setdefault('data', {})['model_summary'] = ""

        data['view_summaries'] = view_summaries

        existing_file = ViewFile.objects.filter(app=app).first()
        if existing_file:
            serializer = ViewFileSerializer(existing_file, data=data, partial=True)
        else:
            serializer = ViewFileSerializer(data=data)

        if serializer.is_valid():
            saved_viewfile = serializer.save()
            return Response({"file_id": saved_viewfile.id}, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SaveViewFileCodeOnlyAPIView(APIView):
    def put(self, request, pk, format=None):
        try:
            view_file = ViewFile.objects.get(id=pk, app__project__user=request.user)
        except ViewFile.DoesNotExist:
            return Response(
                {"error": "ViewFile not found or not owned by user."},
                status=status.HTTP_404_NOT_FOUND
            )

        content = request.data.get('content')
        if content is None:
            return Response(
                {"error": "Missing 'content' in request."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update the content and clear diagram-related fields
        view_file.content = content
        view_file.diagram = None  # Clear existing diagram
        view_file.view_summaries = {}  # Reset summaries
        view_file.save()

        # Serialize the full view file object
        serializer = ViewFileSerializer(view_file)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class FetchSavedViewFileAPIView(APIView):
    def get(self, request, id, format=None):
        try:
            view_file = ViewFile.objects.get(id=id)
            app = view_file.app

            # Check if ModelFile exists for this app
            model_file = ModelFile.objects.filter(app=app).first()
            model_summaries = model_file.model_summaries if model_file else {}

            # Enrich view nodes with model summaries
            diagram_data = view_file.diagram
            nodes = diagram_data.get('nodes', [])
            for node in nodes:
                if node.get('type') == 'customView':
                    model_ref = node.get('data', {}).get('model_reference', '')
                    if model_ref and model_ref in model_summaries:
                        node['data']['model_summary'] = model_summaries[model_ref]

            return Response({
                'content': view_file.content,
                'diagram': diagram_data,
                
            }, status=200)
        except ViewFile.DoesNotExist:
            return Response({"error": "View file not found."}, status=404)



class ViewFileListAPIView(generics.ListAPIView):
    """
    Returns a list of ViewFiles for the given app.
    You can filter by app_id using the query parameter.
    """
    serializer_class = ViewFileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        app_id = self.request.query_params.get('app_id')
        if app_id:
            return ViewFile.objects.filter(app=app_id)
        return ViewFile.objects.all()
    
class ViewFileDetailAPIView(generics.RetrieveAPIView):
    """
    Retrieves the details of a saved ViewFile.
    """
    queryset = ViewFile.objects.all()
    serializer_class = ViewFileSerializer
    permission_classes = [IsAuthenticated]



from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status

@api_view(['POST'])
@permission_classes([])
def parse_formfile(request):
    """
    Parses Django form code to produce:
      - A 'customForm' node for each form
      - A 'customModel' node for each referenced model
      - Edges from the form to the model
    """
    code = request.data.get('code', '')
    if not code:
        return Response({"error": "No code provided."}, status=status.HTTP_400_BAD_REQUEST)

    forms_data = extract_forms_from_code(code)
    if not forms_data:
        return Response({"error": "No forms found."}, status=status.HTTP_400_BAD_REQUEST)

    # Identify forms that need AI descriptions
    forms_needing_summaries = [
        form for form in forms_data
        if not form.get("ai_description") and not form.get("form_summary")
    ]

    # Generate AI summaries only for forms that lack descriptions
    ai_summaries = {}
    if forms_needing_summaries:
        generated_summaries = generate_form_ai_summary_batch(forms_needing_summaries)
        for i, form in enumerate(forms_needing_summaries):
            ai_summaries[form["name"]] = generated_summaries[i]

    nodes = []
    edges = []
    model_nodes_map = {}

    for form in forms_data:
        form_name = form.get("name", "UnnamedForm")
        model_name = form.get("model", "").strip()

        # Use existing ai_description or generated summary as form_summary
        form_summary = form.get("form_summary") or form.get("ai_description") or ai_summaries.get(form_name, "")

        form_node_id = f"form-{form_name}"
        # 1) Create the customForm node
        nodes.append({
            "id": form_node_id,
            "type": "customForm",
            "position": {"x": 0, "y": 0},
            "data": {
                "form_name": form_name,
                "form_summary": form_summary,  # Use existing or generated summary
                "model_used": model_name,      # So you can link form to a model
            }
        })

        # 2) If there's a model, create or reuse a customModel node
        if model_name and model_name.lower() != "not specified":
            if model_name not in model_nodes_map:
                model_node_id = f"model-{model_name}"
                model_nodes_map[model_name] = model_node_id
                nodes.append({
                    "id": model_node_id,
                    "type": "customModel",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "model_name": model_name,
                        "model_summary": f"This is a fallback summary for {model_name}"
                    }
                })

            # 3) Create an edge from the form node to the model node
            edges.append({
                "id": f"edge-{form_node_id}-{model_nodes_map[model_name]}",
                "source": form_node_id,
                "target": model_nodes_map[model_name],
                "type": "customEdge",
                "data": {"label": "uses model"}
            })

    elements = nodes + edges
    return Response({"elements": elements})


class FormFileDetailAPIView(APIView):
    def get_object(self, pk):
        try:
            return FormFile.objects.get(pk=pk)
        except FormFile.DoesNotExist:
            raise Http404("Form file not found.")

    def get(self, request, pk, format=None):
        form_file = self.get_object(pk)
        serializer = FormFileSerializer(form_file)
        return Response(serializer.data, status=status.HTTP_200_OK)

class FormFileListAPIView(APIView):
    """
    GET endpoint to retrieve form files based on app_id.
    """
    def get(self, request):
        app_id = request.query_params.get('app')
        if app_id:
            form_files = FormFile.objects.filter(app_id=app_id)
        else:
            form_files = FormFile.objects.all()
        serializer = FormFileSerializer(form_files, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class SaveFormFileContentAPIView(APIView):
    """
    POST endpoint to update the content of a FormFile.
    Expected payload includes:
      - id: ID of the FormFile.
      - content: The form file content.
    """
    permission_classes = []  # Adjust permissions as needed.

    def post(self, request, format=None):
        data = request.data.copy()
        form_file_id = data.get("id")
        print("Received data:", data)  # Debugging log

        try:
            form_file = FormFile.objects.get(id=form_file_id)
        except FormFile.DoesNotExist:
            return Response(
                {"error": "FormFile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Update the content
        form_file.content = data.get("content", "")
        form_file.save()

        serializer = FormFileSerializer(form_file)
        return Response(serializer.data, status=status.HTTP_200_OK)

class SaveFormFileAPIView(APIView):
    """
    POST endpoint to create or update a FormFile.
    Expected payload includes:
      - app_id: ID of the associated App.
      - content: The form file content.
      - diagram: JSON (nodes/edges for the form file diagram).
      - description: Description text.
      - summary: Combined summary text.
      - form_summaries: (Optional) a dictionary of individual form summaries.
    """
    permission_classes = []  # Adjust permissions as needed.

    def post(self, request, format=None):
        data = request.data.copy()
        app_id = data.get("app_id")
        print("Received data:", data)  # Debugging log

        try:
            app = App.objects.get(id=app_id, project__user=request.user)
        except App.DoesNotExist:
            return Response(
                {"error": "App not found or not owned by user."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Remove app_id and set the proper foreign key
        data.pop("app_id", None)
        data["app"] = app.pk
        data["project"] = app.project_id 
        # Fetch existing FormFile (if any) so we can re‑apply its stored summaries
        form_file = FormFile.objects.filter(app=app).first()
        stored_summaries = form_file.form_summaries if form_file else {}

        # If we have no stored_summaries but the old combined `summary` field has lines,
        # parse them into stored_summaries.
        if not stored_summaries and form_file and form_file.summary:
            for line in form_file.summary.split("\n"):
                key, sep, val = line.partition(":")
                if sep:
                    stored_summaries[key.strip()] = val.strip()

        # ONLY re‑apply stored_summaries when updating.
        # On a brand‑new save, stored_summaries is empty and we skip this,
        # preserving whatever parse_formfile set in node.data.form_summary.
        diagram = data.get("diagram", {})
        nodes = diagram.get("nodes", [])
        if stored_summaries:
            for node in nodes:
                if node.get("type") == "customForm":
                    form_name = node.get("data", {}).get("form_name", "").strip()
                    if form_name in stored_summaries:
                        node["data"]["form_summary"] = stored_summaries[form_name]
                    # else: leave node.data.form_summary alone

        # Build the new form_summaries from whatever is now in node.data.form_summary
        def build_form_summaries(node_list):
            summaries = {}
            for node in node_list:
                if node.get("type") == "customForm":
                    form_name = node.get("data", {}).get("form_name", "").strip()
                    form_summary = node.get("data", {}).get("form_summary", "").strip() \
                                   or "No summary available."
                    if form_name:
                        summaries[form_name] = form_summary
            return summaries

        # Use the form_summaries from the payload if provided
        if "form_summaries" in data and data["form_summaries"]:
            data["form_summaries"] = data["form_summaries"]
        else:
            data["form_summaries"] = build_form_summaries(nodes)

        print("Form Summaries to Save:", data["form_summaries"])  # Debugging log

        # Create or update
        existing = FormFile.objects.filter(app=app).first()
        if existing:
            serializer = FormFileSerializer(existing, data=data, partial=True)
        else:
            serializer = FormFileSerializer(data=data)

        if serializer.is_valid():
            serializer.save()
            code = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
            return Response(serializer.data, status=code)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def infer_file_type(filename, choices):
    """
    Infer a choice key by extension, falling back to 'other'.
    `choices` should be the model's file_type choices list.
    """
    ext = filename.lower().rsplit('.', 1)[-1]
    for key, _ in choices:
        if key == ext or (key == 'img' and ext in ('png','jpg','jpeg','gif','svg')):
            return key
        if key == 'video' and ext in ('mp4','webm','ogg'):
            return key
        if key == 'image' and ext in ('png','jpg','jpeg','gif','svg'):
            return key
        if key == 'doc' and ext in ('pdf','doc','docx','txt'):
            return key
    return 'other'





class ProjectTemplateFileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TemplateFileSerializer
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return TemplateFile.objects.filter(project_id=self.kwargs['project_pk'], app=None)


# —— App‐level TemplateFiles ——
class AppTemplateFileListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = TemplateFileSerializer

    def get_queryset(self):
        return TemplateFile.objects.filter(app_id=self.kwargs['app_pk'])

    def perform_create(self, serializer):
        app = get_object_or_404(App, pk=self.kwargs['app_pk'])
        serializer.save(app=app, project=app.project, is_app_template=True)

class AppTemplateFileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TemplateFileSerializer
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        return TemplateFile.objects.filter(app_id=self.kwargs['app_pk'])


# —— Repeat the above pattern for StaticFile … ——


class ProjectStaticFileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = StaticFileSerializer

    def get_queryset(self):
        return StaticFile.objects.filter(project_id=self.kwargs['project_pk'])



# —— … and for MediaFile ——



class ProjectMediaFileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MediaFileSerializer
    def get_queryset(self):
        return MediaFile.objects.filter(project_id=self.kwargs['project_pk'])




class BaseFileUploadAPIView(generics.ListCreateAPIView):
    parser_classes    = [MultiPartParser, FormParser]
    file_model        = None
    serializer_class  = None
    project_kw        = 'project_pk'

    def get_queryset(self):
        return self.file_model.objects.filter(
            project_id=self.kwargs[self.project_kw],
        )

    def post(self, request, *args, **kwargs):
        project = get_object_or_404(Project, pk=kwargs[self.project_kw])
        uploads = request.FILES.getlist('files')
        paths   = request.data.getlist('paths')
        created, errors = [], []

        # Process each uploaded file
        for idx, uploaded_file in enumerate(uploads):
            # Get the relative path, or default to the file name if not provided
            rel_path = (
                paths[idx].strip()
                if idx < len(paths) and paths[idx].strip()
                else uploaded_file.name
            )

            file_type = infer_file_type(
                uploaded_file.name,
                self.file_model._meta.get_field('file_type').choices
            )

            payload = {
                'path':      rel_path,
                'name':      uploaded_file.name,
                'file_type': file_type,
                'file':      uploaded_file,
                'project':   project.id,
            }

            serializer = self.serializer_class(
                data=payload,
                context={'request': request}
            )

            if serializer.is_valid():
                serializer.save()
                created.append(serializer.data)
            else:
                errors.append({
                    'file': uploaded_file.name,
                    'errors': serializer.errors,
                    'payload': payload,
                })

        # Return the response with the results
        if not created:
            return Response(
                {'created': [], 'errors': errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {'created': created, 'errors': errors},
            status=status.HTTP_201_CREATED
        )



class ProjectStaticFileListCreateAPIView(BaseFileUploadAPIView):
    file_model       = StaticFile
    serializer_class = StaticFileSerializer

class ProjectMediaFileListCreateAPIView(BaseFileUploadAPIView):
    file_model = MediaFile
    serializer_class = MediaFileSerializer


class ProjectTemplateFileListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = TemplateFileSerializer
    parser_classes   = [MultiPartParser, FormParser]

    def get_queryset(self):
        return TemplateFile.objects.filter(
            project_id=self.kwargs['project_pk'],
            app=None
        )

    def post(self, request, *args, **kwargs):
        project = get_object_or_404(Project, pk=kwargs['project_pk'])
        uploads = request.FILES.getlist('files')
        paths   = request.data.getlist('paths')  # ← get all paths
        created, errors = [], []

        for idx, upload in enumerate(uploads):
            # decode text
            try:
                text = upload.read().decode(settings.DEFAULT_CHARSET)
            except Exception:
                text = upload.read().decode('utf-8', errors='ignore')

            # pick the matching path, or fallback to filename
            rel_path = paths[idx] if idx < len(paths) else upload.name

            data = {
                'path': rel_path,
                'name': upload.name,
                'content': text,
                'description': request.data.get('description', ''),
                'is_app_template': False,
            }
            serializer = self.get_serializer(data=data, context={'request': request})
            if serializer.is_valid():
                serializer.save(project=project, app=None)
                created.append(serializer.data)
            else:
                errors.append(serializer.errors)

        if errors and not created:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response(created, status=status.HTTP_201_CREATED)


class AppTemplateFileListCreateAPIView(generics.ListCreateAPIView):
    """
    List all template files for a given App and allow uploading folders/files
    preserving their relative paths.
    """
    serializer_class = TemplateFileSerializer
    parser_classes   = [MultiPartParser, FormParser]

    def get_queryset(self):
        return TemplateFile.objects.filter(app_id=self.kwargs['app_pk'])

    def post(self, request, *args, **kwargs):
        # Fetch the App instance
        app = get_object_or_404(App, pk=kwargs['app_pk'])

        # Get uploaded files and their relative paths
        uploads = request.FILES.getlist('files')
        paths   = request.data.getlist('paths')
        created, errors = [], []

        for idx, upload in enumerate(uploads):
            # Read file content
            try:
                text = upload.read().decode(settings.DEFAULT_CHARSET)
            except Exception:
                text = upload.read().decode('utf-8', errors='ignore')

            # Determine the relative path (fallback to filename)
            rel_path = paths[idx] if idx < len(paths) else upload.name

            # Prepare data for serializer
            data = {
                'path': rel_path,
                'name': upload.name,
                'content': text,
                'description': request.data.get('description', ''),
                'is_app_template': True,
            }
            serializer = self.get_serializer(data=data, context={'request': request})

            # Validate and save each file
            if serializer.is_valid():
                serializer.save(project=app.project, app=app)
                created.append(serializer.data)
            else:
                errors.append(serializer.errors)

        # Handle errors vs. successes
        if errors and not created:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
        return Response(created, status=status.HTTP_201_CREATED)
    
from rest_framework_simplejwt.views import TokenObtainPairView

class CookieTokenObtainPairView(TokenObtainPairView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        # set the access token as an HttpOnly cookie
        response.set_cookie(
            "access_token", 
            response.data["access"], 
            httponly=True, 
            samesite="None", 
            secure=False
        )
        return response
class RunProjectAPIView(APIView):
    """
    Simply returns the URL where the dynamic-in-DB project is mounted.
    """
    def post(self, request, project_pk):
        # If your dynamic_urls are mounted at "/projects/<project_pk>/…"
        path = f"/projects/{project_pk}/"

        # Build an absolute URL so the frontend can open a full link
        full_url = request.build_absolute_uri(path)
        return Response({'url': full_url}, status=status.HTTP_200_OK)
    
class DebugDBAlias(APIView):
    def get(self, request, *args, **kwargs):
        return Response({
            "project_db_alias": getattr(request, "project_db_alias", None),
            "session_db_alias": request.session.get("project_db_alias"),
            "user_state_db": getattr(request.user._state, "db", None),
            "user_pk": request.user.pk,
        })
from django.utils.decorators import method_decorator


class PreviewRunAPIView(APIView):
    """
    POST { mode: "before" | "after", change_id? }
    → { url: "https://…/projects/<id>/?preview_mode=…&preview_change_id=…" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, project_id):
        mode = request.data.get('mode', 'before')
        change_id = request.data.get('change_id')
        
        logger.debug(f"Preview run request: project={project_id}, mode={mode}, change_id={change_id}")
        
        # Check if all parameters are valid
        if mode == 'after' and not change_id:
            logger.error("Missing change_id for after preview")
            return Response(
                {"error": "Missing change_id for 'after' mode"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # If "after" mode, verify the change request exists
            if mode == 'after' and change_id:
                try:
                    change = AIChangeRequest.objects.get(
                        id=change_id,
                        project_id=project_id
                    )
                    if not change.diff:
                        logger.error(f"Change request {change_id} has no diff data")
                        return Response(
                            {"error": "Change request has no diff data"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    
                    # Set up preview project with changes
                    preview_alias = f"preview_{project_id}_after_{change_id}"
                    raw_label = change.app_name.lower() if change.app_name else "app"
                    
                    try:
                        # Set up the preview project with changes
                        modified_files = setup_preview_project(project_id, preview_alias, raw_label, change_id)
                        logger.debug(f"Successfully set up preview project with {len(modified_files)} modified files")
                    except Exception as setup_err:
                        logger.error(f"Error setting up preview project: {str(setup_err)}")
                        # Continue anyway - we'll still generate the URL and the preview will handle errors
                
                except AIChangeRequest.DoesNotExist:
                    logger.error(f"Change request not found: id={change_id}, project_id={project_id}")
                    return Response(
                        {"error": "Change request not found"},
                        status=status.HTTP_404_NOT_FOUND
                    )
            
            # Build the preview URL
            host = request.get_host()
            protocol = 'https' if request.is_secure() else 'http'
            
            # Direct URL to the running project for "before" mode
            if mode == 'before':
                url = f"{protocol}://{host}/projects/{project_id}/"
            else:
                # URL with special parameters for "after" mode
                url_params = [f"preview_mode={mode}"]
                if change_id:
                    url_params.append(f"preview_change_id={change_id}")
                
                url = f"{protocol}://{host}/projects/{project_id}/?{'&'.join(url_params)}"
            
            logger.debug(f"Preview URL generated: {url}")
            
            return Response({"url": url})
            
        except Exception as e:
            logger.error(f"Error generating preview URL: {str(e)}")
            logger.error(traceback.format_exc())
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class FullPreviewDiffAPIView(APIView):
    def post(self, request, project_id, change_id):
        try:
            change = AIChangeRequest.objects.get(id=change_id, project_id=project_id)
            preview_alias = f"preview_{project_id}_after_{change_id}"
            raw_label = change.app_name.lower()
            
            # Setup and run both projects
            modified_files = setup_preview_project(project_id, preview_alias, raw_label, change_id)
            
            # Generate diff data for DiffModal
            diff_data = generate_diff_data(project_id, change_id, preview_alias, raw_label, modified_files)
            
            return Response(diff_data, status=status.HTTP_200_OK)
        except AIChangeRequest.DoesNotExist:
            logger.error(f"AIChangeRequest {change_id} not found for project {project_id}")
            return Response({"error": "ChangeRequest not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error generating preview diff: {e}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def generate_diff_data(project_id, change_id, preview_alias, raw_label, modified_files):
    """
    Generate data for DiffModal, including code diffs and preview URLs.
    """
    change = AIChangeRequest.objects.get(id=change_id, project_id=project_id)
    diff = json.loads(change.diff)
    
    # Prepare files array for DiffModal
    files = []
    for path in modified_files:
        # Original content
        original_content = FileIndexer.get_content(path) or ''
        
        # Updated content - make sure we're getting the complete file, not just changes
        if path in diff:
            if isinstance(diff[path], dict) and 'after' in diff[path]:
                # If the diff has a structured format with before/after
                updated_content = diff[path]['after']
            else:
                # If the diff directly contains the updated content
                updated_content = diff[path]
        else:
            updated_content = original_content
            
        # Ensure the updated content is complete (not fragments)
        if updated_content and path.endswith('.html') and ('analytics' in original_content.lower() or 'chart' in original_content.lower()):
            # If it's an analytics template, ensure proper structure
            if '{% extends' not in updated_content and '<html' not in updated_content.lower():
                logger.info(f"Adding template structure to analytics content in {path}")
                updated_content = "{% extends 'base.html' %}\n\n{% block content %}\n" + updated_content + "\n{% endblock %}"
        
        files.append({
            'filePath': path,
            'before': original_content,
            'after': updated_content,
            'projectId': project_id,
            'changeId': change_id
        })
    
    # Generate preview URLs
    preview_map = {
        'before': f"/projects/{project_id}/",
        'after': f"/projects/{project_id}/preview/{change_id}/"
    }
    
    return {
        'files': files,
        'previewMap': preview_map,
        'change_id': change_id
    }



from django.db import transaction
import json 
from django.http import HttpResponse
def apply_changes_to_project(project_id, change_id):
    """
    Save all modified files from AIChangeRequest to the project's database.
    """
    change = AIChangeRequest.objects.get(id=change_id, project_id=project_id)
    diff = json.loads(change.diff)
    app_name = change.app_name.split('_', 2)[2] if '_' in change.app_name else change.app_name
    
    file_models = {
        'model': ModelFile,
        'view': ViewFile,
        'form': FormFile,
        'template': TemplateFile,
        'static': StaticFile,
        'app': AppFile,
        'settings': SettingsFile,
        'url': URLFile,
        'project': ProjectFile,
        'media': MediaFile
    }
    
    with transaction.atomic():
        for path, content in diff.items():
            # Normalize template paths
            if path.startswith('templates/'):
                path = path.replace('templates/', '', 1)
                file_type = 'template'
            else:
                # Determine file type and app
                parts = path.split('/')
                file_type = None
                if len(parts) > 1 and parts[0] in App.objects.filter(project_id=project_id).values_list('name', flat=True):
                    app_name_from_path = parts[0]
                    app = App.objects.get(project_id=project_id, name=app_name_from_path)
                    rel_path = '/'.join(parts[1:])
                else:
                    rel_path = path
                    
                # Match file type
                for type_key, model_class in file_models.items():
                    if change.file_type == type_key or path.endswith(('.py', '.html', '.css', '.js')):
                        file_type = type_key
                        break
            
            model = file_models.get(file_type, AppFile)  # Fallback to AppFile for unknown types
            
            # Update or create file
            defaults = {'content': content, 'project_id': project_id}
            if app:
                defaults['app'] = app
            
            try:
                obj = model.objects.update_or_create(
                    project_id=project_id,
                    path=path,
                    defaults=defaults
                )[0]
                logger.debug(f"Saved {model.__name__}: {path}")
            except Exception as e:
                logger.error(f"Error saving {path}: {str(e)}")
                continue
        
        # Mark change as applied
        change.status = 'applied'
        change.save()


class ApplyChangesAPIView(APIView):
    def post(self, request, project_id, change_id):
        try:
            apply_changes_to_project(project_id, change_id)
            return Response({"message": "Changes applied successfully"}, status=status.HTTP_200_OK)
        except AIChangeRequest.DoesNotExist:
            logger.error(f"AIChangeRequest {change_id} not found for project {project_id}")
            return Response({"error": "ChangeRequest not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error applying changes: {e}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
import traceback
import os
from core.services.file_indexer import FileIndexer
from django.template import Engine, RequestContext, TemplateDoesNotExist, Context
from django.templatetags.static import static as static_tag
from django.template import engines
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.decorators.http import require_GET
# ————————————————————————————————————————————————————————————————————————————
# 1) Simple "preview_view" for any file type (just dumps raw or patched content)
# ————————————————————————————————————————————————————————————————————————————
@require_GET
@csrf_exempt
def preview_view(request, project_id):
    change_id = request.GET.get("change_id")
    mode = request.GET.get("mode", "after")
    file_path = request.GET.get("file", "")  # Keep using "file" as the parameter name for backwards compatibility

    logger.debug(f"Preview request: project={project_id}, change={change_id}, mode={mode}, file={file_path}")

    if not change_id and mode == "after":
        logger.error(f"Missing change_id for after preview: {request.GET}")
        return HttpResponse(status=400, content="Missing change_id for 'after' preview")

    try:
        change = AIChangeRequest.objects.get(pk=change_id, project_id=project_id) if change_id else None
        
        # First try to get content from the diff directly, for the "after" mode
        content = None
        if mode == "after" and change:
            # Get new content from diff
            diff_data = json.loads(change.diff or "{}")
            
            # Check if file is in the diff and has content
            if file_path in diff_data:
                file_data = diff_data[file_path]
                # Extract content depending on structure
                if isinstance(file_data, str):
                    content = file_data
                    logger.debug(f"Found string content for {file_path} in diff")
                elif isinstance(file_data, dict):
                    # Try different possible keys where content might be stored
                    for key in ['content', 'after', 'preview']:
                        if key in file_data:
                            if key == 'preview' and isinstance(file_data[key], dict) and 'after' in file_data[key]:
                                content = file_data[key]['after']
                                logger.debug(f"Found content in diff at {file_path}.preview.after")
                                break
                            elif isinstance(file_data[key], str):
                                content = file_data[key]
                                logger.debug(f"Found content in diff at {file_path}.{key}")
                                break
                    
                    if not content:
                        logger.warning(f"Could not extract content from diff data for {file_path}: {file_data.keys()}")
        
        # If content is still None, try getting original content for "before" mode or as fallback
        if content is None:
            original_content = ""
            if file_path.startswith("templates/"):
                try:
                    orig_file = TemplateFile.objects.get(
                        project_id=project_id, 
                        path=file_path.replace("templates/", "")
                    )
                    original_content = orig_file.content or ""
                    logger.debug(f"Found template file: {file_path}")
                except TemplateFile.DoesNotExist:
                    logger.warning(f"TemplateFile not found: project_id={project_id}, path={file_path}")
            else:
                try:
                    orig_file = StaticFile.objects.get(project_id=project_id, path=file_path)
                    original_content = orig_file.content or ""
                    logger.debug(f"Found static file: {file_path}")
                except StaticFile.DoesNotExist:
                    logger.warning(f"StaticFile not found: project_id={project_id}, path={file_path}")
            
            # Use original content for "before" mode or as fallback if we couldn't get "after" content
            if mode == "before" or content is None:
                content = original_content
                logger.debug(f"Using original content for {file_path} in mode={mode}")

        # Check preview directory as final fallback
        if not content:
            alias = f"preview_{project_id}_after_{change_id}"
            preview_dir = os.path.join(settings.PREVIEW_ROOT, "dynamic_apps_preview", alias)
            preview_path = os.path.join(preview_dir, file_path)
            
            if os.path.exists(preview_path):
                with open(preview_path, "r", encoding="utf-8") as f:
                    content = f.read()
                logger.debug(f"Loaded content from preview directory: {preview_path}")
        
        # If we still have no content, return 404
        if not content:
            logger.error(f"No content found for {file_path} in mode={mode}")
            return HttpResponse(status=404, content=f"No content found for {file_path}")

        # Determine the content type based on file extension
        ext = os.path.splitext(file_path)[1].lower()
        content_type = {
            '.html': 'text/html',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.json': 'application/json',
            '.txt': 'text/plain',
            '.py': 'text/plain',
        }.get(ext, 'text/plain')

        # Log successful preview generation
        logger.debug(f"Returning {len(content)} bytes for {file_path} as {content_type}")
        
        # Return the content with appropriate content type
        return HttpResponse(content, content_type=content_type)

    except Exception as e:
        logger.error(f"Error in preview_view: {e}")
        logger.error(traceback.format_exc())
        return HttpResponse(status=500, content=f"Error: {str(e)}")

    except AIChangeRequest.DoesNotExist:
        logger.error(f"AIChangeRequest not found: pk={change_id}, project_id={project_id}")
        return HttpResponse(status=404)
    except Exception as e:
        logger.exception(f"Error in preview_view: {str(e)}")
        return HttpResponseServerError(f"Server error: {str(e)}")

    except AIChangeRequest.DoesNotExist:
        logger.error(f"AIChangeRequest not found: pk={change_id}, project_id={project_id}")
        return HttpResponse(status=404)
    except Exception as e:
        logger.exception(f"Error in preview_view: {str(e)}")
        return HttpResponseServerError(f"Server error: {str(e)}")


# ————————————————————————————————————————————————————————————————————————————
# 2) "PreviewOneView" that actually renders via the real template engine
# ————————————————————————————————————————————————————————————————————————————
from rest_framework_simplejwt.authentication import JWTAuthentication
# core/views.py

from rest_framework_simplejwt.authentication import JWTAuthentication
from django.template import engines
from django.core.cache import cache

class PreviewOneView(APIView):
    def get(self, request, project_id, change_id):
        file_path = request.GET.get("file")
        mode = request.GET.get("mode", "after")

        if not file_path:
            return Response({"error": "Missing file parameter"}, status=400)

        try:
            change = AIChangeRequest.objects.get(id=change_id, project_id=project_id)
            raw_label = change.app_name.lower()
            preview_dir = os.path.join(
                settings.PREVIEW_ROOT,
                "dynamic_apps_preview",
                f"preview_{project_id}_after_{change_id}_{raw_label}"
            )
            # Configure template engine to prioritize preview directory
            engine = Engine(dirs=[preview_dir], app_dirs=True, debug=True)
            engines['django'] = engine

            diff = json.loads(change.diff or "{}")
            patched_content = diff.get(file_path)

            context = {"request": request, "user": request.user, "posts": []}

            if file_path.endswith(".html"):
                if mode == "before" or not patched_content:
                    try:
                        template = engine.get_template(file_path.replace("templates/", "") if file_path.startswith("templates/") else file_path)
                        rendered = template.render(context, request)
                        return HttpResponse(rendered, content_type="text/html")
                    except TemplateDoesNotExist:
                        return Response({"error": "Template not found"}, status=404)
                else:
                    template = engine.from_string(patched_content)
                    rendered = template.render(context, request)
                    return HttpResponse(rendered, content_type="text/html")
            else:
                # Handle static files
                if mode == "before":
                    try:
                        static_file = StaticFile.objects.get(project_id=project_id, path=file_path)
                        content = static_file.content or ""
                    except StaticFile.DoesNotExist:
                        logger.warning(f"StaticFile not found: project_id={project_id}, path={file_path}")
                        return Response({"error": "Static file not found"}, status=404)
                else:
                    content = patched_content or ""
                    if not content:
                        try:
                            static_file = StaticFile.objects.get(project_id=project_id, path=file_path)
                            content = static_file.content or ""
                        except StaticFile.DoesNotExist:
                            logger.warning(f"StaticFile not found: project_id={project_id}, path={file_path}")
                            return Response({"error": "Static file not found"}, status=404)

                if os.path.exists(os.path.join(preview_dir, file_path)):
                    with open(os.path.join(preview_dir, file_path), "r", encoding="utf-8") as f:
                        content = f.read()
                    logger.debug(f"Loaded content from preview directory: {os.path.join(preview_dir, file_path)}")

                return HttpResponse(content, content_type="text/plain")

        except AIChangeRequest.DoesNotExist:
            return Response({"error": "ChangeRequest not found"}, status=404)
        except Exception as e:
            logger.exception(f"Error in PreviewOneView: {str(e)}")
            return Response({"error": str(e)}, status=500)

@require_GET
def preview_project(request, project_id):
    """
    Preview a project's current state or a specific change.
    """
    try:
        # Get preview mode and change ID from query params
        preview_mode = request.GET.get('mode', 'current')  # current, before, after
        change_id = request.GET.get('change_id')
        
        # Get the project
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            logger.error(f"Project {project_id} not found")
            return JsonResponse({'error': 'Project not found'}, status=404)
        
        # Set up preview context
        context = {
            'project': project,
            'preview_mode': preview_mode,
            'change_id': change_id
        }
        
        # If previewing a change, add the change data
        if change_id and preview_mode in ['before', 'after']:
            try:
                change = AIChangeRequest.objects.get(id=change_id)
                diff_data = json.loads(change.diff or '{}')
                context['change'] = change
                context['diff_data'] = diff_data
            except AIChangeRequest.DoesNotExist:
                logger.error(f"Change {change_id} not found")
                return JsonResponse({'error': 'Change not found'}, status=404)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in change {change_id}")
                return JsonResponse({'error': 'Invalid change data'}, status=400)
        
        # Render the preview template
        template_path = 'preview/project.html'
        try:
            return render(request, template_path, context)
        except Exception as e:
            logger.error(f"Error rendering preview template: {str(e)}")
            return JsonResponse({'error': 'Error rendering preview'}, status=500)
        
    except Exception as e:
        logger.error(f"Error in preview_project: {str(e)}")
        logger.error(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)

def preview_project(request, project_id, preview_alias, raw_label, ai_diff_code=None):
    """
    Preview a project's current state or a specific change.
    
    Args:
        request (HttpRequest): The request object
        project_id (int): The ID of the project to preview
        preview_alias (str): The alias for the preview database
        raw_label (str): The raw label for the app
        ai_diff_code (str, optional): The AI-generated diff code to apply
    """
    try:
        # Get the project
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            logger.error(f"Project {project_id} not found")
            return JsonResponse({'error': 'Project not found'}, status=404)
        
        # Set up preview context
        context = {
            'project': project,
            'preview_alias': preview_alias,
            'raw_label': raw_label,
            'ai_diff_code': ai_diff_code
        }
        
        # If we have AI diff code, apply it to the preview
        if ai_diff_code:
            try:
                # Parse the diff code
                diff_data = json.loads(ai_diff_code)
                context['diff_data'] = diff_data
                
                # Apply changes to preview database
                with transaction.atomic(using=preview_alias):
                    # TODO: Apply changes to preview database
                    pass
                    
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in AI diff code")
                return JsonResponse({'error': 'Invalid diff data'}, status=400)
            except Exception as e:
                logger.error(f"Error applying AI diff code: {str(e)}")
                return JsonResponse({'error': 'Error applying changes'}, status=500)
        
        # Render the preview template
        template_path = 'preview/project.html'
        try:
            return render(request, template_path, context)
        except Exception as e:
            logger.error(f"Error rendering preview template: {str(e)}")
            return JsonResponse({'error': 'Error rendering preview'}, status=500)
        
    except Exception as e:
        logger.error(f"Error in preview_project: {str(e)}")
        logger.error(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)
@sync_to_async
def setup_preview_project(project_id, preview_alias, raw_label, change_id=None):
    """
    Set up a preview project with optional AI changes.
    
    Args:
        project_id (int): The ID of the project to preview
        preview_alias (str): The alias for the preview database
        raw_label (str): The raw label for the app
        change_id (int, optional): The ID of the AI change request to apply
    
    Returns:
        list: A list of modified file paths
    """
    try:
        # Get the project
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            logger.error(f"Project {project_id} not found")
            raise Http404(f"Project {project_id} not found")

        # Get AI changes if change_id provided
        modified_files = []
        if change_id:
            try:
                change = AIChangeRequest.objects.get(id=change_id)
                diff = json.loads(change.diff or "{}")
                for file_path, changes in diff.items():
                    if "after" in changes.get("preview", {}):
                        modified_files.append(file_path)
            except AIChangeRequest.DoesNotExist:
                logger.error(f"Change request {change_id} not found")
                raise Http404(f"Change request {change_id} not found")
            except Exception as e:
                logger.error(f"Error applying changes: {str(e)}")
                raise

        return modified_files

    except Exception as e:
        logger.error(f"Error in setup_preview_project: {str(e)}")
        raise

class CancelChangesAPIView(APIView):
    def post(self, request, project_id, change_id):
        try:
            # Get the change request
            change_request = AIChangeRequest.objects.get(id=change_id, project_id=project_id)
            
            # Update the status to cancelled
            change_request.status = 'cancelled'
            change_request.save()
            
            # If there's an associated conversation, update its status
            if hasattr(change_request, 'conversation') and change_request.conversation:
                change_request.conversation.status = 'cancelled'
                change_request.conversation.save()
            
            # Clean up any preview instances
            try:
                before_alias = f"preview_{project_id}_before_{change_id}"
                after_alias = f"preview_{project_id}_after_{change_id}"
                preview_manager.cleanup_preview(before_alias)
                preview_manager.cleanup_preview(after_alias)
            except Exception as e:
                logger.error(f"Error cleaning up previews: {e}")
                # Continue despite preview cleanup errors
            
            return Response({"message": "Changes cancelled successfully"}, status=status.HTTP_200_OK)
            
        except AIChangeRequest.DoesNotExist:
            return Response({"error": "Change request not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error cancelling changes: {e}")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
