import os
import simplejson as json
import difflib
import requests
from django.core.management import call_command
from asgiref.sync import sync_to_async
import logging
import re
logger = logging.getLogger(__name__)
from create_api.models import (
    AIChangeRequest,
    TemplateFile,
    ModelFile,
    ViewFile,
    FormFile,
    AppFile,
    StaticFile
)
from .classifier import classify_request
TOGETHER_API_KEY = os.getenv("TOGETHER_AI_API_KEY")
MISTRAL_MODEL    = "mistralai/Mixtral-8x7B-Instruct-v0.1"
API_URL          = "https://api.together.xyz/inference"

json_example = r'{ "files": { "<file_path>": "<updated_content>", "<file_path>": "<updated_content>" } }'.replace('{', '{{').replace('}', '}}')
empty_example = r'{ "files": {} }'.replace('{', '{{').replace('}', '}}')

SYSTEM_PROMPT = f"""
You are an AI assistant for a Django project. The user may request changes.  
**You already have the complete contents of every file** (they appear below in fenced code blocks).  
Under no circumstances should you ask for file contents or clarification.  
Your task is to generate a JSON object mapping file paths to their full updated contents.  

Return exactly this JSON, nothing else: { json_example }  
If no changes are needed, return exactly: { empty_example }  

Context:  
Project: {{project_name}}  
App: {{app_name}}  
Files in scope:  
{{file_list}}  
"""
SYSTEM_CHAT_PROMPT = """
You are an expert Django assistant. Here are the details of the user’s project:

• Name: {project_name}  
• Description: {project_description}  

It contains the following files:
{file_list}

Please answer the user’s question about this project in clear, plain English.
"""
async def run_apply(change: AIChangeRequest, project_db_alias: str):
    diffs = json.loads(change.diff)
    FILE_MODEL = {
        'template': TemplateFile,
        'model': ModelFile,
        'view': ViewFile,
        'form': FormFile,
        'app': AppFile,
        'static': StaticFile,
    }

    for path, new_content in diffs.items():
        file_type = change.file_type or classify_request(change.conversation.messages.last().text, [path])[0]
        model_cls = FILE_MODEL.get(file_type, AppFile)
        
        qs = model_cls.objects.filter(project=change.conversation.project, path=path)
        obj = await sync_to_async(qs.first)()
        if obj:
            obj.content = new_content
            await sync_to_async(obj.save)()
        else:
            kwargs = {'project': change.conversation.project, 'content': new_content, 'path': path}
            if hasattr(model_cls, 'app') and change.app_name:
                app_obj = await sync_to_async(App.objects.get)(
                    project=change.conversation.project, name=change.app_name
                )
                kwargs['app'] = app_obj
            await sync_to_async(model_cls.objects.create)(**kwargs)

        if file_type == 'model':
            label = obj.app._meta.label_lower if obj else change.app_name
            await sync_to_async(call_command)("makemigrations", label, interactive=False)
            await sync_to_async(call_command)("migrate", label, database=project_db_alias, interactive=False)
