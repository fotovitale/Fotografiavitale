"""Rutas principales del proyecto."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

# Textos del panel de administración
admin.site.site_header = "Fotografía Vitale — Administración"
admin.site.site_title = "Fotografía Vitale"
admin.site.index_title = "Gestión de la tienda"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("catalogo.urls")),
]

handler404 = "catalogo.views.custom_404_view"

if settings.DEBUG:
    # En desarrollo Django sirve las imágenes subidas desde el admin.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

