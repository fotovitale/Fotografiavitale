"""
Integración con Mercado Pago (Checkout Pro) — ESQUELETO.

Este módulo todavía NO llama a la API. Deja definidos los puntos de
entrada para la próxima fase.

Pasos para completarlo:
1. `pip install mercadopago` y agregarlo a requirements.txt.
2. Cargar MERCADOPAGO_ACCESS_TOKEN / PUBLIC_KEY en el archivo .env
   (usar primero las credenciales de PRUEBA).
3. Implementar `crear_preferencia` con:
       sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
       respuesta = sdk.preference().create(pedido.to_mp_preference(...))
4. Implementar `procesar_webhook` consultando el pago:
       sdk.payment().get(payment_id)
   y registrar un `Pago`; si queda "approved", marcar el pedido como
   pagado y descontar stock (dentro de una transacción).
5. Crear las vistas: checkout, back_urls (éxito/fallo/pendiente) y el
   endpoint del webhook (exento de CSRF, validando la firma con
   MERCADOPAGO_WEBHOOK_SECRET).

Docs: https://www.mercadopago.com.ar/developers/es/docs/checkout-pro/landing
"""
from django.conf import settings


def credenciales_configuradas():
    """True si están cargadas las credenciales de Mercado Pago en el .env."""
    return bool(settings.MERCADOPAGO_ACCESS_TOKEN and settings.MERCADOPAGO_PUBLIC_KEY)


def crear_preferencia(pedido, request):
    """
    Crea una preferencia de pago para `pedido` y devuelve la URL de pago
    (`init_point`). Debe guardar `pedido.mp_preference_id`.
    """
    raise NotImplementedError("La integración con Mercado Pago se implementa en la próxima fase.")


def procesar_webhook(datos):
    """
    Procesa una notificación de Mercado Pago (`datos` = JSON recibido).
    Debe crear/actualizar el `Pago` y actualizar el estado del `Pedido`.
    """
    raise NotImplementedError("La integración con Mercado Pago se implementa en la próxima fase.")
