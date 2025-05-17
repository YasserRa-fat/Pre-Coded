import re
import requests
import openai
from gpt4all import GPT4All
import os
from dotenv import load_dotenv
import aiohttp
import asyncio
import time

# Load environment variables from .env file
load_dotenv()

# Retrieve API keys and sensitive data from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_KEY = os.getenv("TOGETHER_AI_API_KEY")

# Update OpenAI API key
openai.api_key = OPENAI_API_KEY
def parse_parameters(parameter_string):
    """
    Parses a parameter string from a Django field definition.
    This version supports quoted values as well as unquoted values.
    Returns a dictionary mapping parameter names to their string values.
    """
    parameters = {}
    if not parameter_string:
        return parameters

    # Split the parameter string by commas that are not inside quotes.
    params = re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', parameter_string)
    
    for param in params:
        # Try matching key="value".
        match = re.match(r'(\w+)\s*=\s*"(.*?)"', param)
        if not match:
            # If not quoted, try matching unquoted values (e.g. auto=True)
            match = re.match(r'(\w+)\s*=\s*(\S+)', param)
        if match:
            key, value = match.groups()
            parameters[key] = value
    return parameters


import re

def parse_code_with_comments(code):
    """
    Parses Django model code and extracts field definitions.
    
    Instead of relying on indentation, this function checks each line for an equals sign.
    If there is non‑empty content before the "=" and after the "=" the text "models." appears,
    it assumes the line defines a model field.
    
    It then extracts:
      - The field name (content before "=" trimmed)
      - The field type (the word following "models.", typically ending with "Field")
      - The parameter string (the contents inside the first pair of parentheses)
    
    It returns a dictionary with a key "fields" mapping to a list of field dictionaries.
    
    Example:
      Input:
         from django.db import models
         
         class Hello(models.Model):
             age = models.IntegerField(min_value=10)
             name = models.CharField(max_length=40)
      
      Output:
         { "fields": [
             { "name": "age", "type": "IntegerField", "parameters": {"min_value": "10"} },
             { "name": "name", "type": "CharField", "parameters": {"max_length": "40"} }
           ]
         }
    """
    # Normalize newlines.
    code = code.replace("\r\n", "\n")
    lines = code.split("\n")
    fields = []
    # Regex explanation:
    #   ^(.*?)           => Capture (non-greedily) anything before "=" (field name candidate)
    #   =\s*             => The equals sign (with optional whitespace after)
    #   models\.        => The literal string "models."
    #   (\w+Field)       => Capture field type (e.g. "CharField" or "IntegerField")
    #   $$               => Literal "("
    #   ([^)]*)          => Capture everything until the first ")" (parameter string)
    #   $$               => Literal ")"
    pattern = re.compile(r'^(.*?)=\s*models\.(\w+Field)$$([^)]*)$$')
    for line in lines:
        # Only consider lines that contain '=' and "models." on their right-hand side.
        if "=" in line and "models." in line:
            match = pattern.search(line)
            if match:
                lhs = match.group(1).strip()
                # Only process if lhs is not empty (has something before the "=")
                if lhs:
                    field_name = lhs
                    field_type = match.group(2).strip()
                    params_string = match.group(3).strip()
                    parameters = {}
                    if params_string:
                        # Split on commas (this simple approach assumes no commas in the values).
                        for part in params_string.split(","):
                            parts = part.split("=")
                            if len(parts) == 2:
                                key = parts[0].strip()
                                # Strip surrounding quotes (single or double).
                                value = parts[1].strip().strip('"').strip("'")
                                parameters[key] = value
                    fields.append({
                        "name": field_name,
                        "type": field_type,
                        "parameters": parameters
                    })
    print("Parsed fields from full_code:", fields)
    return {"fields": fields}

def generate_code_from_json(data):
    """
    Given a dictionary with a key "fields" (a list of field definitions),
    generate Django model field definitions as a string.
    
    Each field is formatted as:
       field_name = models.FieldType(param1="value1", param2="value2")
    The generated lines are indented by 4 spaces.
    """
    fields = data.get("fields", [])
    code_lines = []
    for field in fields:
        field_name = field.get("name")
        field_type = field.get("type")
        parameters = field.get("parameters", {})
        params_str = ", ".join(f'{k}="{v}"' for k, v in parameters.items())
        code_lines.append(f"    {field_name} = models.{field_type}({params_str})")
    return "\n".join(code_lines)


