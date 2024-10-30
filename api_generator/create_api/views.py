# create_api/views.py
from rest_framework import generics,serializers
from django.contrib.auth.models import User
from rest_framework.response import Response
from .serializers import UserSerializer, UserModelSerializer
from django.http import JsonResponse
from django.db import models, connection
from django.db.models import fields
from rest_framework import status
import logging
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from django.core.management import call_command
from io import StringIO
from django.apps import apps
from .models import UserModel
from rest_framework import viewsets


logger = logging.getLogger(__name__)

class CurrentUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        serializer = UserSerializer(user)  # Serialize the user information
        
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
               return Response({'status': 'Error', 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

def create_model(model_name, fields):
    # Dynamically create a model
    attrs = {field['name']: getattr(models, field['type'])() for field in fields}
    new_model = type(model_name, (models.Model,), attrs)

    # Register the model with the database
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(new_model)

    return new_model

# Create API to handle dynamic model creation
def create_model_view(request):
    if request.method == 'POST':
        model_name = request.POST.get('model_name')
        fields = request.POST.getlist('fields')

        # Validate model name and fields here (add your own validation logic)
        if not model_name or not fields:
            return JsonResponse({'status': 'Error', 'message': 'Model name and fields are required.'}, status=400)

        new_model = create_model(model_name, fields)
        return JsonResponse({'status': 'Model created successfully', 'model': model_name})

def field_types_view(request):
    all_fields = [field.__name__ for field in models.Field.__subclasses__()]
    return JsonResponse({'field_types': all_fields})

class GenerateAPIView(APIView):
    """API View to generate API resources dynamically."""
    
    def post(self, request):
        model_name = request.data.get('model_name')
        fields = request.data.get('fields')
        
        if not model_name or not fields:
            return Response({'error': 'Model name and fields are required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Prepare to capture the management command output
        out = StringIO()
        
        try:
            call_command('generate_api', model_name=model_name, fields=fields, stdout=out)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'message': out.getvalue()}, status=status.HTTP_200_OK)




class AvailableModelsAPIView(APIView):
    """API View to fetch all models and their fields."""
    permission_classes = [AllowAny]
    def get(self, request):
        models_data = {}
        # Get all models and their fields
        for model in apps.get_models():
            fields = [field.name for field in model._meta.get_fields()]
            models_data[model.__name__] = fields
        return Response(models_data, status=200)


class UserModelViewSet(viewsets.ModelViewSet):
    queryset = UserModel.objects.all()
    serializer_class = UserModelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Get the query parameter to filter models
        filter_type = self.request.query_params.get('filter_type', None)

        if filter_type == 'my_models':
            # Return only the authenticated user's models
            return self.queryset.filter(user=user)
        elif filter_type == 'other_models':
            # Return only models from other users
            return self.queryset.exclude(user=user)
        else:
            # Default behavior: return both user's models and public models
            return self.queryset.filter(models.Q(user=user) | models.Q(visibility='public'))

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)  # Set the user automatically

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
