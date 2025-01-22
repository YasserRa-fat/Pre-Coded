import re

def parse_code_with_comments(code):
    json_data = {
        "fields": []
    }
    
    lines = code.splitlines()
    field = None
    inside_multiline_comment = False
    multiline_comment = ""

    for line in lines:
        # Handle multiline comments
        if '"""' in line:
            if inside_multiline_comment:
                multiline_comment += f"\n{line.strip()}"
                if field:
                    field["comments"].append({
                        "type": "multiline",
                        "text": multiline_comment.strip(),
                        "position": "after"
                    })
                multiline_comment = ""
                inside_multiline_comment = False
            else:
                multiline_comment = line.strip()
                inside_multiline_comment = True
            continue

        if inside_multiline_comment:
            multiline_comment += f"\n{line.strip()}"
            continue

        # Match field definitions
        field_match = re.match(r'(\w+)\s*=\s*models\.(\w+Field)\((.*)\)', line)
        inline_comment_match = re.search(r'#(.*)', line)
        
        if field_match:
            field_name, field_type, parameters = field_match.groups()
            field = {
                "name": field_name,
                "type": field_type,
                "parameters": parse_parameters(parameters),
                "comments": []
            }
            json_data["fields"].append(field)

        # Handle inline comment if there's an ongoing field
        if inline_comment_match and field:
            comment_text = inline_comment_match.group(1).strip()
            field["comments"].append({
                "type": "inline",
                "text": f"#{comment_text}",
                "position": "after"
            })

    return json_data

def parse_parameters(parameter_string):
    parameters = {}
    if not parameter_string:
        return parameters

    params = re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', parameter_string)
    
    for param in params:
        match = re.match(r'(\w+)\s*=\s*"(.*?)"', param)
        if match:
            key, value = match.groups()
            parameters[key] = value
    
    return parameters



def generate_code_from_json(data):
    fields = data.get("fields", [])
    code_lines = []

    for field in fields:
        field_name = field.get('name')
        field_type = field.get('type')
        parameters = field.get('parameters', {})

        # Ensure parameters is a dictionary
        if not isinstance(parameters, dict):
            raise ValueError(f"Parameters for field '{field_name}' must be a dictionary")

        parameters_string = ", ".join(f"{k}={v}" for k, v in parameters.items())
        code_lines.append(f"{field_name} = models.{field_type}({parameters_string})")

    return "\n".join(code_lines)

