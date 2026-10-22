from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="inicio"),
    path("index.html", views.index, name="inicio_html"),
    path("catalogo/", views.catalogo, name="catalogo"),
    path("catalogo.html", views.catalogo, name="catalogo_html"),
]
