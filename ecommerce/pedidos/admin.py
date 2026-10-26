"""
Admin de pedidos y pagos.

Los pedidos y pagos los generará el sistema (checkout + webhooks de
Mercado Pago), por eso desde el admin son de solo lectura, salvo el
estado y las notas internas del pedido (ej. marcar como "Entregado").
"""
from django.contrib import admin

from .models import ItemPedido, Pago, Pedido


class SoloLecturaInlineMixin:
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ItemPedidoInline(SoloLecturaInlineMixin, admin.TabularInline):
    model = ItemPedido
    fields = ("nombre_producto", "precio_unitario", "cantidad", "subtotal")
    readonly_fields = fields

    @admin.display(description="Subtotal")
    def subtotal(self, obj):
        return obj.subtotal


class PagoInline(SoloLecturaInlineMixin, admin.TabularInline):
    model = Pago
    fields = ("mp_payment_id", "estado_mp", "estado_detalle", "monto", "metodo_pago", "creado")
    readonly_fields = fields


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("id", "codigo_corto", "nombre_completo_display", "usuario", "requiere_fotos", "email", "envio_nombre", "total", "estado", "creado")
    list_filter = ("estado", "requiere_fotos", "creado", "envio_modalidad")
    search_fields = ("id", "codigo", "nombre", "apellido", "email", "telefono", "calle", "localidad", "mp_preference_id", "usuario__username", "usuario__email")
    date_hierarchy = "creado"
    inlines = (ItemPedidoInline, PagoInline)
    readonly_fields = (
        "codigo",
        "usuario",
        "nombre",
        "apellido",
        "email",
        "telefono",
        "calle",
        "numero",
        "piso_depto",
        "localidad",
        "codigo_postal",
        "envio_nombre",
        "envio_modalidad",
        "costo_envio",
        "requiere_fotos",
        "subtotal",
        "total",
        "mp_preference_id",
        "creado",
        "actualizado",
    )
    fieldsets = (
        ("Pedido", {"fields": ("codigo", "usuario", "estado", "requiere_fotos", "subtotal", "costo_envio", "total", "notas")}),
        ("Comprador", {"fields": ("nombre", "apellido", "email", "telefono")}),
        ("Dirección y Envío", {"fields": ("envio_nombre", "envio_modalidad", "calle", "numero", "piso_depto", "localidad", "codigo_postal")}),
        ("Mercado Pago", {"fields": ("mp_preference_id",)}),
        ("Fechas", {"fields": ("creado", "actualizado")}),
    )

    def has_add_permission(self, request):
        return False

    @admin.display(description="Cliente", ordering="nombre")
    def nombre_completo_display(self, obj):
        return obj.nombre_completo

    @admin.display(description="Código", ordering="codigo")
    def codigo_corto(self, obj):
        return str(obj.codigo)[:8].upper()


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("mp_payment_id", "pedido", "estado_mp", "monto", "metodo_pago", "creado")
    list_filter = ("estado_mp", "metodo_pago")
    search_fields = ("mp_payment_id", "pedido__codigo", "pedido__email")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
