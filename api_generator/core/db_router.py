class ProjectRouter:
    """
    Routes models in apps labeled "project_<id>_<appname>" to the "project_<id>" database,
    and allows them to FK back to auth.User in the default DB.
    """

    def db_for_read(self, model, **hints):
        label = model._meta.app_label
        if label.startswith('project_'):
            parts = label.split('_', 2)
            return f"project_{parts[1]}"
        return None

    def db_for_write(self, model, **hints):
        return self.db_for_read(model, **hints)

    def allow_migrate(self, db, app_label, model_name=None, **hints):
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

        # otherwise, fall back to Django’s default (None)
        return None
