import os
import shutil
import tempfile
import logging
from django.conf import settings
from django.db.models.signals import post_save, pre_delete, post_migrate
from django.dispatch import receiver
from django.core.management import call_command
from django.db import transaction
from django.db import models
import time
from create_api.models import (
    Project, App,
    ProjectFile, AppFile,
    TemplateFile, SettingsFile, URLFile,
    StaticFile, MediaFile, ModelFile, ViewFile, FormFile
)

logger = logging.getLogger(__name__)

def initialize_project(project):
    """Initialize a newly created project with apps and migrations"""
    from core.startup import dynamic_register_apps, dynamic_register_and_dump
    
    # Register and dump apps
    dynamic_register_apps()
    dynamic_register_and_dump()
    
    # Create a dummy model file to trigger migrations if no apps exist yet
    if not project.apps.exists():
        with tempfile.TemporaryDirectory() as temp_dir:
            app_name = 'core'
            app = App.objects.create(project=project, name=app_name)
            
            # Create a basic models.py
            models_content = '''from django.db import models

# Core app models
class CoreConfig(models.Model):
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
'''
            models_path = os.path.join(temp_dir, 'models.py')
            with open(models_path, 'w') as f:
                f.write(models_content)
                  
            # Save it as a ModelFile
            write_codefile(ModelFile, project, app, f'{app_name}/models.py', models_path)

    # Run migrations for all apps in the project
    db_alias = f"project_{project.id}"
    for app in project.apps.all():
        label = f"project_{project.id}_{app.name}"
        try:
            call_command('makemigrations', label, interactive=False, verbosity=1)
            call_command('migrate', label, database=db_alias, interactive=False, verbosity=1)
        except Exception as e:
            logger.error(f"Error during initial migration for {label}: {e}")

def write_codefile(model, project, app, rel_path, real_path, **extra):
    """
    Read the file on disk, then create `model` with exactly the fields
    it actually defines (no spurious `app=None` on project-only models).
    """
    with open(real_path, encoding='utf-8') as f:
        content = f.read()

    kwargs = {
        'project': project,
        'path': rel_path.replace(os.sep, '/'),
        'name': os.path.basename(rel_path),
        'content': content,
        **extra,
    }

    field_names = {f.name for f in model._meta.get_fields()}
    if 'app' in field_names and app is not None:
        kwargs['app'] = app

    model.objects.create(**kwargs)


@receiver(post_save, sender=Project)
def create_project_skeleton(sender, instance, created, **kwargs):
    if not created:
        return
    with tempfile.TemporaryDirectory() as temp_dir:
        call_command('startproject', instance.name, temp_dir)
        project_root = os.path.join(temp_dir, instance.name)
        manage_py = os.path.join(temp_dir, 'manage.py')

        if os.path.exists(manage_py):
            write_codefile(ProjectFile, instance, None, 'manage.py', manage_py)

        for fname in ('__init__.py', 'settings.py', 'urls.py', 'wsgi.py', 'asgi.py'):
            real = os.path.join(project_root, fname)
            if not os.path.exists(real):
                continue
            if fname == 'urls.py' and URLFile.objects.filter(
                    project=instance, app__isnull=True, name='urls.py'
                ).exists():
                continue

            model = {
                'settings.py': SettingsFile,
                'urls.py': URLFile,
            }.get(fname, ProjectFile)

            rel_path = os.path.join(instance.name, fname)
            write_codefile(model, instance, None, rel_path, real)
            
    # After project creation, register apps and run initial migrations
    transaction.on_commit(lambda: initialize_project(instance))


@receiver(post_save, sender=App)
def create_app_skeleton(sender, instance, created, **kwargs):
    if not created:
        return
    with tempfile.TemporaryDirectory() as temp_dir:
        app_dir = os.path.join(temp_dir, instance.name)
        os.makedirs(app_dir, exist_ok=True)
        call_command('startapp', instance.name, app_dir)

        for rel in ('__init__.py', 'admin.py', 'apps.py', 'models.py', 'tests.py', 'views.py', 'urls.py', 'forms.py'):
            real = os.path.join(app_dir, rel)
            if rel == 'urls.py' and URLFile.objects.filter(
                    project=instance.project, app=instance, name='urls.py'
                ).exists():
                continue

            if not os.path.exists(real):
                stub = None
                if rel == 'forms.py': 
                    stub = '# Sample forms.py content'
                elif rel == 'urls.py': 
                    stub = 'from django.urls import path\n\nurlpatterns = []\n'
                elif rel == 'models.py':
                    # Create a models.py with proper User model imports and settings
                    stub = '''from django.db import models
from django.conf import settings

# Example model with proper User relationship settings
class ExampleModel(models.Model):
    # Example of how to properly set up User relationships
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='+',  # Disable reverse relation
        db_constraint=False  # Disable DB-level foreign key constraint
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Add any model meta options here
        pass
'''
                if stub:
                    with open(real, 'w', encoding='utf-8') as f:
                        f.write(stub)

            model = {
                'models.py': ModelFile,
                'views.py': ViewFile,
                'forms.py': FormFile,
                'urls.py': URLFile,
            }.get(rel, AppFile)
            write_codefile(model, instance.project, instance, os.path.join(instance.name, rel), real)

        mig_init = os.path.join(app_dir, 'migrations', '__init__.py')
        if not os.path.exists(mig_init):
            os.makedirs(os.path.dirname(mig_init), exist_ok=True)
            with open(mig_init, 'w', encoding='utf-8') as f:
                f.write('# Migrations package init')
            write_codefile(AppFile, instance.project, instance, os.path.join(instance.name, 'migrations', '__init__.py'), mig_init)

        for folder_name, model, extra in [
            ('templates', TemplateFile, {'is_app_template': True}),
            ('static', StaticFile, {'file_type': 'other'}),
            ('media', MediaFile, {'file_type': 'other'}),
        ]:
            root = os.path.join(app_dir, folder_name)
            if not os.path.isdir(root):
                os.makedirs(root, exist_ok=True)
            for dirpath, _, files in os.walk(root):
                for fn in files:
                    real = os.path.join(dirpath, fn)
                    rel = os.path.relpath(real, temp_dir)
                    write_codefile(model, instance.project, instance, rel, real, **extra)


