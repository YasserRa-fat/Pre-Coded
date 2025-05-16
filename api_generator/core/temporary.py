from django.test import Client
from create_api.models import AIChangeRequest

JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzQ2NTM3NjkzLCJpYXQiOjE3NDY1MzQwOTMsImp0aSI6ImFjMjFjOGIxYmRlODRkYzdiNTRlYzExOTRkZTM2ZmEwIiwidXNlcl9pZCI6MX0.WhfU_P6uQpIg8UvTxXTH5xpnLw-InnF6Utk4WsznVk8"

def shell_preview_test(change_id, file_path, mode="before"):
    """
    Hit the preview endpoint exactly like the WS consumer would,
    using the hard‑coded JWT for authentication.
    """
    change = AIChangeRequest.objects.get(pk=change_id)
    pid    = change.project_id

    client = Client(HTTP_AUTHORIZATION=f"Bearer {JWT}")
    url = (
        f"/api/projects/{pid}/preview/"
        f"?change_id={change_id}"
        f"&file={file_path}"
        f"&mode={mode}"
    )
    resp = client.get(url)
    print(f"GET {url!r} → {resp.status_code}")
    print(resp.content.decode("utf8")[:200].replace("\n"," ") + " …")
