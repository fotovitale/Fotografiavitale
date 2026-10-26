from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="inicio"),
    path("index.html", views.index, name="inicio_html"),
    path("catalogo/", views.catalogo, name="catalogo"),
    path("catalogo.html", views.catalogo, name="catalogo_html"),
    path("carrito/", views.carrito, name="carrito"),
    path("carrito.html", views.carrito, name="carrito_html"),
    path("checkout/", views.checkout, name="checkout"),
    path("pago/exitoso/", views.pago_exitoso, name="pago_exitoso"),
    # Autenticación y perfil de usuario
    path("registro/", views.registro_view, name="registro"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("perfil/", views.perfil_view, name="perfil"),
    # Technical SEO y Crawlers
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("llms.txt", views.llms_txt, name="llms_txt"),
]

