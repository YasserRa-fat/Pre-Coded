def has_marker_areas(content, file_path=None):
    """
    Check if content contains marker areas for dynamic changes.
    
    Args:
        content (str): The content to check
        file_path (str, optional): The file path, used to determine if Python or other file type
    
    Returns:
        bool: True if marker areas are found, False otherwise
    """
    if not content:
        return False
    
    # Check if Python file based on extension
    is_python = file_path and file_path.endswith('.py') if file_path else False
    
    # Define markers based on file type
    if is_python:
        add_marker_start = "# DJANGO-AI-ADD-START"
        remove_marker_start = "# DJANGO-AI-REMOVE-START"
    else:
        add_marker_start = "<!-- DJANGO-AI-ADD-START -->"
        remove_marker_start = "<!-- DJANGO-AI-REMOVE-START -->"
    
    # Check if markers exist in content
    return add_marker_start in content or remove_marker_start in content 