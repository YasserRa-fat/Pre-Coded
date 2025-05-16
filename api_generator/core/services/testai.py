import json
from django.template import engines
from django.test import RequestFactory
from django.template.context import RequestContext
from create_api.models import AIChangeRequest, TemplateFile

# Fetch data
change = AIChangeRequest.objects.get(pk=83, project_id=1)
diff = json.loads(change.diff or "{}")

# Get contents
try:
    orig_template = TemplateFile.objects.get(project_id=1, path="feed.html")
    orig_content = orig_template.content
except TemplateFile.DoesNotExist:
    orig_content = ""
patched_content = diff.get("templates/feed.html") or diff.get("feed.html") or orig_content

# Test both modes
contents = {"before": orig_content, "after": patched_content}
for mode, content in contents.items():
    print(f"\nTesting mode: {mode}")
    if not content:
        print("No content available")
        continue

    # Mock request and context
    factory = RequestFactory()
    request = factory.get("/")
    mock_posts = [
        {
            "title": "Sample Post",
            "content": "This is a sample post.",
            "image": {"url": "/static/sample.jpg"},
            "created_at": "2025-05-09",
            "get_absolute_url": "/posts/1/",
            "id": 1,
        }
    ]
    ctx = RequestContext(request, {"project": change.project, "posts": mock_posts})

    # Render template
    django_engine = engines["django"]
    try:
        template_obj = django_engine.from_string(content)
        rendered = template_obj.render(ctx)
        print(f"Rendered output (first 200 chars): {rendered[:200]}")
    except Exception as e:
        print(f"Rendering failed: {str(e)}")