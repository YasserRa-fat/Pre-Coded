from django.db import models
from django.contrib.auth.models import User
import os

# -------------------------------------------------------------------
# Utility Models
# -------------------------------------------------------------------
class Tag(models.Model):
    """
    Tag model for categorizing projects, apps, and files.
    """
    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tag"
        verbose_name_plural = "Tags"
        ordering = ["name"]

    def __str__(self):
        return self.name

# -------------------------------------------------------------------
# Core Models
# -------------------------------------------------------------------
VISIBILITY_CHOICES = [
    ('private', 'Private'),
    ('public', 'Public'),
]

class UserModel(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    model_name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='private')
    full_code = models.TextField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.model_name

class Project(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='private')
    description = models.TextField(null=True, blank=True)

    keywords = models.TextField(blank=True, default='', help_text="Searchable keywords")
    project_hash = models.CharField(max_length=64, blank=True, null=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name='projects')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'name')
        indexes = [
            models.Index(fields=['user', 'name']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.name

class App(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="apps")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    keywords = models.TextField(blank=True, default='', help_text="Searchable keywords")
    app_hash = models.CharField(max_length=64, blank=True, null=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name='apps')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('project', 'name')
        indexes = [
            models.Index(fields=['project', 'name']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.name} (in {self.project.name})"

# -------------------------------------------------------------------
# Abstract base for all code- and file-types
# -------------------------------------------------------------------
class CodeFile(models.Model):
    path = models.CharField(max_length=512, help_text="Relative path from project root")
    name = models.CharField(max_length=255)
    content = models.TextField(blank=True)
    description = models.TextField(blank=True)

    is_folder = models.BooleanField(default=False)
    parent_folder = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='children'
    )

    keywords = models.TextField(blank=True, default='', help_text="Searchable keywords")
    content_hash = models.CharField(max_length=64, blank=True, null=True)
    # dynamic related_name: Tag.modelfiles, Tag.viewfiles, Tag.formfiles, etc.
    tags = models.ManyToManyField(
        Tag,
        blank=True,
        related_name='%(class)ss',
        related_query_name='%(class)s'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['path']
        indexes = [
            models.Index(fields=['path']),
            models.Index(fields=['is_folder']),
        ]

# -------------------------------------------------------------------
# Specific file types
# -------------------------------------------------------------------
# create_api/models.py

class ModelFile(CodeFile):
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="model_files")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="project_model_files")
    diagram = models.JSONField(null=True, blank=True)
    summary = models.TextField(blank=True)
    model_summaries = models.JSONField(default=dict, blank=True, null=True)

    class Meta:
        unique_together = ('app', 'name')      # ← enforce at the DB level
        indexes = [
            models.Index(fields=['app', 'name']),
        ]

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

class ProjectFile(CodeFile):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='project_files')

    def __str__(self):
        return f"ProjectFile: {self.path}"

class SettingsFile(CodeFile):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='settings_files')

    def __str__(self):
        return f"SettingsFile: {self.name}"

class URLFile(CodeFile):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='url_files')
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='app_url_files', null=True, blank=True)

    def __str__(self):
        return f"URLFile: {self.name}"

class TemplateFile(CodeFile):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='template_files')
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='app_template_files', null=True, blank=True)
    is_app_template = models.BooleanField(default=False)

    def __str__(self):
        loc = "App" if self.is_app_template else "Project"
        return f"{loc}Template: {self.path}"

def project_upload_to(instance, filename):
    base = f"projects/{instance.project.id}"
    return os.path.join(base, filename)

class StaticFile(CodeFile):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='static_files')
    file_type = models.CharField(max_length=50, choices=[('css', 'CSS'), ('js', 'JavaScript'), ('img', 'Image'), ('other', 'Other')])
    file = models.FileField(upload_to=project_upload_to)

    def __str__(self):
        return f"StaticFile: {self.path} ({self.file_type})"

class MediaFile(CodeFile):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='media_files')
    file_type = models.CharField(max_length=50, choices=[('image', 'Image'), ('video', 'Video'), ('doc', 'Document'), ('other', 'Other')])
    file = models.FileField(upload_to=project_upload_to)

    def __str__(self):
        return f"MediaFile: {self.path} ({self.file_type})"

class AppFile(CodeFile):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='app_files')
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name='app_files')

    def __str__(self):
        return f"AppFile: {self.app.name}/{self.path}"

# -------------------------------------------------------------------
# AI Conversation Models
# -------------------------------------------------------------------
class AIConversation(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('awaiting_clarification', 'Awaiting Clarification'),
        ('review', 'Review Diff'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='ai_conversations')
    app_name = models.CharField(max_length=100, blank=True, null=True)
    file_path = models.CharField(max_length=512, blank=True, null=True)
    file_type = models.CharField(
    max_length=32,
    choices=[
        ('template', 'Template'),
        ('model',    'Model'),
        ('view',     'View'),
        ('form',     'Form'),
        ('app',      'New App'),
        ('other',    'Other'),
    ],
    blank=True,
    null=True,
    help_text='Type of file being edited'
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class AIMessage(models.Model):
    SENDER_CHOICES = [('user', 'User'), ('assistant', 'Assistant')]
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.CharField(max_length=16, choices=SENDER_CHOICES)
    text = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

class AIChangeRequest(models.Model):
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name='changes')
    file_type = models.CharField(max_length=32, choices=[
        ('template', 'Template'),
        ('model', 'Model'),
        ('view', 'View'),
        ('form', 'Form'),
        ('app', 'New App'),
        ('other', 'Other')
    ])
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    file_path = models.CharField(max_length=512, blank=True, null=True)
    diff = models.TextField()
    files        = models.JSONField(default=list, help_text="List of file paths this diff applies to")
    status = models.CharField(max_length=16, choices=[
        ('draft', 'Draft'),
        ('applied', 'Applied'),
        ('rejected', 'Rejected')
    ], default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    app_name = models.CharField(
        max_length=100,
        null=False,
        blank=False,
        help_text="The Django app label (e.g. 'project_1_posts') this change targets"
    )
    def __str__(self):
        return f"ChangeRequest {self.id} ({self.status})"
    def save(self, *args, **kwargs):
        print(f"Saving ChangeRequest {self.id}")
        super().save(*args, **kwargs)