def call_ai(conversation, last_user_message, context_files):
    history = []
    for msg in conversation.messages.order_by('timestamp'):
        prefix = "User:" if msg.sender=='user' else "Assistant:"
        history.append(f"{prefix} {msg.text}")
    history.append(f"User: {last_user_message}")

    file_list = "\n".join(f"- {p}" for p in context_files.keys())
    prompt = SYSTEM_PROMPT.format(
        project_name=conversation.project.name,
        app_name=conversation.app_name or "—",
        file_list=file_list
    ) + "\n\n"

    prompt += (
       "!!! ATTENTION AI !!!\n"
       "You must output *only* a JSON object with EXACTLY two keys:\n"
       "  {\n"
       "    \"diffs\": { \"path\": \"<unified_diff>\" , … },\n"
       "    \"files\": [ \"path\", … ]\n"
       "  }\n"
       "Each <unified_diff> must start with:\n"
       "  --- a/<path>\\n"
       "  +++ b/<path>\\n"
       "  @@ ... @@\n"
       "Do NOT include any other text, explanation, or markup.\n\n"
    )

    for path, content in context_files.items():
        prompt += f"```{path}\n{content}\n```\n\n"
    prompt += "\n".join(history) + "\nAssistant:"

    resp = requests.post(
        API_URL,
        json={
            "model": MISTRAL_MODEL,
            "prompt": prompt,
            "temperature": 0.2,
            "max_tokens": 2048,
        },
        headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"},
        timeout=150
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["text"].strip()

def parse_ai_output(ai_text: str):
    m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", ai_text, flags=re.IGNORECASE)
    if m:
        payload = m.group(1)
    else:
        start = ai_text.find("{")
        end   = ai_text.rfind("}")
        if start < 0 or end < 0 or end <= start:
            raise ValueError("Could not locate JSON object in AI response")
        payload = ai_text[start:end+1]

    cleaned = "".join(
        ch for ch in payload
        if ord(ch) >= 32 or ch in ("\t", "\r", "\n")
    )

    sanitized = cleaned.replace("\r", "\\r").replace("\n", "\\n")
    logger.debug("▶️ Sanitized JSON payload: %r", sanitized)

    try:
        return json.loads(sanitized, strict=False)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failed after sanitization: {e}\nPayload:\n{sanitized}") from e

def call_chat_ai(conversation, last_user_message, context_files=None):
    history = []
    for msg in conversation.messages.order_by('timestamp'):
        prefix = 'User:' if msg.sender == 'user' else 'Assistant:'
        history.append(f"{prefix} {msg.text}")
    history.append(f"User: {last_user_message}")

    if context_files:
        file_list = "\n".join(f"- {path} ({len(content)} chars)" for path, content in context_files.items())
    else:
        file_list = "– no files provided –"

    prompt = SYSTEM_CHAT_PROMPT.format(
        project_name=conversation.project.name,
        project_description=conversation.project.description or "— no description provided —",
        file_list=file_list
    ) + "\n\n"

    if context_files:
        for path, content in context_files.items():
            prompt += f"```{path}\n{content}\n```\n\n"

    prompt += f"User: {last_user_message}\nAssistant:"

    resp = requests.post(
        API_URL,
        json={
            "model": MISTRAL_MODEL,
            "prompt": prompt,
            "temperature": 0.2,
            "max_tokens": 512,
        },
        headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"},
        timeout=150
    )
    resp.raise_for_status()
    data = resp.json()
    logger.debug("Together API response: %s", json.dumps(data, indent=2))
    return data.get("choices", [{}])[0].get("text", "").strip()

async def call_ai_multi_file(conversation, last_user_message, context_files):
    """
    Sends a prompt to Together AI and extracts a JSON object from the response.
    Returns (files_dict, error_message) where error_message is None on success.
    """
    project_name = await sync_to_async(lambda: conversation.project.name)()
    app_name = await sync_to_async(lambda: conversation.app_name or "—")()
    raw_msgs = await sync_to_async(lambda: list(conversation.messages.order_by('timestamp')))()
    history = [f"{'User:' if m.sender=='user' else 'Assistant:'} {m.text}" for m in raw_msgs]
    history.append(f"User: {last_user_message}")

    def est(text: str) -> float:
        return len(text) / 4.0

    header = (
        "You are an AI assistant for a Django project.\n"
        "Reply with only the JSON object: {\"files\":{...}} mapping file paths "
        "to full updated contents. No extra text, markdown, or explanations. "
        "The response must start with '{' and end with '}'. "
        "Ensure all string values are properly escaped to form valid JSON.\n\n"
        "If the user requested a change in anyof their frontend, then change only the styles keeping all existent functionality intact unless explicitly asked otherwise"
        "A template may be loading other templates, make sure if a change is made not to affect the reusable template as it might be used by other ones, instead make new custom implementation for the request"
        "Always make sure necessary loading tags are included such as {% load static %}"
    )
    MAX_CONTENT_CHARS = 8000
    truncated = {
        path: (content[:MAX_CONTENT_CHARS] + "\n\n/* ...CONTENT TRUNCATED... */") if len(content) > MAX_CONTENT_CHARS else content
        for path, content in context_files.items()
    }

    files_dict = dict(truncated)
    MAX_MODEL_TOKENS = 32768
    MAX_COMPLETION_TOKENS = 10000

    def build_prompt():
        flist = "\n".join(f"- {p}" for p in files_dict)
        p = header + f"Project: {project_name}\nApp: {app_name}\nFiles:\n{flist}\n\n"
        for path, content in files_dict.items():
            p += f"Current content of {path}:\n```{content}```\n\n"
        p += "\n".join(history) + "\nAssistant:"
        return p

    while True:
        prompt = build_prompt()
        total_tokens = est(prompt) + MAX_COMPLETION_TOKENS
        if total_tokens <= MAX_MODEL_TOKENS:
            break
        if files_dict:
            largest = max(files_dict, key=lambda k: len(files_dict[k]))
            files_dict.pop(largest)
            logger.warning("Dropped file '%s' to fit tokens", largest)
            continue
        if history:
            history.pop(0)
            logger.warning("Dropped oldest history line to fit tokens")
            continue
        return None, "Unable to fit prompt within token limit."

    body = {"model": MISTRAL_MODEL, "prompt": prompt, "temperature": 0.2, "max_tokens": MAX_COMPLETION_TOKENS}
    try:
        resp = requests.post(API_URL, json=body, headers={"Authorization": f"Bearer {TOGETHER_API_KEY}"}, timeout=150)
        resp.raise_for_status()
    except requests.HTTPError:
        logger.error("Together API %d error: %s", resp.status_code, resp.text)
        return None, f"API error {resp.status_code}: see logs"
    except Exception as e:
        logger.error("Together API exception: %s", e)
        return None, f"API request failed: {e}"

    data = resp.json()
    logger.debug("AI RAW RESPONSE: %s", json.dumps(data, indent=2))
    text = data.get("choices", [{}])[0].get("text", "").strip()
    logger.debug("AI RAW TEXT: %r", text)
    # 1) find the first '{'
    start = text.find("{")
    if start < 0:
        logger.error("No JSON object found in AI response")
        return None, "No JSON object found"

    # 2) walk forward, tracking braces
    depth = 0
    end = None
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end is None:
        logger.error("Unterminated JSON object in AI response")
        return None, "Malformed JSON: unterminated"

    json_str = text[start:end]
    logger.debug("JSON block extracted: %s", json_str[:100] + "…")

    # 3) parse it
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("JSON parse failed: %s\nPayload: %s", e, json_str)
        return None, f"Invalid JSON: {e}"

    # 4) normalize to files dict
    if "files" in parsed and isinstance(parsed["files"], dict):
        return parsed["files"], None
    if isinstance(parsed, dict):
        return parsed, None

    return None, "Malformed AI response: expected object of file mappings"