@receiver(post_save, sender=ModelFile)
def rebuild_and_migrate(sender, instance, created, **kwargs):
    # Only rebuild if this is a models.py file or if it's a new file
    if not (created or instance.path.endswith('models.py')):
        return
        
    # refresh dynamic apps on disk
    from core.startup import dynamic_register_apps, dynamic_register_and_dump
    dynamic_register_apps()
    dynamic_register_and_dump()
    
    # Only make and apply migrations if this is a models.py file
    if instance.path.endswith('models.py'):
        transaction.on_commit(lambda: _make_and_apply(instance))

def _make_and_apply(instance):
    project_id = instance.project_id
    db_alias = f"project_{project_id}"
    
    # Get all apps for this project
    apps_to_migrate = App.objects.filter(project_id=project_id)
    
    # First check which apps need migrations
    apps_needing_migrations = []
    for app in apps_to_migrate:
        label = f"project_{project_id}_{app.name}"
        try:
            # Use --dry-run to check if migrations are needed
            from io import StringIO
            import sys
            output = StringIO()
            sys.stdout = output
            call_command('makemigrations', label, dry_run=True, verbosity=1)
            sys.stdout = sys.__stdout__
            
            if "No changes detected" not in output.getvalue():
                apps_needing_migrations.append(app)
        except Exception as e:
            logger.error(f"Error checking migrations for '{label}': {e}")
            continue
    
    if not apps_needing_migrations:
        logger.info("No migrations needed for any apps")
        return
        
    # Make migrations only for apps that need them
    for app in apps_needing_migrations:
        label = f"project_{project_id}_{app.name}"
        try:
            logger.info(f"Making migrations for {label}")
            call_command('makemigrations', label, interactive=False, verbosity=1)
        except Exception as e:
            logger.error(f"Error making migrations for '{label}': {e}")
            continue
    
    # Then apply all migrations to ensure consistency
    try:
        logger.info(f"Applying migrations for project {project_id}")
        # Apply migrations for the whole project database
        call_command('migrate', database=db_alias, interactive=False, verbosity=1)
    except Exception as e:
        logger.error(f"Error applying migrations: {e}")
        # If migration fails, try individual apps
        for app in apps_to_migrate:
            label = f"project_{project_id}_{app.name}"
            try:
                call_command('migrate', label, database=db_alias, interactive=False, verbosity=1)
            except Exception as e:
                logger.error(f"Error applying migrations for '{label}': {e}")
                continue


@receiver(post_save)
def sync_mediafile_on_save(sender, instance, **kwargs):
    label = getattr(sender._meta, 'app_label', '')
    if not label.startswith('project_'):
        return
    parts = label.split('_')
    project = None
    if len(parts) >= 2 and parts[1].isdigit():
        from create_api.models import Project as _P
        project = _P.objects.filter(id=int(parts[1])).first()
    for field in instance._meta.get_fields():
        if isinstance(field, models.FileField):
            val = getattr(instance, field.name)
            if val and hasattr(val, 'name') and val.name:
                MediaFile.objects.update_or_create(
                    path=val.name,
                    defaults={'file': val.name, 'project': project}
                )


@receiver(pre_delete)
def delete_mediafile_on_delete(sender, instance, **kwargs):
    label = getattr(sender._meta, 'app_label', '')
    if not label.startswith('project_'):
        return
    for field in instance._meta.get_fields():
        if isinstance(field, models.FileField):
            val = getattr(instance, field.name)
            if val and val.name:
                MediaFile.objects.filter(path=val.name).delete()