import ast

def extract_models_from_content(content):
    """
    Extracts models from a given models.py content.
    Returns a list of dictionaries with model names and fields.
    """
    tree = ast.parse(content)
    models = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # Check if the class inherits from models.Model
            if any(
                (isinstance(base, ast.Attribute) and base.attr == 'Model') or
                (isinstance(base, ast.Name) and base.id == 'Model')
                for base in node.bases
            ):
                fields = []
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign) and hasattr(stmt.targets[0], 'id'):
                        fields.append(stmt.targets[0].id)
                models.append({'name': node.name, 'fields': fields})
    return models

# utils.py
import ast

# create_api/utils.py (for example)

import re

def extract_models_from_code(code):
    """
    Parse Django model classes, returning a list of dicts with:
    [
      {
        "name": "Post",
        "fields": [
          {"name": "title", "type": "CharField", "params": "max_length=255"},
          ...
        ],
        "relationships": [
          {"type": "ForeignKey", "target": "User", "params": "User, on_delete=models.CASCADE, null=True, blank=True"}
        ]
      },
      ...
    ]
    """
    # Regex to capture `class ModelName(models.Model):`
    model_pattern = re.compile(
        r'class\s+(?P<model>\w+)\(models\.Model\):([\s\S]*?)(?=\nclass\s|\Z)',
        re.MULTILINE
    )
    # Regex to capture fields: `field_name = models.XxxField(...)`
    field_pattern = re.compile(
        r'(?P<field_name>\w+)\s*=\s*models\.(?P<field_type>\w+)\((?P<params>.*?)\)',
        re.DOTALL
    )

    models_data = []
    for match in model_pattern.finditer(code):
        model_name = match.group('model')
        body = match.group(2)  # The body inside the class

        fields = []
        relationships = []

        for field_match in field_pattern.finditer(body):
            field_name = field_match.group('field_name')
            field_type = field_match.group('field_type')
            params = field_match.group('params').strip()

            # Check if it's a relationship field
            if field_type in ['ForeignKey', 'OneToOneField', 'ManyToManyField']:
                # Attempt to parse the target model from the first param
                # e.g. ForeignKey(Post, on_delete=models.CASCADE)
                # We'll just take everything up to the first comma or parenthesis
                target_match = re.match(r"['\"]?(\w+)['\"]?", params)
                if target_match:
                    target_model = target_match.group(1)
                else:
                    target_model = "Unknown"

                relationships.append({
                    "type": field_type,
                    "target": target_model,
                    "params": params
                })

                # Also store it as a "field" so the node can display it
                fields.append({
                    "name": field_name,
                    "type": field_type,
                    "params": params
                })
            else:
                # Regular field
                fields.append({
                    "name": field_name,
                    "type": field_type,
                    "params": params
                })

        models_data.append({
            "name": model_name,
            "fields": fields,
            "relationships": relationships
        })

    return models_data


# create_api/utils.py
import requests
import time

def quick_summary(model_name, fields, relationships):
    """
    Returns a quick, rule-based summary of the Django model.
    This is the fallback if remote services are unavailable.
    """
    summary = f"{model_name}: " + ", ".join(f"{f['name']} ({f['type']})" for f in fields)
    if relationships:
        summary += "; Relationships: " + ", ".join(f"{r['type']} -> {r['target']}" for r in relationships)
    return summary

def call_inference_api(api_url, headers, payload, retries=3, backoff=5):
    for attempt in range(retries):
        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            return result
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(backoff)
            else:
                raise e



# 1) Specify your GPT4All model file name:
# 2) If your model file is not in the default directory, specify the full path:
# model_path = "/path/to/your/models/ggml-gpt4all-j-v1.3-groovy.bin"
# Otherwise, GPT4All will look in ~/.cache/gpt4all/ by default.

# 3) Create a GPT4All instance:

from gpt4all import GPT4All

