import os
import shutil
import tempfile

from django.conf import settings
from django.db.models.signals import post_save,pre_delete
from django.dispatch import receiver
from django.core.management import call_command
from create_api.models import MediaFile, Project
from django.db import models

from .models import (
    Project, App,
    ProjectFile, AppFile,
    TemplateFile, SettingsFile, URLFile,
    StaticFile, MediaFile, ModelFile, ViewFile, FormFile
)

def write_codefile(model, project, app, rel_path, real_path, **extra):
    """
    Read the file on disk, then create `model` with exactly the fields
    it actually defines (no spurious `app=None` on project‐only models).
    """

    # 1) Read content
    with open(real_path, encoding='utf-8') as f:
        content = f.read()

    # 2) Base kwargs always include project, path, name, content
    kwargs = {
        'project': project,
        'path': rel_path.replace(os.sep, '/'),
        'name': os.path.basename(rel_path),
        'content': content,
        **extra,
    }

    # 3) Only add `app` if that field actually exists on the model
    field_names = {f.name for f in model._meta.get_fields()}
    if 'app' in field_names and app is not None:
        kwargs['app'] = app

    # 4) Create it
    model.objects.create(**kwargs)


@receiver(post_save, sender=Project)
def create_project_skeleton(sender, instance, created, **kwargs):
    if not created:
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        call_command('startproject', instance.name, temp_dir)
        project_root = os.path.join(temp_dir, instance.name)
        manage_py = os.path.join(temp_dir, 'manage.py')

        # manage.py
        if os.path.exists(manage_py):
            write_codefile(ProjectFile, instance, None,
                           'manage.py', manage_py)

        # standard project files
        for fname in ('__init__.py', 'settings.py', 'urls.py', 'wsgi.py', 'asgi.py'):
            real = os.path.join(project_root, fname)
            if not os.path.exists(real):
                continue

            # if urls.py already recorded, skip
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


@receiver(post_save, sender=App)
def create_app_skeleton(sender, instance, created, **kwargs):
    if not created:
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        app_dir = os.path.join(temp_dir, instance.name)
        os.makedirs(app_dir, exist_ok=True)
        call_command('startapp', instance.name, app_dir)

        for rel in ('__init__.py', 'admin.py', 'apps.py',
                    'models.py', 'tests.py', 'views.py', 'urls.py', 'forms.py'):

            real = os.path.join(app_dir, rel)

            # If the app already has a urls.py record, skip
            if rel == 'urls.py' and URLFile.objects.filter(
                project=instance.project, app=instance, name='urls.py'
            ).exists():
                continue

            if not os.path.exists(real):
                if rel == 'forms.py':
                    stub = '# Sample forms.py content'
                elif rel == 'urls.py':
                    stub = 'from django.urls import path\n\nurlpatterns = []\n'
                else:
                    continue

                with open(real, 'w', encoding='utf-8') as f:
                    f.write(stub)

            model = {
                'models.py': ModelFile,
                'views.py': ViewFile,
                'forms.py': FormFile,
                'urls.py': URLFile,
            }.get(rel, AppFile)

            write_codefile(model, instance.project, instance,
                           os.path.join(instance.name, rel), real)

        # migrations/__init__.py
        mig_init = os.path.join(app_dir, 'migrations', '__init__.py')
        if not os.path.exists(mig_init):
            os.makedirs(os.path.dirname(mig_init), exist_ok=True)
            with open(mig_init, 'w', encoding='utf-8') as f:
                f.write('# Sample __init__.py content')
            write_codefile(AppFile, instance.project, instance,
                           os.path.join(instance.name, 'migrations', '__init__.py'), mig_init)

        # templates, static, media as before…
        # (the helper will pick up the right FK fields)


        # App-level templates / static / media
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
                    print(f"Writing {rel} as {model.__name__} for app {instance.name}")
                    write_codefile(model, instance.project, instance, rel, real, is_project_file=False, **extra)

@receiver(post_save, sender=ModelFile)
def rebuild_and_migrate(sender, instance, **kwargs):
    """
    Whenever a ModelFile is changed in the DB:
      1) rewrite models.py on disk
      2) makemigrations for that app
      3) migrate that app’s database
    """
    # 1) dump all dynamic apps (rewrites models.py)
    from core.startup import dynamic_register_and_dump, dynamic_register_apps
    dynamic_register_apps()
    dynamic_register_and_dump()

    # derive the django app label, e.g. project_1_posts
    project_label = f"project_{instance.project_id}_{instance.app.name}"

    # 2) makemigrations for that one app
    call_command("makemigrations", project_label, interactive=False)

    # 3) migrate on that project’s DB
    #    you must have a DATABASES['project_<id>'] entry & a router
    call_command("migrate", project_label, database=f"project_{instance.project_id}", interactive=False)


def get_project_from_app_label(label):
    # labels look like "project_1_users" or "project_1_posts"
    parts = label.split("_")
    if len(parts) >= 2 and parts[1].isdigit():
        return Project.objects.filter(id=int(parts[1])).first()
    return None

@receiver(post_save)
def sync_mediafile_on_save(sender, instance, **kwargs):
    # Only care about dynamic-app models
    label = getattr(sender._meta, "app_label", "")
    if not label.startswith("project_"):
        return

    project = get_project_from_app_label(label)

    # Inspect all FileField/ImageField on this model
    for field in instance._meta.get_fields():
        if isinstance(field, models.FileField):
            file_field = getattr(instance, field.name)
            if file_field and hasattr(file_field, "name") and file_field.name:
                path = file_field.name  # e.g. "profile_avatar/foo.png"
                # Upsert the MediaFile row
                MediaFile.objects.update_or_create(
                    path=path,
                    defaults={
                        "file": path,
                        "project": project,
                    }
                )

@receiver(pre_delete)
def delete_mediafile_on_delete(sender, instance, **kwargs):
    label = getattr(sender._meta, "app_label", "")
    if not label.startswith("project_"):
        return

    # If the instance had any files, remove their MediaFile rows
    for field in instance._meta.get_fields():
        if isinstance(field, models.FileField):
            file_field = getattr(instance, field.name)
            if file_field and file_field.name:
                MediaFile.objects.filter(path=file_field.name).delete()