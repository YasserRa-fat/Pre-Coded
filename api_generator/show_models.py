from django.apps import apps
from django.db.models.fields.related import ForeignKey, ManyToManyField

def print_model_data(model):
    model_name = model.__name__
    print(f"\n===== {model._meta.app_label}.{model_name} =====")
    try:
        objects = model.objects.all()[:5]
        if not objects:
            print("  (No data)")
            return
        for obj in objects:
            print(f"\n{model_name} ID: {obj.pk}")
            for field in model._meta.get_fields():
                if field.auto_created and not field.concrete:
                    continue  # Skip reverse relations

                try:
                    value = getattr(obj, field.name)
                    if isinstance(field, ManyToManyField):
                        print(f"  {field.name} (ManyToMany): {[str(v) for v in value.all()]}")
                    elif isinstance(field, ForeignKey):
                        print(f"  {field.name} (FK): {str(value)}")
                    else:
                        print(f"  {field.name}: {value}")
                except Exception as e:
                    print(f"  {field.name}: <error: {e}>")
    except Exception as e:
        print(f"  Could not load data: {e}")

# Loop through all models from all installed apps
for model in apps.get_models():
    print_model_data(model)
