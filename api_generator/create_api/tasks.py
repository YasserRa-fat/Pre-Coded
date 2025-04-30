import os
import time
from pathlib import Path
from dotenv import load_dotenv
from together import Together
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django_q.tasks import async_task

# ------------------------------------------------------------
# 🔵 1. Load .env early (only if not already loaded)
BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR.parent / ".env"

TOGETHER_AI_API_KEY='5c5f7514a2e2bde8bda4e086fe17ddc0c7e76a8a41e29e908761139b358dfb11'
# 🛠 Local imports
from .models import (
    AIConversation, AIMessage, AIChangeRequest,
    TemplateFile, StaticFile, MediaFile,
    ProjectFile, URLFile, AppFile,
    ModelFile, ViewFile, FormFile
)
from .serializers import AIMessageSerializer, AIChangeRequestSerializer

def _ensure_parent(project, path, Model):
    """Ensure intermediate folders exist and return parent folder instance."""
    parts = path.split("/")[:-1]
    parent = None
    for p in parts:
        folder, _ = Model.objects.get_or_create(
            project=project,
            name=p,
            parent=parent,
            defaults={'is_folder': True, 'content': ''}
        )
        parent = folder
    return parent

def handle_chat(conv_id, user_message):
    """Handle chat interactions using Together API."""
    conv = AIConversation.objects.get(id=conv_id)

    # Record the user message
    AIMessage.objects.create(conversation=conv, sender='user', text=user_message)

    # Build context from all project files
    snippets = []
    for FileModel in (
        TemplateFile, StaticFile, MediaFile,
        ProjectFile, URLFile, AppFile,
        ModelFile, ViewFile, FormFile
    ):
        for f in FileModel.objects.filter(project=conv.project, is_folder=False):
            header = getattr(f, "path", f.name)
            snippets.append(f"--- {header} ---\n{f.content}")
    context = "\n\n".join(snippets)

    # Initialize Together client
    api_key = TOGETHER_AI_API_KEY
    if not api_key:
        raise RuntimeError("TOGETHER_API_KEY not set in environment")

    client = Together(api_key=api_key)

    messages = [
        {"role": "system", "content": f"Project context:\n{context}"},
        {"role": "user",   "content": user_message}
    ]

    # Attempt up to 3 times
    ai_resp = None
    for attempt in range(3):
        try:
            stream = client.chat.completions.create(
                model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
                messages=messages,
                stream=True
            )
            ai_resp = "".join(chunk.choices[0].delta.content or "" for chunk in stream)
            break
        except Exception as e:
            print(f"⚠️ Chat attempt {attempt+1} failed: {e}")
            time.sleep(2**attempt)

    if not ai_resp:
        print("❌ No AI response after 3 attempts")
        return  # Bail if no response

    # Record assistant reply
    AIMessage.objects.create(conversation=conv, sender='assistant', text=ai_resp)

    # Parse CREATE instructions
    for line in ai_resp.splitlines():
        if line.startswith("CREATE "):
            _, rest = line.split("CREATE ", 1)
            path, code = rest.split(":", 1)
            code = code.rstrip()
            ext = path.split(".")[-1].lower()

            # Pick appropriate model
            if ext in ("html", "htm"):
                Model = TemplateFile
            elif ext in ("css", "js"):
                Model = StaticFile
            elif ext in ("png", "jpg", "jpeg", "gif", "svg"):
                Model = MediaFile
            elif path.endswith("urls.py"):
                Model = URLFile
            else:
                Model = AppFile

            parent = _ensure_parent(conv.project, path, Model)
            obj, created = Model.objects.update_or_create(
                project=conv.project,
                name=path.split("/")[-1],
                parent=parent,
                defaults={'content': code, 'is_folder': False}
            )

            AIChangeRequest.objects.create(
                conversation=conv,
                file_type=ext if ext in ('template', 'model', 'view', 'form') else 'other',
                app_name=conv.app_name,
                file_path=path,
                diff=code
            )

    # Broadcast updated chat + changes over WebSocket
    channel_layer = get_channel_layer()
    payload = {
        "chat": {
            "conversation_id": conv.id,
            "messages": AIMessageSerializer(conv.messages, many=True).data,
            "changes":  AIChangeRequestSerializer(conv.changes, many=True).data
        }
    }
    async_to_sync(channel_layer.group_send)(
        f"project_{conv.project.id}",
        {"type": "project_message", "payload": payload}
    )
