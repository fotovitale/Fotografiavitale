import requests
from django.conf import settings

def obtener_token_enviopack():
    url = "https://api.enviopack.com/auth"
    payload = {
        "api-key": settings.ENVIOPACK_API_KEY,
        "secret-key": settings.ENVIOPACK_SECRET_KEY
    }
    respuesta = requests.post(url, json=payload, timeout=5)
    
    if respuesta.status_code == 200:
        return respuesta.json().get('token')
    return None


def obtener_cotizacion_enviopack(codigo_postal, peso, alto, ancho, largo):
    token = obtener_token_enviopack()
    if not token:
        print("Error: No se pudo obtener el token de autenticación de Envíopack.")
        return None

    url = "https://api.enviopack.com/cotizar/costo"
    
    # Envíopack requiere que las dimensiones vayan en un string con formato altoXanchoXlargo
    paquetes_format = f"{alto}x{ancho}x{largo}"
    
    params = {
        "access_token": token,
        "codigo_postal": str(codigo_postal),
        "peso": float(peso),
        "paquetes": paquetes_format
    }

    try:
        # Ahora enviamos un GET con params en lugar de un POST con json
        respuesta = requests.get(url, params=params, timeout=5)
        
        if respuesta.status_code == 200:
            return respuesta.json()
        else:
            print(f"Error de Envíopack al cotizar: {respuesta.status_code} - {respuesta.text}")
            return None
            
    except requests.RequestException as e:
        print(f"Error de conexión en cotización: {e}")
        return None


