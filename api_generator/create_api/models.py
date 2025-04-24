from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
import os
# Create your models here.
VISIBILITY_CHOICES = [
        ('private', 'Private'),
        ('public', 'Public'),
    ]
class UserModel(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    model_name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='private')
    full_code = models.TextField(null=True)  # Now stores the entire code as a string
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.model_name


class Project(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE)
    name        = models.CharField(max_length=255)
    visibility  = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='private')
    description = models.TextField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class App(models.Model):
    project     = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="apps")
    name        = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    class Meta:
         unique_together = ('project', 'name')  
    def __str__(self):
        return f"{self.name} (in {self.project.name})"


# -------------------------------------------------------------------
# Abstract base for all “code‐file” types
# -------------------------------------------------------------------
class CodeFile(models.Model):
    path        = models.CharField(max_length=512, help_text="Relative path from project root")
    name        = models.CharField(max_length=255)
    content     = models.TextField()
    description = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

class ModelFile(CodeFile):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="model_files")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="project_model_files")
    diagram = models.JSONField(null=True, blank=True)
    summary = models.TextField(blank=True)
    model_summaries = models.JSONField(default=dict, blank=True, null=True)

    def __str__(self):
        return f"ModelFile: {self.app.name}/{self.name}"


class ViewFile(CodeFile):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="view_files")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="project_view_files")
    model_file = models.ForeignKey(ModelFile, on_delete=models.SET_NULL, null=True, blank=True, related_name="view_files")
    diagram = models.JSONField(null=True, blank=True)
    summary = models.TextField(blank=True)
    view_summaries = models.JSONField(default=dict, blank=True, null=True)

    def __str__(self):
        return f"ViewFile: {self.app.name}/{self.name}"


class FormFile(CodeFile):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="form_files")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="project_form_files")
    diagram = models.JSONField(null=True, blank=True)
    summary = models.TextField(blank=True)
    form_summaries = models.JSONField(default=dict, blank=True, null=True)

    def __str__(self):
        return f"FormFile: {self.app.name}/{self.name}"

# -------------------------------------------------------------------
# Project‐level files
# -------------------------------------------------------------------
class ProjectFile(CodeFile):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='project_files'
    )

    def __str__(self):
        return f"ProjectFile: {self.path}"


class SettingsFile(CodeFile):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='settings_files'
    )

    def __str__(self):
        return f"SettingsFile: {self.name}"


class URLFile(CodeFile):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='url_files'
    )
    app = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name='app_url_files',
        null=True,
        blank=True
    )

    def __str__(self):
        return f"URLFile: {self.name}"



# -------------------------------------------------------------------
# Templates, Static & Media can be either project‐ or app‐level
# -------------------------------------------------------------------
class TemplateFile(CodeFile):
    project          = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='template_files'
    )
    app              = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name='app_template_files',
        null=True,
        blank=True
    )
    is_app_template  = models.BooleanField(default=False)

    def __str__(self):
        loc = "App" if self.is_app_template else "Project"
        return f"{loc}Template: {self.path}"


def project_upload_to(instance, filename):
    # store under MEDIA_ROOT/projects/<project_id>/… 
    base = f"projects/{instance.project.id}"
    return os.path.join(base, filename)

class StaticFile(CodeFile):
    project   = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='static_files'
    )

    file_type = models.CharField(max_length=50, choices=[
        ('css', 'CSS'),
        ('js',  'JavaScript'),
        ('img', 'Image'),
        ('other','Other')
    ])
    file      = models.FileField(upload_to=project_upload_to)

    def __str__(self):
        return f"StaticFile: {self.path} ({self.file_type})"


class MediaFile(CodeFile):
    project   = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='media_files'
    )

    file_type = models.CharField(max_length=50, choices=[
        ('image','Image'),
        ('video','Video'),
        ('doc',  'Document'),
        ('other','Other')
    ])
    file      = models.FileField(upload_to=project_upload_to)

    def __str__(self):
        return f"MediaFile: {self.path} ({self.file_type})"

# -------------------------------------------------------------------
# Generic “code file” for any additional app‐level python files
# -------------------------------------------------------------------
class AppFile(CodeFile):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='app_files'
    )
    app     = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name='app_files'
    )

    def __str__(self):
        return f"AppFile: {self.app.name}/{self.path}"