@receiver(post_migrate)
def load_projects_after_migrations(sender, **kwargs):
    for proj in Project.objects.all():
        logger.info(f"Loaded project: {proj.name}")

def ensure_proper_user_relationships(content):
    """
    Ensures model file content has proper User relationship settings.
    Returns (modified_content, was_modified)
    """
    import ast
    import astor  # You'll need to add astor to requirements.txt
    
    was_modified = False
    try:
        # Parse the content
        tree = ast.parse(content)
        
        class UserFieldTransformer(ast.NodeTransformer):
            def visit_Call(self, node):
                # Check if this is a ForeignKey or OneToOneField to User
                if (isinstance(node.func, ast.Attribute) and 
                    isinstance(node.func.value, ast.Name) and
                    node.func.value.id == 'models' and
                    node.func.attr in ('ForeignKey', 'OneToOneField')):
                    
                    # Check if this field references the User model
                    is_user_field = False
                    for arg in node.args:
                        if (isinstance(arg, ast.Attribute) and 
                            isinstance(arg.value, ast.Name) and
                            arg.value.id == 'settings' and
                            arg.attr == 'AUTH_USER_MODEL'):
                            is_user_field = True
                            break
                    
                    if is_user_field:
                        # Get existing keyword arguments
                        kwargs = {kw.arg: kw.value for kw in node.keywords}
                        
                        # Add or update required settings
                        modified = False
                        if 'related_name' not in kwargs or astor.to_source(kwargs['related_name']).strip("'") != '+':
                            kwargs['related_name'] = ast.Constant(value='+')
                            modified = True
                        
                        if 'db_constraint' not in kwargs or astor.to_source(kwargs['db_constraint']).strip() != 'False':
                            kwargs['db_constraint'] = ast.Constant(value=False)
                            modified = True
                        
                        if modified:
                            nonlocal was_modified
                            was_modified = True
                            # Rebuild the node with updated kwargs
                            new_keywords = [ast.keyword(arg=k, value=v) for k, v in kwargs.items()]
                            return ast.Call(
                                func=node.func,
                                args=node.args,
                                keywords=new_keywords
                            )
                
                return self.generic_visit(node)
        
        # Apply the transformation
        tree = UserFieldTransformer().visit(tree)
        if was_modified:
            # Generate the modified source code
            return astor.to_source(tree), True
            
    except Exception as e:
        logger.error(f"Error processing model content: {e}")
        return content, False
        
    return content, False

@receiver(post_save, sender=ModelFile)
def ensure_model_settings(sender, instance, created, **kwargs):
    """Ensures model files have proper User relationship settings"""
    if not instance.path.endswith('models.py'):
        return
        
    modified_content, was_modified = ensure_proper_user_relationships(instance.content)
    if was_modified:
        # Update the model file with the modified content
        instance.content = modified_content
        instance.save()  # This will trigger rebuild_and_migrate through the post_save signal

def check_and_apply_migrations():
    """Check and apply any pending migrations for all projects"""
    from django.db.migrations.executor import MigrationExecutor
    from django.db import connections
    from django.apps import apps
    
    # Get all project databases
    project_dbs = [alias for alias in connections.databases.keys() if alias.startswith('project_')]
    
    for db_alias in project_dbs:
        try:
            connection = connections[db_alias]
            executor = MigrationExecutor(connection)
            
            # Get all apps for this project
            project_id = int(db_alias.split('_')[1])
            project_apps = [
                app for app in apps.get_app_configs()
                if app.label.startswith(f'project_{project_id}_')
            ]
            
            # First make migrations for all apps
            for app in project_apps:
                try:
                    logger.info(f"Making migrations for {app.label}")
                    call_command('makemigrations', app.label, interactive=False, verbosity=1)
                except Exception as e:
                    logger.error(f"Error making migrations for '{app.label}': {e}")
                    continue
            
            # Then apply all migrations for this database
            try:
                logger.info(f"Applying migrations for project {project_id}")
                call_command('migrate', database=db_alias, interactive=False, verbosity=1)
            except Exception as e:
                logger.error(f"Error applying migrations: {e}")
                # If batch migration fails, try individual apps
                for app in project_apps:
                    try:
                        call_command('migrate', app.label, database=db_alias, interactive=False, verbosity=1)
                    except Exception as e:
                        logger.error(f"Error applying migrations for '{app.label}': {e}")
                        continue
                
        except Exception as e:
            logger.error(f"Error checking migrations for {db_alias}: {e}")
            continue

@receiver(post_migrate)
def handle_post_migrate(sender, **kwargs):
    """Handle any necessary tasks after migrations are applied"""
    app_config = kwargs.get('app_config')
    if app_config and app_config.label.startswith('project_'):
        # Refresh dynamic apps after migrations
        from core.startup import dynamic_register_apps, dynamic_register_and_dump
        dynamic_register_apps()
        dynamic_register_and_dump()
        
        # Check if any other migrations are needed
        check_and_apply_migrations()