# Use the actual file name (as a string) and the full path to your model file.
# MODEL_NAME = "ggml-gpt4all-j-v1.3-groovy.bin"
# MODEL_PATH = "C:/Users/yasse/OneDrive/Desktop/Pre-Coded/api_generator/create_api/model"
# os.environ["OMP_NUM_THREADS"] = "8"
# Instantiate GPT4All with the valid model name.
# model = GPT4All(model_name="ggml-gpt4all-j-v1.3-groovy.bin", model_path=MODEL_PATH, allow_download=False)



def generate_ai_summary(model_name, fields, relationships, retries=3, backoff=1.0):
    prompt = f"""
The Django model '{model_name}' has fields: {', '.join(field['name'] for field in fields)}.
It has relationships: {', '.join(f"{rel['type']} -> {rel['target']}" for rel in relationships)}.

Provide a human-readable summary with at most 40 words of this model's purpose, without generating code. Start with "The model {model_name}" and explain.
""".strip()
    url = "https://api.together.xyz/inference"
    payload = {
        "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "prompt": prompt,
        "temperature": 0.5,
        "max_tokens": 50
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}

    for attempt in range(retries):
        try:
            response = call_inference_api(url, headers, payload)
            if response.get("choices") and isinstance(response["choices"][0], dict) and "text" in response["choices"][0]:
                return response["choices"][0]["text"].strip().split("\n")[0]
            return "Error: Unexpected API response format."
        except requests.RequestException as e:
            logger.error(f"RequestException on attempt {attempt + 1}: {str(e)}")
            time.sleep(backoff)
            backoff *= 2

    return f"Error generating AI summary for model '{model_name}' after {retries} attempts."


def generate_view_ai_summary(view_name, view_type, model_reference):
    prompt = f"""
The Django view '{view_name}' is a {view_type} that operates on the model '{model_reference}'.
Provide a human-readable summary (max 40 words) of this view's purpose. Start with "The view {view_name}".
""".strip()
    url = "https://api.together.xyz/inference"
    payload = {
        "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "prompt": prompt,
        "temperature": 0.5,
        "max_tokens": 50
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}
    try:
        response = call_inference_api(url, headers, payload)
        if response.get("choices") and isinstance(response["choices"][0], dict) and "text" in response["choices"][0]:
            return response["choices"][0]["text"].strip().split("\n")[0]
        return "Error: Unexpected API response format."
    except requests.RequestException as e:
        return f"Error generating AI summary: {str(e)}"
    
    
def find_local_forms_in_file(code):
    """
    Return a dictionary of {FormClassName: {"is_modelform": bool, "model": str or None}}
    for all form classes declared in this file.
    """
    # Regex: class SomeForm(forms.ModelForm): ...
    form_pattern = (
        r"class\s+([A-Z][a-zA-Z0-9_]*)\(\s*forms\.(ModelForm|Form|BaseForm|.+)\)\s*:(.*?)(?=\nclass|\Z)"
    )
    matches = re.findall(form_pattern, code, re.DOTALL)

    form_info_map = {}
    for form_name, form_parent, form_body in matches:
        # Check if it's a ModelForm
        is_modelform = "ModelForm" in form_parent
        model_name = None
        if is_modelform:
            # Attempt to find model = SomeModel in the body
            model_match = re.search(r"^\s*class\s+Meta\s*:\s*(.*?)(?=\nclass|\Z)", form_body, re.DOTALL | re.MULTILINE)
            if model_match:
                meta_body = model_match.group(1)
                # Within Meta, we look for: model = SomeModel
                # e.g. model = Profile
                model_line = re.search(r"^\s*model\s*=\s*([A-Za-z0-9_]+)", meta_body, re.MULTILINE)
                if model_line:
                    model_name = model_line.group(1)
            else:
                # Another style: model = SomeModel directly in form body
                # (less common, but let's check)
                alt_model_line = re.search(r"^\s*model\s*=\s*([A-Za-z0-9_]+)", form_body, re.MULTILINE)
                if alt_model_line:
                    model_name = alt_model_line.group(1)

        form_info_map[form_name] = {
            "is_modelform": is_modelform,
            "model": model_name
        }

    return form_info_map


