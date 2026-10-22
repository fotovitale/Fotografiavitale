"""
Modelos del catálogo: Categoria, Producto e ImagenProducto.

Notas de diseño:
- `precio` es opcional: si está vacío el producto se muestra como
  "Consultar" (igual que en el catálogo estático actual) y no se puede
  comprar online.
- `Producto.to_mp_item()` deja lista la conversión al formato de ítem que
  pide la API de Mercado Pago (Checkout Pro).
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify



def generar_slug_unico(instancia, texto, campo="slug"):
    """Genera un slug único para el modelo de `instancia` a partir de `texto`."""
    modelo = instancia.__class__
    max_len = modelo._meta.get_field(campo).max_length
    base = (slugify(texto) or "item")[:max_len]
    slug = base
    n = 2
    while modelo.objects.filter(**{campo: slug}).exclude(pk=instancia.pk).exists():
        sufijo = f"-{n}"
        slug = f"{base[: max_len - len(sufijo)]}{sufijo}"
        n += 1
    return slug


class Categoria(models.Model):
    nombre = models.CharField("nombre", max_length=100, unique=True)
    slug = models.SlugField(
        "identificador URL",
        max_length=120,
        unique=True,
        blank=True,
        help_text="Se completa solo a partir del nombre.",
    )
    orden = models.PositiveSmallIntegerField(
        "orden", default=0, help_text="Orden en la barra de filtros (menor = primero)."
    )
    activa = models.BooleanField("activa", default=True)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generar_slug_unico(self, self.nombre)
        super().save(*args, **kwargs)


class Producto(models.Model):
    # --- Datos básicos ---
    nombre = models.CharField("nombre", max_length=200)
    slug = models.SlugField(
        "identificador URL",
        max_length=220,
        unique=True,
        blank=True,
        help_text="Se completa solo a partir del nombre.",
    )
    sku = models.CharField(
        "código interno (SKU)",
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        help_text="Opcional. Código propio del local.",
    )
    descripcion = models.TextField("descripción", blank=True)
    categoria = models.ForeignKey(
        Categoria,
        verbose_name="categoría",
        on_delete=models.PROTECT,
        related_name="productos",
    )

    # --- Precio ---
    precio = models.DecimalField(
        "precio (ARS)",
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text='Dejar vacío para mostrar "Consultar".',
    )
    precio_oferta = models.DecimalField(
        "precio de oferta (ARS)",
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Opcional. Debe ser menor al precio normal.",
    )

    # --- Imagen y stock ---
    imagen = models.ImageField(
        "imagen principal", upload_to="productos/", blank=True
    )
    stock = models.PositiveIntegerField("stock", default=0)

    # --- Visibilidad / promociones ---
    activo = models.BooleanField(
        "visible en la tienda",
        default=True,
        help_text="Desmarcar para ocultarlo sin borrarlo.",
    )
    destacado = models.BooleanField(
        "destacado",
        default=False,
        help_text='Aparece en el carrusel de "Ofertas Especiales".',
    )
    etiqueta_promo = models.CharField(
        "etiqueta de promoción",
        max_length=40,
        blank=True,
        help_text='Ej: "OFERTA DESTACADA", "COMBO TECH".',
    )

    # --- Auditoría ---
    creado = models.DateTimeField("creado", auto_now_add=True)
    actualizado = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["categoria__orden", "nombre"]
        indexes = [
            models.Index(fields=["activo", "categoria"]),
            models.Index(fields=["destacado"]),
        ]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generar_slug_unico(self, self.nombre)
        if self.sku == "":
            self.sku = None  # Evita choques de unicidad con SKU vacíos.
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.precio_oferta is not None:
            if self.precio is None:
                raise ValidationError(
                    {"precio_oferta": "Para cargar una oferta primero definí el precio normal."}
                )
            if self.precio_oferta >= self.precio:
                raise ValidationError(
                    {"precio_oferta": "El precio de oferta debe ser menor al precio normal."}
                )

    # ------------------------------------------------------------------
    # Lógica de negocio
    # ------------------------------------------------------------------
    @property
    def precio_a_consultar(self):
        return self.precio is None

    @property
    def en_oferta(self):
        return self.precio is not None and self.precio_oferta is not None

    @property
    def precio_final(self):
        """Precio que paga el cliente (oferta si existe). None si es "Consultar"."""
        if self.en_oferta:
            return self.precio_oferta
        return self.precio

    @property
    def hay_stock(self):
        return self.stock > 0

    @property
    def stock_bajo(self):
        return self.stock <= getattr(settings, "STOCK_BAJO_UMBRAL", 2)

    @property
    def se_puede_comprar(self):
        """True si puede venderse online (si no, se mantiene la consulta por WhatsApp)."""
        return self.activo and self.precio_final is not None and self.hay_stock

    # ------------------------------------------------------------------
    # Integración Mercado Pago
    # ------------------------------------------------------------------
    def to_mp_item(self, cantidad=1, request=None):
        """
        Devuelve el ítem en el formato que espera la API de preferencias de
        Mercado Pago. `request` se usa para armar la URL absoluta de la foto.
        """
        if not self.se_puede_comprar:
            raise ValueError(f'El producto "{self}" no está disponible para la venta online.')
        if cantidad < 1 or cantidad > self.stock:
            raise ValueError(f'Cantidad inválida para "{self}" (stock: {self.stock}).')

        item = {
            "id": self.sku or str(self.pk),
            "title": self.nombre[:256],
            "description": (self.descripcion or self.nombre)[:256],
            "category_id": self.categoria.slug,
            "quantity": int(cantidad),
            "unit_price": float(self.precio_final),
            "currency_id": getattr(settings, "MONEDA", "ARS"),
        }
        if self.imagen and request is not None:
            item["picture_url"] = request.build_absolute_uri(self.imagen.url)
        return item


class ImagenProducto(models.Model):
    """Fotos adicionales de un producto (galería)."""

    producto = models.ForeignKey(
        Producto,
        verbose_name="producto",
        on_delete=models.CASCADE,
        related_name="imagenes",
    )
    imagen = models.ImageField("imagen", upload_to="productos/galeria/")
    orden = models.PositiveSmallIntegerField("orden", default=0)

    class Meta:
        verbose_name = "imagen adicional"
        verbose_name_plural = "imágenes adicionales"
        ordering = ["orden", "id"]

    def __str__(self):
        return f"Imagen de {self.producto}"


class SiteStatistics(models.Model):
    """
    Modelo Singleton para estadísticas globales del sitio y catálogo.
    Mantiene un contador persistente del total acumulado de visitas.
    """

    total_visitas = models.PositiveBigIntegerField(
        "total de visitas",
        default=0,
        help_text="Contador global acumulado de visitas a la tienda.",
    )
    ultima_visita = models.DateTimeField(
        "última visita",
        auto_now=True,
        help_text="Fecha y hora de la última visita registrada.",
    )

    class Meta:
        verbose_name = "estadística del sitio"
        verbose_name_plural = "estadísticas del sitio"

    def __str__(self):
        return f"Estadísticas del Sitio ({self.total_visitas} visitas)"

    def save(self, *args, **kwargs):
        # Patrón Singleton: fuerza siempre la clave primaria a 1
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Protege el registro único para evitar pérdida de métricas
        pass

    @classmethod
    def obtener(cls):
        """Obtiene o crea la instancia única de estadísticas (Singleton)."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def incrementar(cls):
        """
        Incrementa de forma atómica y concurrente (+1) el contador de visitas.
        Usa F() expressions para evitar condiciones de carrera (race conditions).
        """
        cls.objects.get_or_create(pk=1)
        cls.objects.filter(pk=1).update(
            total_visitas=models.F("total_visitas") + 1,
            ultima_visita=timezone.now(),
        )

