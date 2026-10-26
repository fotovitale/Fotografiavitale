"""
Integración con Mercado Pago (Checkout Pro).
Genera preferencias de pago sumando productos y costos de envío.
"""
import os
import logging
import mercadopago
from django.conf import settings

logger = logging.getLogger(__name__)


def obtener_access_token():
    """Obtiene el Access Token de Mercado Pago desde settings o desde variables de entorno."""
    token = getattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "") or os.environ.get("MERCADOPAGO_ACCESS_TOKEN", "")
    return str(token).strip()


def credenciales_configuradas():
    """True si está cargado el Access Token de Mercado Pago en settings o en el .env."""
    return bool(obtener_access_token())


def crear_preferencia_mp(items, payer=None, external_reference=None, back_urls=None, notification_url=None):
    """
    Crea una preferencia de pago en Mercado Pago a partir de una lista de ítems.
    Devuelve un diccionario con id, init_point y sandbox_init_point, o None si falla o no hay credenciales.
    """
    access_token = obtener_access_token()
    if not access_token:
        print("\n" + "=" * 60)
        print("[MERCADO PAGO ERROR] MERCADOPAGO_ACCESS_TOKEN no está configurado en settings ni en .env.")
        print("=" * 60 + "\n")
        logger.warning("MERCADOPAGO_ACCESS_TOKEN no configurado en settings ni en .env.")
        return None

    try:
        sdk = mercadopago.SDK(access_token)
        preference_data = {
            "items": items,
            "statement_descriptor": "FOTOGRAFIA VITALE",
        }
        if payer:
            preference_data["payer"] = payer
        if external_reference:
            preference_data["external_reference"] = str(external_reference)

        if back_urls:
            # Respetar el protocolo original (http o https) sin forzar HTTPS en entorno local
            preference_data["back_urls"] = dict(back_urls)
            success_url = str(back_urls.get("success") or "")
            # Mercado Pago solo permite auto_return: 'approved' si la URL de éxito es HTTPS.
            # En desarrollo local sobre HTTP plano, se omite auto_return para evitar el error HTTP 400 del SDK.
            if success_url.startswith("https://"):
                preference_data["auto_return"] = "approved"
        else:
            preference_data["auto_return"] = "approved"
            preference_data["back_urls"] = {
                "success": "https://fotografiavitale.com/pago/exitoso/",
                "failure": "https://fotografiavitale.com/carrito/",
                "pending": "https://fotografiavitale.com/pago/exitoso/",
            }

        if notification_url:
            preference_data["notification_url"] = notification_url

        respuesta = sdk.preference().create(preference_data)
        status_code = respuesta.get("status")
        res_data = respuesta.get("response", {})

        if status_code not in (200, 201):
            print("\n" + "=" * 60)
            print(f"[MERCADO PAGO ERROR] Falló la creación de preferencia (HTTP {status_code}):")
            if isinstance(res_data, dict):
                print(f" - Error: {res_data.get('error')}")
                print(f" - Mensaje: {res_data.get('message')}")
                causas = res_data.get("causes") or res_data.get("cause")
                if causas:
                    print(f" - Causas: {causas}")
            print(f"Respuesta completa del SDK: {res_data}")
            print("=" * 60 + "\n")
            logger.error(f"Error Mercado Pago API ({status_code}): {res_data}")
            return None

        init_point = res_data.get("init_point")
        # En entornos de desarrollo/DEBUG se puede utilizar sandbox si está presente
        if getattr(settings, "DEBUG", False) and res_data.get("sandbox_init_point"):
            init_point = res_data.get("sandbox_init_point")

        print(f"[MERCADO PAGO] Preferencia creada con éxito. ID: {res_data.get('id')} | Init Point: {init_point}")

        return {
            "id": res_data.get("id"),
            "init_point": init_point or res_data.get("init_point"),
            "sandbox_init_point": res_data.get("sandbox_init_point"),
            "raw": res_data,
        }
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"[MERCADO PAGO EXCEPCIÓN] Error inesperado al invocar SDK de Mercado Pago: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60 + "\n")
        logger.error(f"Error al crear preferencia en Mercado Pago: {e}", exc_info=True)
        return None


def crear_preferencia(pedido, request=None, costo_envio=0, envio_nombre=None):
    """
    Crea una preferencia de pago para `pedido` sumando el costo de envío (si existe)
    y devuelve la URL de pago (`init_point`). Guarda `pedido.mp_preference_id`.
    """
    back_urls = None
    if request:
        from django.urls import reverse
        try:
            success_base = request.build_absolute_uri(reverse("pago_exitoso"))
        except Exception:
            success_base = request.build_absolute_uri("/pago/exitoso/")
        sep = "&" if "?" in success_base else "?"
        success_url = f"{success_base}{sep}pedido_id={pedido.id}&external_reference={pedido.id}"
        try:
            cart_url = request.build_absolute_uri(reverse("carrito"))
        except Exception:
            cart_url = request.build_absolute_uri("/carrito/")
        back_urls = {
            "success": success_url,
            "failure": cart_url,
            "pending": success_url,
        }

    pref_data = pedido.to_mp_preference(
        back_urls=back_urls,
        request=request,
        external_reference=str(pedido.id)
    )

    if costo_envio and float(costo_envio) > 0:
        pref_data["items"].append({
            "id": "ENVIO",
            "title": f"Costo de Envío ({envio_nombre or 'Envíopack'})",
            "quantity": 1,
            "unit_price": float(costo_envio),
            "currency_id": getattr(settings, "MONEDA", "ARS"),
        })

    resultado = crear_preferencia_mp(
        items=pref_data["items"],
        payer=pref_data.get("payer"),
        external_reference=pref_data.get("external_reference"),
        back_urls=pref_data.get("back_urls"),
    )

    if resultado and resultado.get("id"):
        pedido.mp_preference_id = resultado["id"]
        pedido.save(update_fields=["mp_preference_id", "actualizado"])
        return resultado.get("init_point")
    return None


def procesar_webhook(datos):
    """
    Procesa una notificación de webhook de Mercado Pago (`datos` = JSON recibido).
    """
    access_token = getattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "")
    if not access_token:
        return None
    try:
        sdk = mercadopago.SDK(access_token)
        payment_id = datos.get("data", {}).get("id") or datos.get("id")
        if not payment_id:
            return None
        payment_info = sdk.payment().get(payment_id)
        return payment_info.get("response", {})
    except Exception as e:
        logger.error(f"Error procesando webhook de Mercado Pago: {e}")
        return None
