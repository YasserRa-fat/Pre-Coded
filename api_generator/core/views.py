from django.shortcuts import render
import mimetypes
from django.http import FileResponse, Http404, HttpResponse
from create_api.models import StaticFile, MediaFile, AIChangeRequest
import json
from django.views.static import serve as static_serve
import os
import rest_framework

# Compute the on-disk path to DRF's own "static/rest_framework" folder:
DRF_STATIC_ROOT = os.path.join(
    os.path.dirname(rest_framework.__file__),
    "static", "rest_framework"
)

def serve_db_static(request, path):
    """
    Serve a static file out of the DB for any URL /static/<path>.
    Handles preview_mode="after" for AI-proposed changes.
    """
    # Handle preview mode "after"
    if request.GET.get("preview_mode") == "after" and request.GET.get("preview_change_id"):
        change_id = request.GET.get("preview_change_id")
        try:
            change = AIChangeRequest.objects.get(pk=change_id)
            diff = json.loads(change.diff or "{}")
            
            # Look for the file in the diff
            for file_path, file_data in diff.items():
                if file_path == path or file_path == f"static/{path}":
                    if 'preview' in file_data and 'after' in file_data['preview']:
                        content = file_data['preview']['after']
                        content_type = "text/css" if path.endswith(".css") else "application/javascript" if path.endswith(".js") else "text/plain"
                        return HttpResponse(content, content_type=content_type)
        except AIChangeRequest.DoesNotExist:
            pass
    
    # Serve from database
    try:
        record = StaticFile.objects.get(path=path)
        f = record.file.open('rb')
        content_type, _ = mimetypes.guess_type(path)
        return FileResponse(f, content_type=content_type or 'application/octet-stream')
    except StaticFile.DoesNotExist:
        raise Http404(f"No static file found for {path!r}")

def serve_db_media(request, path):
    """
    Serve /media/<path> by loading the file out of our MediaFile model.
    Also handles preview mode for AI changes.
    """
    # Handle preview mode "after"
    if request.GET.get("preview_mode") == "after" and request.GET.get("preview_change_id"):
        change_id = request.GET.get("preview_change_id")
        try:
            change = AIChangeRequest.objects.get(pk=change_id)
            diff = json.loads(change.diff or "{}")
            
            # Look for the file in the diff
            for file_path, file_data in diff.items():
                if file_path == path or file_path == f"media/{path}":
                    if 'preview' in file_data and 'after' in file_data['preview']:
                        content = file_data['preview']['after']
                        content_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
                        return HttpResponse(content, content_type=content_type)
        except AIChangeRequest.DoesNotExist:
            pass

    try:
        record = MediaFile.objects.get(path=path)
    except MediaFile.DoesNotExist:
        raise Http404(f"No media file for {path!r}")

    # record.file is a FieldFile, so we can open() and stream it
    file_obj = record.file.open('rb')
    return FileResponse(file_obj, 
                        content_type=record.file.file.content_type  
                        if hasattr(record.file.file, 'content_type') else None)

def serve_drf_static(request, path):
    """
    Serve any /static/rest_framework/... asset from DRF's package.
    """
    return static_serve(request, path, document_root=DRF_STATIC_ROOT)