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

    # Usuario registrado (opcional para permitir compras como invitado)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos",
        verbose_name="usuario",
        help_text="Usuario registrado que realizó la compra (opcional para invitados).",
    )

    # Datos del comprador
    nombre = models.CharField("nombre", max_length=150)
    apellido = models.CharField("apellido", max_length=150, blank=True)
    email = models.EmailField("email")
    telefono = models.CharField("teléfono", max_length=50, blank=True)

    # Datos postales y de entrega
    calle = models.CharField("calle", max_length=200, blank=True)
    numero = models.CharField("número", max_length=20, blank=True)
    piso_depto = models.CharField("piso / depto", max_length=50, blank=True)
    localidad = models.CharField("localidad", max_length=100, blank=True)
    codigo_postal = models.CharField("código postal", max_length=20, blank=True)

    # Datos del envío
    envio_nombre = models.CharField("transporte / correo", max_length=100, blank=True)
    envio_modalidad = models.CharField("modalidad de envío", max_length=50, blank=True)
    costo_envio = models.DecimalField(
        "costo de envío (ARS)", max_digits=12, decimal_places=2, default=Decimal("0")
    )

    # Validación de personalización
    requiere_fotos = models.BooleanField(
        "requiere fotos",
        default=False,
        help_text="Indica si al menos uno de los productos requiere envío de fotos del cliente.",
    )

    # Totales y estado
    subtotal = models.DecimalField(
        "subtotal productos (ARS)", max_digits=12, decimal_places=2, default=Decimal("0")
    )
    total = models.DecimalField(
        "total (ARS)", max_digits=12, decimal_places=2, default=Decimal("0")
    )
    estado = models.CharField(
        "estado", max_length=20, choices=Estado.choices, default=Estado.PENDIENTE
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

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}".strip()

    def __str__(self):
        return f"Pedido #{self.id or ''} ({str(self.codigo)[:8].upper()}) - {self.nombre_completo}"

    @property
    def external_reference(self):
        return str(self.codigo)

    @property
    def necesita_fotos(self):
        """Devuelve True si el pedido requiere fotos personalizadas."""
        if self.requiere_fotos:
            return True
        return any(
            bool(item.producto and getattr(item.producto, "requiere_fotos", False))
            for item in self.items.select_related("producto").all()
        )

    def verificar_requiere_fotos(self, guardar=True):
        """Verifica y actualiza el campo requiere_fotos según los productos asociados."""
        tiene = any(
            bool(item.producto and getattr(item.producto, "requiere_fotos", False))
            for item in self.items.select_related("producto").all()
        )
        if self.requiere_fotos != tiene:
            self.requiere_fotos = tiene
            if guardar and self.pk:
                self.save(update_fields=["requiere_fotos", "actualizado"])
        return self.requiere_fotos

    def recalcular_total(self, guardar=True):
        subtotal = self.items.aggregate(
            t=Sum(F("precio_unitario") * F("cantidad"))
        )["t"] or Decimal("0")
        self.subtotal = subtotal
        self.total = subtotal + (self.costo_envio or Decimal("0"))
        if guardar:
            self.save(update_fields=["subtotal", "total", "actualizado"])
        return self.total

    def to_mp_preference(self, back_urls=None, notification_url=None, request=None, external_reference=None):
        """
        Arma el cuerpo de la preferencia para Checkout Pro.
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

        payer_data = {
            "name": self.nombre,
            "email": self.email,
        }
        if self.apellido:
            payer_data["surname"] = self.apellido
        if self.telefono:
            payer_data["phone"] = {"number": self.telefono}
        if self.calle:
            num = 0
            if self.numero and self.numero.isdigit():
                num = int(self.numero)
            payer_data["address"] = {
                "street_name": self.calle,
                "street_number": num,
                "zip_code": self.codigo_postal or "",
            }

        preferencia = {
            "items": items,
            "payer": payer_data,
            "external_reference": str(external_reference or self.codigo),
            "statement_descriptor": "FOTOGRAFIA VITALE",
        }
        if back_urls:
            preferencia["back_urls"] = back_urls
            success_url = str(back_urls.get("success") or "")
            if not success_url.startswith("http://"):
                preferencia["auto_return"] = "approved"
        else:
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