def find_imported_forms(code):
    """
    Return a set of form-like names that are imported, e.g.:
      from .forms import ProfileForm, RegisterForm
    """
    pattern = r"from\s+\S+\s+import\s+([\w,\s]+)"
    matches = re.findall(pattern, code)
    imported_forms = set()
    for m in matches:
        for name in m.split(","):
            name = name.strip()
            if name and name[0].isupper():
                if " as " in name:
                    name = name.split(" as ")[-1].strip()
                imported_forms.add(name)
    return imported_forms

def extract_views_from_code(code):
    """
    Extract view information including:
      - View name
      - View type (class-based or function-based)
      - Model reference(s)
      - Form class reference(s) (comma-separated if multiple)
    """
    views_data = []

    # Gather local form info (including if it's a ModelForm + which model)
    local_form_info = find_local_forms_in_file(code)
    local_form_names = set(local_form_info.keys())

    # Gather imported form names
    imported_form_names = find_imported_forms(code)
    recognized_forms = local_form_names.union(imported_form_names)

    GENERIC_VIEW_CLASSES = (
        "View", "TemplateView", "ListView", "DetailView",
        "CreateView", "UpdateView", "DeleteView", "FormView",
        "LoginView", "RedirectView"
    )

    # Class-Based Views
    class_pattern = r"class\s+(\w+)\(([\w,\s]+)\):(.*?)(?=\nclass|\Z)"
    class_matches = re.findall(class_pattern, code, re.DOTALL)
    for class_name, parents, class_body in class_matches:
        parent_list = [p.strip() for p in parents.split(',')]
        if any(p in GENERIC_VIEW_CLASSES for p in parent_list):
            model = "Not specified"
            form_class = "Not specified"
            # Look for 'model = SomeModel'
            model_match = re.search(r"^\s*model\s*=\s*(\w+)", class_body, re.MULTILINE)
            if model_match:
                model = model_match.group(1)

            # Look for 'form_class = SomeForm'
            fc_match = re.search(r"^\s*form_class\s*=\s*(\w+)", class_body, re.MULTILINE)
            if fc_match:
                fc_candidate = fc_match.group(1)
                if fc_candidate in recognized_forms:
                    form_class = fc_candidate
                    # If local form is a ModelForm, refine model
                    if fc_candidate in local_form_info:
                        form_model = local_form_info[fc_candidate].get("model")
                        if form_model and model == "Not specified":
                            model = form_model
                else:
                    form_class = fc_candidate

            views_data.append({
                "name": class_name,
                "view_type": "Class-based",
                "model": model,
                "form_class": form_class,
            })

    # Function-Based Views
    fbv_pattern = r"(?:\n|^)@?(?:\w+\.\s*)?(?:\w+\([^\)]*\)\s*)*def\s+(\w+)\s*\(\s*request[\s\),]"
    func_names = re.findall(fbv_pattern, code)
    for func_name in func_names:
        model = "Not specified"
        form_class = "Not specified"

        # Grab the function body
        body_pattern = rf"def\s+{func_name}\(.*?\):(.*?)(?=\ndef|\n@|\Z)"
        body_match = re.search(body_pattern, code, re.DOTALL)
        if body_match:
            body = body_match.group(1)

            # Extract model references via .objects
            model_refs = re.findall(r"\b(\w+)\.objects\b", body)
            if model_refs:
                model = ", ".join(set(model_refs))

            # Extract form references
            form_refs = re.findall(r"\bform\s*=\s*([A-Z][a-zA-Z0-9_]*)\s*\(", body)
            valid_form_refs = list(set(form_refs))
            if valid_form_refs:
                form_class = ", ".join(valid_form_refs)

                # Infer model from ModelForm
                all_models_inferred = set(model_refs)
                for fr in valid_form_refs:
                    if fr in local_form_info and local_form_info[fr]["is_modelform"]:
                        form_model = local_form_info[fr].get("model")
                        if form_model:
                            all_models_inferred.add(form_model)
                if all_models_inferred:
                    model = ", ".join(all_models_inferred)

        views_data.append({
            "name": func_name,
            "view_type": "Function-based",
            "model": model,
            "form_class": form_class,
        })

    return views_data





