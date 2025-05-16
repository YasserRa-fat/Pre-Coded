# core/early.py
"""
Early dynamic registration of project databases and apps,
before Django's app registry is populated.
"""
import sqlite3
import os
import re
from pathlib import Path
from django.conf import settings
import textwrap


def get_default_db_path():
    # assume default is sqlite3
    default = settings.DATABASES['default']
    return Path(default['NAME'])


def dynamic_register_databases_early():
    """
    Connect directly to the default sqlite DB and load each project's SettingsFile.
    """
    db_path = get_default_db_path()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Fetch all projects and their settings content
    cur.execute('SELECT project_id, content FROM create_api_settingsfile')
    for project_id, raw in cur.fetchall():
        alias = f"project_{project_id}"
        if alias in settings.DATABASES:
            continue

        # Exec the stored settings.py to extract DATABASES
        ns = {"__file__": str(db_path.parent / f"project_{project_id}_settings.py")}
        exec(textwrap.dedent(raw), ns)
        proj_dbs = ns.get('DATABASES', {})
        if 'default' not in proj_dbs:
            continue

        # Merge over real default
        base_default = settings.DATABASES['default'].copy()
        merged = base_default.copy()
        merged.update(proj_dbs['default'])
        # override file name
        merged['NAME'] = str(db_path.parent / f"{alias}.sqlite3")
        settings.DATABASES[alias] = merged
        print(f"🗄️  Early registered DB '{alias}' → {merged.get('NAME')}")

    conn.close()


def inject_related_names(lines):
    """
    Patch FK/O2O fields to inject related_name='+' to avoid reverse accessor conflicts.
    """
    fk_pattern = re.compile(
        r"^(?P<indent>\s*)(?P<name>\w+)\s*=\s*models\.(?P<type>ForeignKey|OneToOneField)\((?P<args>.*)\)$"
    )
    output = []
    for line in lines:
        m = fk_pattern.match(line)
        if m:
            indent = m.group("indent")
            name = m.group("name")
            field_type = m.group("type")
            args = m.group("args")
            # only add if not already specifying related_name
            if "related_name" not in args:
                args = f"{args}, related_name='+'"
            line = f"{indent}{name} = models.{field_type}({args})"
        output.append(line)
    return output

def dynamic_register_apps_early():
    db_path = get_default_db_path()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    DYNAMIC_ROOT = Path(settings.BASE_DIR) / 'dynamic_apps'
    DYNAMIC_ROOT.mkdir(exist_ok=True)
    init_root = DYNAMIC_ROOT / '__init__.py'
    if not init_root.exists():
        init_root.write_text('')

    cur.execute('SELECT project_id, name, id FROM create_api_app')
    for project_id, name, app_id in cur.fetchall():
        label = f"project_{project_id}_{name}"
        fs_module = f"dynamic_apps.{label}"
        fs_path = DYNAMIC_ROOT / label

        fs_path.mkdir(parents=True, exist_ok=True)
        init_file = fs_path / '__init__.py'
        init_content = ''
        if not init_file.exists() or init_file.read_text() != init_content:
            init_file.write_text(init_content)

        apps_py = fs_path / 'apps.py'
        apps_content = textwrap.dedent(f"""
            from django.apps import AppConfig

            class {name.capitalize()}Config(AppConfig):
                name = '{fs_module}'
                label = '{label}'
        """)
        if not apps_py.exists() or apps_py.read_text() != apps_content:
            apps_py.write_text(apps_content)

        cur.execute(
            """
            SELECT mf.content
              FROM create_api_modelfile mf
             WHERE mf.project_id=?
               AND mf.app_id=?
               AND mf.path LIKE '%models.py'
            """,
            (project_id, app_id)
        )
        row = cur.fetchone()
        if row:
            (content,) = row
            lines = content.splitlines()
            sanitized = inject_related_names(lines)
            models_content = "\n".join(sanitized)
            models_file = fs_path / 'models.py'
            if not models_file.exists() or models_file.read_text() != models_content:
                models_file.write_text(models_content)

        mig = fs_path / 'migrations'
        mig.mkdir(exist_ok=True)
        mig_init = mig / '__init__.py'
        mig_content = ''
        if not mig_init.exists() or mig_init.read_text() != mig_content:
            mig_init.write_text(mig_content)

        if fs_module not in settings.INSTALLED_APPS:
            settings.INSTALLED_APPS.append(fs_module)
            print(f"➕ Early registered app '{fs_module}'")

    conn.close()