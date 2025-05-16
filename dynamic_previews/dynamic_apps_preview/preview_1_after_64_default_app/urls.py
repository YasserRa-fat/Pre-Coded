from django.urls import path, include
from django.conf import settings

urlpatterns = [
    # Include original project URLs
    path('', include('projects.1.urls')),
]

# Add preview-specific settings
# This allows the preview to operate independently
if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
