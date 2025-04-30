# core/early.py
"""
Early dynamic registration of project databases and apps,
before Django's app registry is populated.
"""
import sqlite3
import os
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


def dynamic_register_apps_early():
    """
    Connect directly to default sqlite and fetch App entries to append to INSTALLED_APPS,
    dump each app's files (apps.py, models.py) to dynamic_apps,
    and ensure migrations package exists.
    """
    db_path = get_default_db_path()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # root of dynamic file-system apps
    DYNAMIC_ROOT = Path(settings.BASE_DIR) / 'dynamic_apps'
    DYNAMIC_ROOT.mkdir(exist_ok=True)
    init_root = DYNAMIC_ROOT / '__init__.py'
    if not init_root.exists():
        init_root.write_text('')
# print(f"[DEBUG session] alias={alias!r}, user_id={user_id!r}, backend={backend_str!r}")
    # For each app defined in DB
    cur.execute('SELECT project_id, name, id FROM create_api_app')
    for project_id, name, app_id in cur.fetchall():
        label = f"project_{project_id}_{name}"
        fs_module = f"dynamic_apps.{label}"
        fs_path = DYNAMIC_ROOT / label

        # ensure package directory
        fs_path.mkdir(parents=True, exist_ok=True)
        init_file = fs_path / '__init__.py'
        if not init_file.exists():
            init_file.write_text('')

        # write apps.py
        apps_py = fs_path / 'apps.py'
        if not apps_py.exists():
            apps_py.write_text(f"""
from django.apps import AppConfig

class {name.capitalize()}Config(AppConfig):
    name = '{fs_module}'
    label = '{label}'
""")

        # dump models.py from DB
        # grab whatever models.py the DB knows (e.g. 'posts/models.py')
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
            (fs_path / 'models.py').write_text(content)

        # ensure migrations package
        mig = fs_path / 'migrations'
        mig.mkdir(exist_ok=True)
        mig_init = mig / '__init__.py'
        if not mig_init.exists():
            mig_init.write_text('')

        # register in INSTALLED_APPS
        if fs_module not in settings.INSTALLED_APPS:
            settings.INSTALLED_APPS.append(fs_module)
            print(f"➕ Early registered app '{fs_module}'")

    conn.close()