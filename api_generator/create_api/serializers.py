from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (UserModel, Project, ModelFile, App, ViewFile, FormFile, ProjectFile, URLFile, 
SettingsFile, TemplateFile,AppFile,StaticFile,MediaFile, AIConversation, AIMessage, AIChangeRequest
)
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['username', 'email', 'password']
        extra_kwargs = {
            'password': {'write_only': True},
            'email': {'required': True}
        }

    def create(self, validated_data):
        user = User(
            username=validated_data['username'],
            email=validated_data['email']
        )
        user.set_password(validated_data['password'])
        user.save()
        return user

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

class UserModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserModel
        fields = ['id', 'user', 'model_name', 'visibility', 'created_at', 'full_code']
        read_only_fields = ['user', 'created_at']

    def validate(self, data):
        user = self.context['request'].user
        model_name = data.get('model_name')
        if self.instance is None and UserModel.objects.filter(user=user, model_name=model_name).exists():
            raise serializers.ValidationError({"model_name": "You already have a model with this name."})
        return data

    def update(self, instance, validated_data):
        instance.model_name = validated_data.get('model_name', instance.model_name)
        instance.visibility = validated_data.get('visibility', instance.visibility)
        if 'full_code' in validated_data:
            instance.full_code = validated_data['full_code']
        instance.save()
        return instance

class ViewFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ViewFile
        fields = ['id', 'content', 'diagram', 'description', 'summary', 'created_at', 'app', 'view_summaries']

# serializers.py
class ModelFileSerializer(serializers.ModelSerializer):
    app = serializers.PrimaryKeyRelatedField(
        queryset=App.objects.all(),
        error_messages={'does_not_exist': 'App not found or not owned by user.'}
    )
    model_summaries = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = ModelFile
        fields = ['id', 'app', 'project', 'content', 'diagram', 'description', 'summary','model_summaries']
        read_only_fields = ['project']

    def validate_app(self, value):
        user = self.context['request'].user
        if value.project.user != user:
            raise serializers.ValidationError("App not found or not owned by user.")
        return value

class FormFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormFile
        fields = [
            'id',
            'app',
            'content',
            'diagram',
            'description',
            'summary',
            'created_at',
            'form_summaries',
            
        ]

class TemplateFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = TemplateFile
        fields = ['id', 'path', 'name', 'content', 'description', 'created_at', 'is_app_template']


class StaticFileSerializer(serializers.ModelSerializer):
    # expose the uploaded file URL
    file = serializers.FileField(use_url=True)

    class Meta:
        model = StaticFile
        fields = [
            'id', 'path', 'name', 'file_type',
            'file',           # ← NEW
            'description', 'created_at',
            'project', 
        ]
        read_only_fields = ['created_at']


class MediaFileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(use_url=True)

    class Meta:
        model = MediaFile
        fields = [
            'id', 'path', 'name', 'file_type',
            'file',           # ← NEW
            'description', 'created_at',
            'project', 
        ]
        read_only_fields = ['created_at']

class AppFileSerializer(serializers.ModelSerializer):
    project = serializers.PrimaryKeyRelatedField(read_only=True)  # No queryset needed
    
    class Meta:
        model = AppFile
        fields = '__all__'

class URLFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = URLFile
        fields = ['id', 'name', 'path', 'content', 'created_at','project','app',]

        
class AppSerializer(serializers.ModelSerializer):
    model_files = ModelFileSerializer(many=True, read_only=True)
    view_files = ViewFileSerializer(many=True, read_only=True)
    form_files = FormFileSerializer(many=True, read_only=True)
    template_files = TemplateFileSerializer(source='app_template_files', many=True, read_only=True)
    app_files = AppFileSerializer(many=True, read_only=True)
    app_url_files = URLFileSerializer(many=True, read_only=True, required=False)  # Make it optional

    class Meta:
        model = App
        fields = [
            'id', 'project', 'name', 'description',
            'model_files', 'view_files', 'form_files',
            'template_files', 'app_files', 'app_url_files'
        ]


class SettingsFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SettingsFile
        fields = ['id', 'name', 'path', 'content', 'created_at','project']



class ProjectFileSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = ProjectFile
        fields = ['id', 'name', 'path', 'content', 'created_at','project']
class ProjectSerializer(serializers.ModelSerializer):
    apps = AppSerializer(many=True, read_only=True)
    settings_files = SettingsFileSerializer(many=True, read_only=True)
    url_files     = URLFileSerializer(many=True, read_only=True)
    project_files = ProjectFileSerializer(many=True, read_only=True)
    # ← Add these three:
    template_files = TemplateFileSerializer(many=True, read_only=True)
    static_files   = StaticFileSerializer(many=True, read_only=True)
    media_files    = MediaFileSerializer(many=True, read_only=True)
    class Meta:
        model = Project
        fields = [
            'id','user','name','description','visibility','created_at',
            'apps','settings_files','template_files','static_files',
            'media_files','url_files','project_files'
        ]

    def create(self, validated_data):
        # Assign the user from the request to the project
        user = self.context['request'].user
        validated_data['user'] = user  # Ensure the user is set
        return super().create(validated_data)



class AIMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIMessage
        fields = ['id','sender','text','timestamp']

class AIChangeRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIChangeRequest
        fields = ['id','file_type','app_name','file_path','diff','status','created_at']

class AIConversationSerializer(serializers.ModelSerializer):
    messages = AIMessageSerializer(many=True, read_only=True)
    changes  = AIChangeRequestSerializer(many=True, read_only=True)

    class Meta:
        model = AIConversation
        fields = [
            'id','project','app_name','file_path','user','status',
            'created_at','updated_at','messages','changes'
        ]
        read_only_fields = ['user','status','created_at','updated_at']