def generate_view_ai_summary_batch(views_data):
    url = "https://api.together.xyz/inference"
    prompt = """
We have the following Django views:
{views_list}

For EACH view above, provide a SINGLE-LINE summary starting with the view number.
Example format:
1) The view ProfileUpdate handles user profile updates with ProfileForm.
2) The view RegisterView manages user registration with RegisterForm.
...
""".strip()

    # Generate the list of views.
    views_list = "\n".join([
        f"{i}) Name: {v['name']}, Type: {v['view_type']}, Model: {v['model']}"
        for i, v in enumerate(views_data, 1)
    ])
    prompt = prompt.replace("{views_list}", views_list)
    payload = {
        "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "prompt": prompt,
        "temperature": 0.5,
        "max_tokens": 500
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}

    try:
        max_retries = 2
        for attempt in range(max_retries):
            response = call_inference_api(url, headers, payload)
            if response.get("choices") and isinstance(response["choices"][0], dict) and "text" in response["choices"][0]:
                raw_text = response["choices"][0]["text"]
            else:
                raw_text = response["choices"][0]
            lines = raw_text.strip().split('\n')
            # Filter lines that start with a digit followed by a parenthesis.
            valid_lines = [line for line in lines if re.match(r'^\d+\)', line.strip())]
            pattern = r'^(\d+)\)\s*(.*)$'
            matches = []
            for line in valid_lines:
                m = re.match(pattern, line)
                if m:
                    matches.append({"num": int(m.group(1)), "text": m.group(2)})
            if len(matches) < len(views_data):
                print(f"Attempt {attempt + 1} failed: Only {len(matches)} summaries for {len(views_data)} views. Retrying...")
                time.sleep(1)
                continue
            matches.sort(key=lambda x: x["num"])
            return [m["text"].strip() for m in matches]
        return ["Error: Max retries exceeded."] * len(views_data)
    except requests.RequestException as e:
        return [f"Error generating AI summary: {str(e)}"] * len(views_data)

def extract_forms_from_code(code):
    """
    Extracts Django form classes from the given code.
    Looks for classes that inherit from anything ending in 'Form'
    and captures the 'model' in Meta if present.
    """
    forms = []
    class_pattern = re.compile(r'class\s+(\w+)\s*\(.*?\b\w+Form\b.*?\):')

    for class_match in class_pattern.finditer(code):
        form_name = class_match.group(1)
        start = class_match.end()
        next_class = re.search(r'\nclass\s+\w+\s*\(', code[start:])
        end = next_class.start() + start if next_class else len(code)
        class_body = code[start:end]

        # Extract the model from "class Meta:"
        model_name = ""
        meta_pattern = re.compile(r'class\s+Meta\s*:\s*(.*?)(?=\nclass\s|\Z)', re.DOTALL)
        meta_match = meta_pattern.search(class_body)
        if meta_match:
            meta_block = meta_match.group(1)
            model_pattern = re.compile(r'model\s*=\s*(\w+)')
            model_match = model_pattern.search(meta_block)
            if model_match:
                model_name = model_match.group(1)

        forms.append({
            "name": form_name,
            "model": model_name,
            # Add model_used so that frontend enrichment can check it
            "model_used": model_name,
            # Optionally add "ai_description" here if needed.
        })

    return forms

