import re

FILE_TYPE_KEYWORDS = {
    'template':    [r'\.html$', r'template', r'font', r'color', r'style'],
    'model':       [r'\bmodel\b', r'\.py'],
    'view':        [r'\bview\b', r'APIView', r'\.py'],
    'form':        [r'\bform\b', r'\.py'],
    'static':      [r'\.css$', r'\.js$'],
}
import os
def classify_request(text, candidates):
    """
    Return (file_type, best_path).  file_type in
    ('template','model','view','form','static','other').
    best_path is the chosen file or None.
    """
    lowered = text.lower()

    # 1) Urls → template
    if 'http://' in text or 'https://' in text:
        file_type = 'template'
    # 2) style words → template
    elif any(kw in lowered for kw in ('font','color','style','css','layout')):
        file_type = 'template'
    else:
        file_type = 'other'

    # 3) keyword scan overrides
    for kind, patterns in FILE_TYPE_KEYWORDS.items():
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                file_type = kind
                break
        if file_type == kind:
            break

    # 4) if user mentioned a filename explicitly
    best = None
    for path in candidates:
        name = os.path.basename(path).lower()
        if name in lowered:
            best = path
            break

    # 5) for templates: pick homepage/feed before base.html
    if file_type == 'template' and not best:
        # prefer any of these names
        for path in candidates:
            n = os.path.basename(path).lower()
            if n in ('index.html','home.html','homepage.html','feed.html'):
                best = path
                break
        # then any containing those substrings
        if not best:
            for path in candidates:
                nl = path.lower()
                if 'index.html' in nl or 'feed.html' in nl:
                    best = path
                    break
        # last, base.html
        if not best and 'base.html' in candidates:
            best = 'base.html'


    # Always return a tuple
    return file_type, best