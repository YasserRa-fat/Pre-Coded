class ProjectRouter:
    """
    Routes models in apps labeled "project_<id>_<appname>" to the "project_<id>" database,
    and allows them to FK back to auth.User in the default DB.
    Also routes create_api models to project databases when in project context.
    """

    def db_for_read(self, model, **hints):
        # First check if we're in a project context
        from .thread_local import thread_local
        current_db = thread_local.db_alias
        if current_db and current_db != 'default':
            # If we're in a project context, route create_api models to that DB
            if model._meta.app_label == 'create_api':
                return current_db

        # Fall back to app label based routing
        label = model._meta.app_label
        if label.startswith('project_'):
            parts = label.split('_', 2)
            return f"project_{parts[1]}"
        return None

    def db_for_write(self, model, **hints):
        return self.db_for_read(model, **hints)

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Allow create_api migrations on both default and project databases
        if app_label == 'create_api':
            return True
            
        if app_label.startswith('project_'):
            parts = app_label.split('_', 2)
            return db == f"project_{parts[1]}"
        return db == 'default'

    def allow_relation(self, obj1, obj2, **hints):
        lab1 = obj1._meta.app_label
        lab2 = obj2._meta.app_label

        # if either model is in a project_<id> app, allow the relation
        if lab1.startswith('project_') or lab2.startswith('project_'):
            return True

        # Allow relations between create_api models
        if lab1 == 'create_api' and lab2 == 'create_api':
            return True

        # otherwise, fall back to Django's default (None)
        return None