def generate_form_ai_summary_batch(forms_data):
    url = "https://api.together.xyz/inference"
    prompt = """
We have the following Django forms:
{forms_list}

For EACH form above, provide a SINGLE-LINE summary starting with the form number.
Example format:
1) The form LoginForm validates user credentials.
2) The form RegistrationForm handles user registration.
...
""".strip()

    # Generate the list of forms.
    forms_list = "\n".join([
        f"{i}) Name: {f['name']}, Fields: {', '.join(f.get('fields', []))}"
        for i, f in enumerate(forms_data, 1)
    ])
    prompt = prompt.replace("{forms_list}", forms_list)
    
    payload = {
        "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "prompt": prompt,
        "temperature": 0.5,
        "max_tokens": 500
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}
 
    try:
        max_retries = 2
        for attempt in range(max_retries):
            response = call_inference_api(url, headers, payload)
            if response.get("choices") and isinstance(response["choices"][0], dict) and "text" in response["choices"][0]:
                raw_text = response["choices"][0]["text"]
            else:
                raw_text = response["choices"][0]
            lines = raw_text.strip().split('\n')
            valid_lines = [line for line in lines if re.match(r'^\d+\)', line.strip())]
            pattern = r'^(\d+)\)\s*(.*)$'
            matches = []
            for line in valid_lines:
                m = re.match(pattern, line)
                if m:
                    matches.append({"num": int(m.group(1)), "text": m.group(2)})
            if len(matches) < len(forms_data):
                print(f"Attempt {attempt + 1} failed: Only {len(matches)} summaries for {len(forms_data)} forms. Retrying...")
                time.sleep(1)
                continue
            matches.sort(key=lambda x: x["num"])
            return [m["text"].strip() for m in matches]
        return ["Error: Max retries exceeded."] * len(forms_data)
    except requests.RequestException as e:
        return [f"Error generating AI summary: {str(e)}"] * len(forms_data) 
    
from unidiff import PatchSet,UnidiffParseError
import logging
import difflib



logger = logging.getLogger(__name__)
def apply_unified_diff(original_lines: list, diff: str) -> list:
    try:
        result_lines = original_lines.copy()
        hunks = re.split(r'^@@', diff, flags=re.MULTILINE)[1:]  # Skip diff header
        current_line = 0

        for hunk in hunks:
            # Parse hunk header (e.g., "-1,10 +1,15")
            header_match = re.match(r' -(\d+),(\d+) \+(\d+),(\d+) @@', '@@' + hunk.split('\n', 1)[0])
            if not header_match:
                logger.error(f"Invalid hunk header: {hunk[:100]}")
                return original_lines

            old_start, old_count, new_start, new_count = map(int, header_match.groups())
            if old_start < 1 or old_start + old_count - 1 > len(original_lines):
                logger.error(f"Hunk range out of bounds: old_start={old_start}, old_count={old_count}, file_lines={len(original_lines)}")
                return original_lines

            # Extract hunk lines
            hunk_lines = ('@@' + hunk).split('\n')[1:]
            new_lines = []
            expected_lines = []
            hunk_line_idx = 0
            i = old_start - 1

            # Process hunk lines
            while hunk_line_idx < len(hunk_lines) and i < len(original_lines):
                line = hunk_lines[hunk_line_idx]
                if line.startswith('-'):
                    if i >= len(original_lines) or original_lines[i] != line[1:]:
                        logger.error(f"Hunk line mismatch at line {i+1}: expected={line[1:][:50]}, got={original_lines[i][:50] if i < len(original_lines) else 'EOF'}")
                        return original_lines
                    expected_lines.append(original_lines[i])
                    i += 1
                    hunk_line_idx += 1
                elif line.startswith('+'):
                    new_lines.append(line[1:])
                    hunk_line_idx += 1
                elif line.startswith(' '):
                    if i >= len(original_lines) or original_lines[i] != line[1:]:
                        logger.error(f"Context line mismatch at line {i+1}: expected={line[1:][:50]}, got={original_lines[i][:50] if i < len(original_lines) else 'EOF'}")
                        return original_lines
                    new_lines.append(line[1:])
                    expected_lines.append(line[1:])
                    i += 1
                    hunk_line_idx += 1
                else:
                    logger.error(f"Invalid hunk line: {line[:100]}")
                    return original_lines

            if i != old_start + old_count - 1:
                logger.error(f"Hunk is longer than expected: processed {i - (old_start - 1)} lines, expected {old_count}")
                return original_lines

            # Apply changes
            result_lines = result_lines[:old_start - 1] + new_lines + result_lines[old_start + old_count - 1:]
            current_line = old_start + old_count - 1

        logger.debug(f"Applied diff successfully, result_lines={len(result_lines)}")
        return result_lines

    except Exception as e:
        logger.exception(f"Failed to apply unified diff: {e}")
        return original_lines