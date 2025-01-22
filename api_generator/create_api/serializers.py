from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserModel
from .utils import parse_code_with_comments, generate_code_from_json

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
        fields = ['id', 'user', 'model_name', 'fields', 'visibility', 'created_at','full_code']  # Include 'comments' if not yet done
        read_only_fields = ['user', 'created_at']

    def validate(self, data):
        user = self.context['request'].user
        model_name = data.get('model_name')

        if self.instance is None and UserModel.objects.filter(user=user, model_name=model_name).exists():
            raise serializers.ValidationError({"model_name": "You already have a model with this name."})

        return data

    def create(self, validated_data):
        fields = validated_data.pop('fields', [])
        # Ensure the fields are valid if necessary
        validated_data['fields'] = fields
        # Add any parsing logic if necessary
        return super().create(validated_data)
  
    def update(self, instance, validated_data):
        code = validated_data.pop('code', '')
        if code:
            parsed_json = parse_code_with_comments(code)
            validated_data['fields'] = parsed_json['fields']  # Should include comments
        print("Validated data in update:", validated_data) 
        instance.model_name = validated_data.get('model_name', instance.model_name)
        instance.visibility = validated_data.get('visibility', instance.visibility)
        instance.fields = validated_data.get('fields', instance.fields)
        full_code = validated_data.pop('full_code', None)
        if full_code:
           instance.full_code = full_code
        # Saving the instance
        instance.save()
        return instance


