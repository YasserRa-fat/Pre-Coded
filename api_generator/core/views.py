from django.shortcuts import render

# Create your views here.
import mimetypes
from django.http import FileResponse, Http404
from create_api.models import StaticFile, MediaFile

def serve_db_static(request, path):
    """
    Serve a static file out of the DB for any URL /static/<path>.
    """
    try:
        rec = StaticFile.objects.get(path=path)
    except StaticFile.DoesNotExist:
        raise Http404(f"No static file found for {path!r}")
    # rec.file is a Django FileField; .open() returns a file‐like
    f = rec.file.open('rb')
    content_type, _ = mimetypes.guess_type(path)
    return FileResponse(f, content_type=content_type or 'application/octet-stream')

def serve_db_media(request, path):
    """
    Serve an uploaded media file out of the DB for any URL /media/<path>.
    """
    try:
        rec = MediaFile.objects.get(path=path)
    except MediaFile.DoesNotExist:
        raise Http404(f"No media file found for {path!r}")
    f = rec.file.open('rb')
    content_type, _ = mimetypes.guess_type(path)
    return FileResponse(f, content_type=content_type or 'application/octet-stream')
