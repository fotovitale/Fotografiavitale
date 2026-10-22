"""
Middleware personalizado para registrar visitas en el contador global del sitio.
"""
from django.conf import settings
from .models import SiteStatistics


class ContadorVisitasMiddleware:
    """
    Middleware que incrementa +1 en SiteStatistics cada vez que un usuario
    carga la página principal o la página del catálogo.
    Ignora deliberadamente peticiones a /admin/, estáticos y multimedia.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Solo contar peticiones GET exitosas (200 OK)
        if request.method == "GET" and response.status_code == 200:
            path = request.path

            # Ignorar /admin/, estáticos, multimedia y favicon
            if not self._es_ruta_ignorada(path):
                if self._es_ruta_catalogo(path):
                    try:
                        SiteStatistics.incrementar()
                    except Exception:
                        pass

        return response

    def _es_ruta_ignorada(self, path):
        if path.startswith("/admin/"):
            return True
        static_url = getattr(settings, "STATIC_URL", "/static/")
        if static_url and path.startswith(static_url):
            return True
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if media_url and path.startswith(media_url):
            return True
        if path == "/favicon.ico":
            return True
        return False

    def _es_ruta_catalogo(self, path):
        # Página principal (index) y catálogo general
        return path in {"/", "/index.html", "/catalogo/", "/catalogo.html"} or path.startswith("/catalogo")
