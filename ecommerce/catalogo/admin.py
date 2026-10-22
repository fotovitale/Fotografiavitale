"""Panel de administración del catálogo (pensado para empleados del local)."""
from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import Categoria, ImagenProducto, Producto


def _miniatura(imagen, alto=50):
    if not imagen:
        return mark_safe('<span style="color:#999;">Sin foto</span>')
    return format_html(
        '<img src="{}" style="height:{}px;width:auto;border-radius:6px;'
        'object-fit:contain;background:#fff;border:1px solid #ddd;">',
        imagen.url,
        alto,
    )


class ImagenProductoInline(admin.TabularInline):
    model = ImagenProducto
    extra = 1
    fields = ("vista_previa", "imagen", "orden")
    readonly_fields = ("vista_previa",)

    @admin.display(description="Vista previa")
    def vista_previa(self, obj):
        return _miniatura(obj.imagen if obj else None, alto=70)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "orden", "activa", "cantidad_productos")
    list_editable = ("orden", "activa")
    search_fields = ("nombre",)
    prepopulated_fields = {"slug": ("nombre",)}

    @admin.display(description="Productos")
    def cantidad_productos(self, obj):
        return obj.productos.count()


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    # --- Listado ---
    list_display = (
        "miniatura",
        "nombre",
        "categoria",
        "precio",
        "precio_oferta",
        "stock",
        "estado_stock",
        "activo",
        "destacado",
    )
    list_display_links = ("miniatura", "nombre")
    # Edición rápida directamente desde la lista:
    list_editable = ("precio", "precio_oferta", "stock", "activo", "destacado")
    list_filter = ("categoria", "activo", "destacado")
    search_fields = ("nombre", "sku", "descripcion")
    list_per_page = 50
    list_select_related = ("categoria",)
    save_on_top = True
    actions = ("marcar_activo", "marcar_inactivo", "marcar_destacado", "quitar_destacado")

    # --- Formulario ---
    prepopulated_fields = {"slug": ("nombre",)}
    readonly_fields = ("vista_previa", "creado", "actualizado")
    inlines = (ImagenProductoInline,)
    fieldsets = (
        ("Datos del producto", {"fields": ("nombre", "categoria", "descripcion")}),
        ("Precio y stock", {"fields": (("precio", "precio_oferta"), "stock")}),
        ("Imagen principal", {"fields": ("vista_previa", "imagen")}),
        (
            "Visibilidad y promociones",
            {"fields": ("activo", "destacado", "etiqueta_promo")},
        ),
        (
            "Avanzado",
            {
                "classes": ("collapse",),
                "fields": ("slug", "sku", "creado", "actualizado"),
            },
        ),
    )

    # --- Columnas personalizadas ---
    @admin.display(description="Foto")
    def miniatura(self, obj):
        return _miniatura(obj.imagen)

    @admin.display(description="Vista previa")
    def vista_previa(self, obj):
        return _miniatura(obj.imagen if obj else None, alto=160)

    @admin.display(description="Estado")
    def estado_stock(self, obj):
        if obj.stock == 0:
            return format_html('<b style="color:#c0392b;">{}</b>', "Sin stock")
        if obj.stock_bajo:
            return format_html('<b style="color:#e67e22;">{}</b>', "Stock bajo")
        return format_html('<span style="color:#27ae60;">{}</span>', "OK")

    # --- Acciones masivas ---
    def _actualizar(self, request, queryset, mensaje, **campos):
        n = queryset.update(**campos)
        self.message_user(request, f"{n} producto(s) {mensaje}.", messages.SUCCESS)

    @admin.action(description="Mostrar en la tienda", permissions=["change"])
    def marcar_activo(self, request, queryset):
        self._actualizar(request, queryset, "visibles en la tienda", activo=True)

    @admin.action(description="Ocultar de la tienda", permissions=["change"])
    def marcar_inactivo(self, request, queryset):
        self._actualizar(request, queryset, "ocultos", activo=False)

    @admin.action(description="Marcar como destacado", permissions=["change"])
    def marcar_destacado(self, request, queryset):
        self._actualizar(request, queryset, "marcados como destacados", destacado=True)

    @admin.action(description="Quitar de destacados", permissions=["change"])
    def quitar_destacado(self, request, queryset):
        self._actualizar(request, queryset, "quitados de destacados", destacado=False)
