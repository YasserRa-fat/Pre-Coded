from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserModel

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
        """Check if the email is already in use."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

class UserModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserModel
        fields = ['id', 'user', 'model_name', 'fields', 'visibility', 'created_at']
        read_only_fields = ['user', 'created_at']

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['user'] = user  # Associate the model with the current user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if not instance:
            raise serializers.ValidationError("Model instance does not exist.")
        instance.model_name = validated_data.get('model_name', instance.model_name)
        instance.fields = validated_data.get('fields', instance.fields)
        instance.visibility = validated_data.get('visibility', instance.visibility)
        instance.save()
        return instance
