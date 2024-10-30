# create_api/management/commands/generate_api.py

from django.core.management.base import BaseCommand
from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
import os

class Command(BaseCommand):
    """Custom management command to generate API resources dynamically."""

    help = 'Generates API resources for a specified model.'

    def add_arguments(self, parser):
        """Add command line arguments for model name and fields."""
        parser.add_argument('--model_name', type=str, help='Name of the model to generate API for')
        parser.add_argument('--fields', type=str, help='Comma-separated list of fields and their types')

    def handle(self, *args, **options):
        """Handle the command execution and generate the API resources."""
        model_name = options['model_name']  # Get the model name from command line arguments
        fields = options['fields'].split(',')  # Split fields by comma for processing

        # Check if model already exists
        if self.model_exists(model_name):
            self.stdout.write(self.style.ERROR(f"Model '{model_name}' already exists. Please choose a different name."))
            return

        # Generate model, serializer, viewset, and URLs dynamically based on the provided fields
        self.create_model(model_name, fields)
        self.create_serializer(model_name)
        self.create_viewset(model_name)
        self.create_urls(model_name)

    def model_exists(self, model_name):
        """Check if the model already exists in the current app."""
        return model_name in [model.__name__ for model in apps.get_models()]

    def create_model(self, model_name, fields):
        """Generate model code based on provided fields."""
        if not model_name.isidentifier():
            self.stdout.write(self.style.ERROR(f"Invalid model name: '{model_name}'. Model names must be valid Python identifiers."))
            return
        
        model_content = f"""
from django.db import models

class {model_name}(models.Model):
    \"\"\"Model representing {model_name.lower()}\"\"\"
    """
        for field in fields:
            if '=' not in field:
                self.stdout.write(self.style.ERROR(f"Invalid field format: '{field}'. Expected format is 'name=type'."))
                return
            
            name, field_type = field.split('=')
            
            if not name.isidentifier():
                self.stdout.write(self.style.ERROR(f"Invalid field name: '{name}'. Field names must be valid Python identifiers."))
                return
            
            # Correctly format the field based on the type
            if field_type == 'CharField':
                model_content += f"    {name} = models.CharField(max_length=255)  # Character field with max length 255\n"
            elif field_type == 'TextField':
                model_content += f"    {name} = models.TextField()  # Large text field\n"
            elif field_type == 'IntegerField':
                model_content += f"    {name} = models.IntegerField()  # Integer field\n"
            elif field_type == 'FloatField':
                model_content += f"    {name} = models.FloatField()  # Float field\n"
            elif field_type == 'BooleanField':
                model_content += f"    {name} = models.BooleanField(default=False)  # Boolean field\n"
            elif field_type == 'DateField':
                model_content += f"    {name} = models.DateField()  # Date field\n"
            elif field_type == 'DateTimeField':
                model_content += f"    {name} = models.DateTimeField(auto_now_add=True)  # DateTime field\n"
            elif field_type == 'EmailField':
                model_content += f"    {name} = models.EmailField()  # Email field\n"
            elif field_type == 'URLField':
                model_content += f"    {name} = models.URLField()  # URL field\n"
            elif field_type == 'DecimalField':
                model_content += f"    {name} = models.DecimalField(max_digits=10, decimal_places=2)  # Decimal field\n"
            elif field_type == 'TimeField':
                model_content += f"    {name} = models.TimeField()  # Time field\n"
            elif field_type == 'DurationField':
                model_content += f"    {name} = models.DurationField()  # Duration field\n"
            elif field_type == 'FileField':
                model_content += f"    {name} = models.FileField(upload_to='uploads/')  # File upload field\n"
            elif field_type == 'ImageField':
                model_content += f"    {name} = models.ImageField(upload_to='images/')  # Image upload field\n"
            elif field_type == 'SlugField':
                model_content += f"    {name} = models.SlugField()  # Slug field\n"
            elif field_type == 'UUIDField':
                model_content += f"    {name} = models.UUIDField()  # UUID field\n"
            elif field_type == 'PositiveIntegerField':
                model_content += f"    {name} = models.PositiveIntegerField()  # Positive integer field\n"
            elif field_type == 'PositiveSmallIntegerField':
                model_content += f"    {name} = models.PositiveSmallIntegerField()  # Positive small integer field\n"
            elif field_type == 'SmallIntegerField':
                model_content += f"    {name} = models.SmallIntegerField()  # Small integer field\n"
            elif field_type == 'BigIntegerField':
                model_content += f"    {name} = models.BigIntegerField()  # Big integer field\n"
            elif field_type == 'JSONField':
                model_content += f"    {name} = models.JSONField()  # JSON field\n"
            elif field_type == 'ForeignKey':
                related_model = input(f"Enter the related model for {name}: ")
                model_content += f"    {name} = models.ForeignKey('{related_model}', on_delete=models.CASCADE)  # Foreign key field\n"
            elif field_type == 'OneToOneField':
                related_model = input(f"Enter the related model for {name}: ")
                model_content += f"    {name} = models.OneToOneField('{related_model}', on_delete=models.CASCADE)  # One-to-one field\n"
            elif field_type == 'ManyToManyField':
                related_model = input(f"Enter the related model for {name}: ")
                model_content += f"    {name} = models.ManyToManyField('{related_model}')  # Many-to-many field\n"
            else:
                self.stdout.write(self.style.ERROR(f"Field type '{field_type}' is not recognized."))
                return

        model_content += f"""
    def __str__(self):
        \"\"\"Return a string representation of the model.\"\"\"
        return self.{fields[0].split('=')[0]}  # Return the first field as the string representation
"""
        # Write to models.py with error handling
        try:
            with open('create_api/models.py', 'a') as f:
                f.write(model_content)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to write model to file: {e}"))

    def create_serializer(self, model_name):
        """Generate serializer code for the specified model."""
        serializer_content = f"""from rest_framework import serializers
from .models import {model_name}  # Import the model for serialization

class {model_name}Serializer(serializers.ModelSerializer):
    \"\"\"Serializer class for the {model_name} model.\"\"\"
    
    class Meta:
        model = {model_name}  # Specify the model to serialize
        fields = '__all__'  # Include all fields in the serialized output
"""
        # Write to serializers.py with error handling
        try:
            with open('create_api/serializers.py', 'a') as f:
                f.write(serializer_content)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to write serializer to file: {e}"))

    def create_viewset(self, model_name):
        """Generate viewset code for the specified model."""
        viewset_content = f"""from rest_framework import viewsets
from .models import {model_name}  # Import the model for the viewset
from .serializers import {model_name}Serializer  # Import the corresponding serializer

class {model_name}ViewSet(viewsets.ModelViewSet):
    \"\"\"ViewSet for the {model_name} model, providing default CRUD operations.\"\"\"
    
    queryset = {model_name}.objects.all()  # Query all instances of the model
    serializer_class = {model_name}Serializer  # Specify the serializer to use
"""
        # Write to views.py with error handling
        try:
            with open('create_api/views.py', 'a') as f:
                f.write(viewset_content)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to write viewset to file: {e}"))

    def create_urls(self, model_name):
        """Generate URL routing code for the specified model's viewset."""
        url_content = f"""from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import {model_name}ViewSet  # Import the viewset

# Create a router for automatic URL routing
router = DefaultRouter()
router.register(r'{model_name.lower()}', {model_name}ViewSet)  # Register the viewset with the router

urlpatterns = [
    path('', include(router.urls)),  # Include the router URLs
]
"""
        # Write to urls.py with error handling
        try:
            with open('create_api/urls.py', 'a') as f:
                f.write(url_content)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to write URLs to file: {e}"))

    def test_generated_code(self, model_name):
        """Placeholder for automated tests after generating code."""
        # Implement automated tests to validate generated code behavior
        self.stdout.write(self.style.WARNING("Automated tests need to be implemented for the generated code."))
