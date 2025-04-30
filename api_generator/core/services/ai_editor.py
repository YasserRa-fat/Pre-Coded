# core/services/ai_editor.py
import os, re, requests
from django.conf import settings

TOGETHER_API_KEY = os.getenv("TOGETHER_AI_API_KEY")
MISTRAL_MODEL    = "mistralai/Mixtral-8x7B-Instruct-v0.1"
API_URL          = "https://api.together.xyz/inference"

SYSTEM_PROMPT = """
You are an expert Django AI assistant. The user is editing:
Project: {project_name}
App: {app_name or '—'}
File: {file_path or '—'}

When clear, output only a unified diff (lines starting with +/−) to implement the change.
If the request is ambiguous or you need clarification, start your reply with "CLARIFY:" and ask exactly one question.
Do NOT output any other text.
"""

def call_ai(conversation, last_user_message):
    # build full prompt with history
    hist = []
    for msg in conversation.messages.order_by('timestamp'):
        role = "User:" if msg.sender=='user' else "Assistant:"
        hist.append(f"{role} {msg.text}")
    hist.append(f"User: {last_user_message}")
    prompt = SYSTEM_PROMPT.format(
        project_name=conversation.project.name,
        app_name=conversation.app_name or '',
        file_path=conversation.file_path or ''
    ) + "\n\n" + "\n".join(hist) + "\nAssistant:"
    payload = {
        "model": MISTRAL_MODEL,
        "prompt": prompt,
        "temperature": 0.2,
        "max_tokens": 512
    }
    headers = {"Authorization": f"Bearer {TOGETHER_API_KEY}"}
    resp = requests.post(API_URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json().get("choices", [])[0].get("text","").strip()

def parse_ai_output(text):
    """Return ('clarify', question) or ('diff', diff_text)."""
    if text.upper().startswith("CLARIFY:"):
        return 'clarify', text[len("CLARIFY:"):].strip()
    # otherwise assume diff
    # optionally strip triple-backticks
    cleaned = re.sub(r"^```diff|```$", "", text, flags=re.MULTILINE).strip()
    return 'diff', cleaned
