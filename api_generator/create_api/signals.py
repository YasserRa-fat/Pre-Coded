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
                if rel == 'forms.py': stub = '# Sample forms.py content'
                if rel == 'urls.py': stub = 'from django.urls import path\n\nurlpatterns = []\n'
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
    # refresh dynamic apps on disk
    from core.startup import dynamic_register_apps, dynamic_register_and_dump
    dynamic_register_apps()
    dynamic_register_and_dump()
    transaction.on_commit(lambda: _make_and_apply(instance))

def _make_and_apply(instance):
    label = f"project_{instance.project_id}_{instance.app.name}"
    db_alias = f"project_{instance.project_id}"

    # Generate migrations for dynamic app
    try:
        call_command('makemigrations', label, interactive=False, verbosity=1)
    except LookupError as e:
        logger.warning(f"Skipping makemigrations for '{label}': no models found ({e})")
        return
    except Exception as e:
        logger.error(f"Unexpected error during makemigrations for '{label}': {e}")
        return

    # Apply migrations, with retry and FieldDoesNotExist handling
    for attempt in range(2):
        try:
            call_command('migrate', label, database=db_alias, interactive=False, verbosity=1)
            break
        except LookupError as e:
            logger.warning(f"Skipping migrate for '{label}' on '{db_alias}': {e}")
            break
        except models.ObjectDoesNotExist as e:
            logger.error(f"FieldDoesNotExist during migrate for '{label}' on '{db_alias}': {e}")
            break
        except Exception as e:
            logger.error(f"Error applying migrations for '{label}' on '{db_alias}' [attempt {attempt+1}]: {e}")
            if attempt == 1:
                break
            # on first failure, retry after a short pause
            time.sleep(1)


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
