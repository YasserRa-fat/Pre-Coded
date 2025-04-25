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
    Serve /media/<path> by loading the file out of our MediaFile model.
    """
    try:
        record = MediaFile.objects.get(path=path)
    except MediaFile.DoesNotExist:
        raise Http404(f"No media file for {path!r}")

    # record.file is a FieldFile, so we can open() and stream it
    file_obj = record.file.open('rb')
    return FileResponse(file_obj, 
                        content_type=record.file.file.content_type  
                        if hasattr(record.file.file, 'content_type') else None)
