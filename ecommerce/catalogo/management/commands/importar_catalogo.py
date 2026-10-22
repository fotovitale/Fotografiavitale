"""
Comando de Django para importar los productos y promociones desde catalogo.html
a la base de datos SQLite y copiar las imágenes al directorio media/.
"""
import os
import re
import shutil
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from catalogo.models import Categoria, ImagenProducto, Producto


class Command(BaseCommand):
    help = "Importa productos y promociones desde el archivo estático catalogo.html"

    def handle(self, *args, **options):
        archivo_html = settings.BASE_DIR.parent / "catalogo.html"
        origen_fotos = settings.BASE_DIR.parent / "productos"
        destino_fotos = settings.MEDIA_ROOT / "productos"
        destino_galeria = destino_fotos / "galeria"

        if not archivo_html.exists():
            self.stderr.write(self.style.ERROR(f"No se encontró el archivo {archivo_html}"))
            return

        destino_fotos.mkdir(parents=True, exist_ok=True)
        destino_galeria.mkdir(parents=True, exist_ok=True)

        contenido = archivo_html.read_text(encoding="utf-8")

        # 1. Asegurar categorías
        cats = {
            "fotografia": Categoria.objects.get_or_create(
                slug="fotografia", defaults={"nombre": "Fotografía", "orden": 1}
            )[0],
            "tecnologia": Categoria.objects.get_or_create(
                slug="tecnologia", defaults={"nombre": "Tecnología y Computación", "orden": 2}
            )[0],
            "outdoor": Categoria.objects.get_or_create(
                slug="outdoor", defaults={"nombre": "Camping, Caza y Pesca", "orden": 3}
            )[0],
            "varios": Categoria.objects.get_or_create(
                slug="varios", defaults={"nombre": "Accesorios y Varios", "orden": 4}
            )[0],
        }

        def extraer_precio(precio_str):
            if not precio_str or "consultar" in precio_str.lower() or "xx" in precio_str.lower():
                return None
            num_limpio = re.sub(r"[^0-9]", "", precio_str)
            if not num_limpio:
                return None
            return Decimal(num_limpio)

        def copiar_foto(nombre_archivo, subcarpeta=""):
            if not nombre_archivo:
                return ""
            archivo_origen = origen_fotos / nombre_archivo
            if not archivo_origen.exists():
                return ""
            if subcarpeta:
                dest = destino_galeria / nombre_archivo
                ruta_relativa = f"productos/galeria/{nombre_archivo}"
            else:
                dest = destino_fotos / nombre_archivo
                ruta_relativa = f"productos/{nombre_archivo}"
            try:
                shutil.copy2(archivo_origen, dest)
                return ruta_relativa
            except Exception:
                return ""

        # Limpiar productos anteriores para reimportar limpiamente
        Producto.objects.all().delete()
        creados = 0

        # 2. Parsear productosTotales
        self.stdout.write("Procesando productosTotales...")
        inicio_p = contenido.find("const productosTotales = [")
        if inicio_p != -1:
            fin_p = contenido.find("];", inicio_p)
            bloque = contenido[inicio_p:fin_p]
            objetos = re.findall(r"\{([^{}]+)\}", bloque)
            for obj_str in objetos:
                nombre_m = re.search(r'nombre\s*:\s*["\'](.*?)["\']', obj_str)
                categoria_m = re.search(r'categoria\s*:\s*["\'](.*?)["\']', obj_str)
                precio_m = re.search(r'precio\s*:\s*["\'](.*?)["\']', obj_str)
                imagen_m = re.search(r'imagen\s*:\s*["\'](.*?)["\']', obj_str)
                imagenes_m = re.search(r'imagenes\s*:\s*\[(.*?)\]', obj_str)

                if not nombre_m:
                    continue

                nombre = nombre_m.group(1).strip()
                cat_slug = categoria_m.group(1).strip() if categoria_m else "varios"
                categoria = cats.get(cat_slug, cats["varios"])

                precio_raw = precio_m.group(1).strip() if precio_m else ""
                precio = extraer_precio(precio_raw)

                imagen_principal = imagen_m.group(1).strip() if imagen_m else ""
                galeria = []
                if imagenes_m:
                    galeria = [img.strip().strip("'\"") for img in imagenes_m.group(1).split(",") if img.strip()]
                    if not imagen_principal and galeria:
                        imagen_principal = galeria[0]

                ruta_guardada = copiar_foto(imagen_principal)

                base_slug = slugify(nombre)[:200]
                slug = base_slug
                idx = 2
                while Producto.objects.filter(slug=slug).exists():
                    slug = f"{base_slug[:190]}-{idx}"
                    idx += 1

                producto = Producto.objects.create(
                    nombre=nombre,
                    slug=slug,
                    categoria=categoria,
                    precio=precio,
                    stock=5 if precio else 0,
                    imagen=ruta_guardada,
                    activo=True,
                )

                for orden, foto in enumerate(galeria[1:] if imagen_principal in galeria else galeria, start=1):
                    ruta_gal = copiar_foto(foto, subcarpeta="galeria")
                    if ruta_gal:
                        ImagenProducto.objects.create(
                            producto=producto,
                            imagen=ruta_gal,
                            orden=orden,
                        )
                creados += 1

        # 3. Parsear promociones destacadas
        self.stdout.write("Procesando ofertas/promos...")
        inicio_promo = contenido.find("const promos = [")
        if inicio_promo != -1:
            fin_promo = contenido.find("];", inicio_promo)
            bloque_promos = contenido[inicio_promo:fin_promo]
            objetos_p = re.findall(r"\{([^{}]+)\}", bloque_promos)
            for p_str in objetos_p:
                titulo_m = re.search(r'titulo\s*:\s*["\'](.*?)["\']', p_str)
                badge_m = re.search(r'badge\s*:\s*["\'](.*?)["\']', p_str)
                desc_m = re.search(r'descripcion\s*:\s*["\'](.*?)["\']', p_str)
                precio_m = re.search(r'precio\s*:\s*["\'](.*?)["\']', p_str)
                imagen_m = re.search(r'imagen\s*:\s*["\'](.*?)["\']', p_str)

                if not titulo_m:
                    continue

                titulo = titulo_m.group(1).strip()
                badge = badge_m.group(1).strip() if badge_m else "OFERTA"
                desc = desc_m.group(1).strip() if desc_m else ""
                precio = extraer_precio(precio_m.group(1).strip() if precio_m else "")
                imagen_nombre = imagen_m.group(1).strip() if imagen_m else ""

                ruta_guardada = copiar_foto(imagen_nombre)

                base_slug = slugify(titulo)[:200]
                slug = base_slug
                idx = 2
                while Producto.objects.filter(slug=slug).exists():
                    slug = f"{base_slug[:190]}-{idx}"
                    idx += 1

                Producto.objects.create(
                    nombre=titulo,
                    slug=slug,
                    categoria=cats["outdoor"] if ("Pistola" in desc or "Rifle" in desc) else cats["fotografia"],
                    descripcion=desc,
                    precio=precio,
                    stock=5 if precio else 0,
                    imagen=ruta_guardada,
                    activo=True,
                    destacado=True,
                    etiqueta_promo=badge,
                )
                creados += 1

        self.stdout.write(self.style.SUCCESS(f"¡Importación completada con éxito! Se cargaron {creados} productos en total."))
