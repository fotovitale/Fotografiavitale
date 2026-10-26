"""
Configuración del proyecto Django - Fotografía Vitale.

Los valores sensibles (SECRET_KEY, credenciales de Mercado Pago) se leen
desde el archivo .env (ver .env.example).
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env", override=True)


def _env_list(nombre, default=""):
    """Lee una variable de entorno separada por comas y la devuelve como lista."""
    items = [v.strip() for v in os.getenv(nombre, default).split(",") if v.strip()]
    if nombre == "DJANGO_ALLOWED_HOSTS" and "testserver" not in items:
        items.append("testserver")
    return items


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("1", "true", "yes", "si")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        # Solo para desarrollo local. En producción es obligatorio definirla.
        SECRET_KEY = "django-insecure-solo-desarrollo-cambiar-en-produccion"
    else:
        raise ImproperlyConfigured("Falta DJANGO_SECRET_KEY en el archivo .env")

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")


# ---------------------------------------------------------------------------
# Aplicaciones
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Apps propias
    "catalogo.apps.CatalogoConfig",
    "pedidos.apps.PedidosConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "catalogo.middleware.ContadorVisitasMiddleware",
]


ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Base de datos (SQLite inicial)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# ---------------------------------------------------------------------------
# Contraseñas
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Idioma y zona horaria (Argentina)
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Mendoza"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Archivos estáticos y multimedia
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_MANIFEST_STRICT = False


MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Negocio
# ---------------------------------------------------------------------------
# Productos con stock igual o menor a este valor se marcan en rojo en el admin.
STOCK_BAJO_UMBRAL = 2
MONEDA = "ARS"


# ---------------------------------------------------------------------------
# Mercado Pago (Checkout Pro)
# ---------------------------------------------------------------------------
MERCADOPAGO_PUBLIC_KEY = os.environ.get("MERCADOPAGO_PUBLIC_KEY", "")
MERCADOPAGO_ACCESS_TOKEN = os.environ.get("MERCADOPAGO_ACCESS_TOKEN", "")
MERCADOPAGO_WEBHOOK_SECRET = os.environ.get("MERCADOPAGO_WEBHOOK_SECRET", "")


# ---------------------------------------------------------------------------
# EnvioPack (logística y envíos)
# ---------------------------------------------------------------------------
ENVIOPACK_API_KEY = os.getenv("ENVIOPACK_API_KEY", "")
ENVIOPACK_SECRET_KEY = os.getenv("ENVIOPACK_SECRET_KEY", "")


# ---------------------------------------------------------------------------
# Autenticación de Usuarios
# ---------------------------------------------------------------------------
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "perfil"
LOGOUT_REDIRECT_URL = "inicio"

