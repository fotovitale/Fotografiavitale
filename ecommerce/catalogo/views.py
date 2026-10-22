import json
from django.shortcuts import render
from .models import Categoria, Producto

NUMERO_WSP = "+5492634779824"
BG_CLASSES = ["bg-naranja", "bg-verde", "bg-rojo", "bg-azul"]


def _formatear_precio(precio):
    if precio is None:
        return "Consultar"
    entero = int(precio)
    return f"${entero:,}".replace(",", ".")


def _serializar_promo(producto, index=0):
    precio_str = _formatear_precio(producto.precio_final)
    imagen_url = producto.imagen.url if producto.imagen else ""
    wsp_text = f"Hola! Me interesa la promo de {producto.nombre}"
    if producto.precio_final:
        wsp_text += f" por {precio_str}"

    return {
        "id": producto.id,
        "badge": producto.etiqueta_promo or "OFERTA DESTACADA",
        "titulo": producto.nombre,
        "descripcion": producto.descripcion or producto.nombre,
        "precio": precio_str,
        "imagen": imagen_url,
        "bgClass": BG_CLASSES[index % len(BG_CLASSES)],
        "wspText": wsp_text,
    }


def _serializar_producto(producto):
    precio_str = _formatear_precio(producto.precio_final)
    imagen_principal = producto.imagen.url if producto.imagen else ""
    
    # Lista de todas las fotos (principal + adicionales)
    fotos = []
    if imagen_principal:
        fotos.append(imagen_principal)
    for img_extra in producto.imagenes.all():
        if img_extra.imagen:
            fotos.append(img_extra.imagen.url)

    return {
        "id": producto.id,
        "nombre": producto.nombre,
        "categoria": producto.categoria.slug if producto.categoria else "varios",
        "precio": precio_str,
        "precio_num": float(producto.precio_final) if producto.precio_final else None,
        "stock": producto.stock,
        "hay_stock": producto.hay_stock,
        "imagen": imagen_principal,
        "imagenes": fotos,
        "descripcion": producto.descripcion or "",
        "destacado": producto.destacado,
    }


def index(request):
    """Página de inicio (landing / index)."""
    promos_qs = Producto.objects.filter(activo=True, destacado=True).select_related("categoria")
    if not promos_qs.exists():
        # Fallback a los últimos 6 productos si no hay ninguno marcado como destacado
        promos_qs = Producto.objects.filter(activo=True).select_related("categoria")[:6]

    promos_data = [_serializar_promo(p, i) for i, p in enumerate(promos_qs)]

    context = {
        "promos": promos_data,
        "promos_json": json.dumps(promos_data, ensure_ascii=False),
        "numero_wsp": NUMERO_WSP,
    }
    return render(request, "index.html", context)


def catalogo(request):
    """Página completa del catálogo interactivo."""
    categorias = Categoria.objects.filter(activa=True).order_by("orden", "nombre")
    
    productos_qs = (
        Producto.objects.filter(activo=True)
        .select_related("categoria")
        .prefetch_related("imagenes")
        .order_by("-destacado", "-id")
    )


    promos_qs = (
        Producto.objects.filter(activo=True, destacado=True)
        .select_related("categoria")
        .order_by("-id")
    )
    if not promos_qs.exists():
        promos_qs = productos_qs.filter(precio__isnull=False)[:6]

    productos_data = [_serializar_producto(p) for p in productos_qs]
    promos_data = [_serializar_promo(p, i) for i, p in enumerate(promos_qs)]

    context = {
        "categorias": categorias,
        "productos": productos_qs,
        "productos_json": json.dumps(productos_data, ensure_ascii=False),
        "promos": promos_data,
        "promos_json": json.dumps(promos_data, ensure_ascii=False),
        "numero_wsp": NUMERO_WSP,
        "total_productos": len(productos_data),
    }
    return render(request, "catalogo.html", context)
