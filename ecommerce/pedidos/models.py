"""
Modelos de pedidos y pagos.

Preparados para Mercado Pago Checkout Pro:
- `Pedido.codigo` (UUID) se envía como `external_reference`, así cuando
  Mercado Pago notifica un pago sabemos a qué pedido corresponde.
- `Pedido.mp_preference_id` guarda el ID de la preferencia creada.
- `Pago` registra cada notificación (webhook) con la respuesta completa.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Sum


class Pedido(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de pago"
        PAGADO = "pagado", "Pagado"
        CANCELADO = "cancelado", "Cancelado"
        ENTREGADO = "entregado", "Entregado"

    codigo = models.UUIDField(
        "código", default=uuid.uuid4, unique=True, editable=False
    )

    # Datos del comprador
    nombre = models.CharField("nombre y apellido", max_length=150)
    email = models.EmailField("email")
    telefono = models.CharField("teléfono", max_length=30, blank=True)

    estado = models.CharField(
        "estado", max_length=20, choices=Estado.choices, default=Estado.PENDIENTE
    )
    total = models.DecimalField(
        "total (ARS)", max_digits=12, decimal_places=2, default=Decimal("0")
    )
    notas = models.TextField("notas internas", blank=True)

    # Mercado Pago
    mp_preference_id = models.CharField(
        "ID de preferencia (Mercado Pago)", max_length=100, blank=True
    )

    creado = models.DateTimeField("creado", auto_now_add=True)
    actualizado = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        ordering = ["-creado"]

    def __str__(self):
        return f"Pedido {str(self.codigo)[:8].upper()} - {self.nombre}"

    @property
    def external_reference(self):
        return str(self.codigo)

    def recalcular_total(self, guardar=True):
        total = self.items.aggregate(
            t=Sum(F("precio_unitario") * F("cantidad"))
        )["t"] or Decimal("0")
        self.total = total
        if guardar:
            self.save(update_fields=["total", "actualizado"])
        return total

    def to_mp_preference(self, back_urls=None, notification_url=None, request=None):
        """
        Arma el cuerpo de la preferencia para Checkout Pro. Se completa con
        las URLs reales cuando se implementen las vistas de pago.
        """
        items = []
        for item in self.items.select_related("producto"):
            datos = {
                "id": (item.producto.sku or str(item.producto.pk)) if item.producto else "",
                "title": item.nombre_producto[:256],
                "quantity": int(item.cantidad),
                "unit_price": float(item.precio_unitario),
                "currency_id": getattr(settings, "MONEDA", "ARS"),
            }
            if item.producto and item.producto.imagen and request is not None:
                datos["picture_url"] = request.build_absolute_uri(item.producto.imagen.url)
            items.append(datos)

        preferencia = {
            "items": items,
            "payer": {"name": self.nombre, "email": self.email},
            "external_reference": self.external_reference,
            "statement_descriptor": "FOTOGRAFIA VITALE",
        }
        if back_urls:
            preferencia["back_urls"] = back_urls
            preferencia["auto_return"] = "approved"
        if notification_url:
            preferencia["notification_url"] = notification_url
        return preferencia


class ItemPedido(models.Model):
    pedido = models.ForeignKey(
        Pedido, verbose_name="pedido", on_delete=models.CASCADE, related_name="items"
    )
    producto = models.ForeignKey(
        "catalogo.Producto",
        verbose_name="producto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items_pedido",
    )
    # Copias al momento de la compra: cambiar el precio del producto después
    # no modifica pedidos ya realizados.
    nombre_producto = models.CharField("producto", max_length=200, blank=True)
    precio_unitario = models.DecimalField(
        "precio unitario", max_digits=12, decimal_places=2, blank=True, null=True
    )
    cantidad = models.PositiveIntegerField(
        "cantidad", default=1, validators=[MinValueValidator(1)]
    )

    class Meta:
        verbose_name = "ítem"
        verbose_name_plural = "ítems"

    def __str__(self):
        return f"{self.cantidad} x {self.nombre_producto}"

    @property
    def subtotal(self):
        return (self.precio_unitario or Decimal("0")) * self.cantidad

    def save(self, *args, **kwargs):
        if self.producto_id:
            if not self.nombre_producto:
                self.nombre_producto = self.producto.nombre
            if self.precio_unitario is None:
                self.precio_unitario = self.producto.precio_final
        super().save(*args, **kwargs)


class Pago(models.Model):
    """Cada notificación de pago recibida desde Mercado Pago."""

    class EstadoMP(models.TextChoices):
        PENDING = "pending", "Pendiente"
        APPROVED = "approved", "Aprobado"
        AUTHORIZED = "authorized", "Autorizado"
        IN_PROCESS = "in_process", "En revisión"
        IN_MEDIATION = "in_mediation", "En mediación"
        REJECTED = "rejected", "Rechazado"
        CANCELLED = "cancelled", "Cancelado"
        REFUNDED = "refunded", "Devuelto"
        CHARGED_BACK = "charged_back", "Contracargo"

    pedido = models.ForeignKey(
        Pedido, verbose_name="pedido", on_delete=models.CASCADE, related_name="pagos"
    )
    mp_payment_id = models.CharField("ID de pago (Mercado Pago)", max_length=100, unique=True)
    estado_mp = models.CharField(
        "estado", max_length=20, choices=EstadoMP.choices, default=EstadoMP.PENDING
    )
    estado_detalle = models.CharField("detalle del estado", max_length=100, blank=True)
    monto = models.DecimalField("monto", max_digits=12, decimal_places=2, null=True, blank=True)
    metodo_pago = models.CharField("método de pago", max_length=50, blank=True)
    respuesta_cruda = models.JSONField("respuesta de Mercado Pago", default=dict, blank=True)
    creado = models.DateTimeField("recibido", auto_now_add=True)

    class Meta:
        verbose_name = "pago"
        verbose_name_plural = "pagos"
        ordering = ["-creado"]

    def __str__(self):
        return f"Pago {self.mp_payment_id} ({self.get_estado_mp_display()})"

    @property
    def aprobado(self):
        return self.estado_mp == self.EstadoMP.APPROVED
