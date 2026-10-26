from decimal import Decimal
import json
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from catalogo.enviopack import obtener_cotizacion_enviopack
from pedidos.models import Pedido
from pedidos.services.mercadopago import crear_preferencia_mp, credenciales_configuradas
from .forms import RegistroUsuarioForm, LoginUsuarioForm
from .models import Categoria, Producto

NUMERO_WSP = "+5492634779824"
BG_CLASSES = ["bg-naranja", "bg-verde", "bg-rojo", "bg-azul"]


def _obtener_total_items_carrito(request):
    """Devuelve la cantidad total acumulada de artículos en el carrito."""
    carrito = request.session.get("carrito", {})
    if isinstance(carrito, dict):
        return sum(
            c if isinstance(c, int) else c.get("cantidad", 1)
            for c in carrito.values()
            if isinstance(c, (int, dict))
        )
    elif isinstance(carrito, list):
        return len(carrito)
    return 0


def _formatear_precio(precio):
    if precio is None:
        return "Consultar"
    entero = int(precio)
    return f"${entero:,}".replace(",", ".")


def _serializar_promo(producto, index=0):
    precio_str = _formatear_precio(producto.precio_final)
    precio_normal_str = _formatear_precio(producto.precio) if producto.precio else None
    precio_oferta_str = _formatear_precio(producto.precio_oferta) if producto.en_oferta else None
    fotos = producto.fotos
    imagen_url = fotos[0] if fotos else ""
    wsp_text = f"Hola! Me interesa la promo de {producto.nombre}"
    if producto.precio_final:
        wsp_text += f" por {precio_str}"

    return {
        "id": producto.id,
        "badge": producto.etiqueta_promo or "OFERTA DESTACADA",
        "titulo": producto.nombre,
        "descripcion": producto.descripcion or producto.nombre,
        "precio": precio_str,
        "precio_normal": precio_normal_str,
        "precio_oferta": precio_oferta_str,
        "en_oferta": producto.en_oferta,
        "imagen": imagen_url,
        "imagenes": fotos,
        "bgClass": BG_CLASSES[index % len(BG_CLASSES)],
        "wspText": wsp_text,
        "stock": producto.stock,
        "hay_stock": producto.hay_stock,
        "se_puede_comprar": producto.se_puede_comprar,
        "requiere_fotos": producto.requiere_fotos,
    }


def _serializar_producto(producto):
    precio_str = _formatear_precio(producto.precio_final)
    precio_normal_str = _formatear_precio(producto.precio) if producto.precio else None
    precio_oferta_str = _formatear_precio(producto.precio_oferta) if producto.en_oferta else None
    
    # Lista de todas las fotos (usando la propiedad optimizada del modelo)
    fotos = producto.fotos
    imagen_principal = fotos[0] if fotos else ""

    return {
        "id": producto.id,
        "nombre": producto.nombre,
        "categoria": producto.categoria.slug if producto.categoria else "varios",
        "categoria_nombre": producto.categoria.nombre if producto.categoria else "",
        "precio": precio_str,
        "precio_normal": precio_normal_str,
        "precio_oferta": precio_oferta_str,
        "en_oferta": producto.en_oferta,
        "precio_num": float(producto.precio_final) if producto.precio_final else None,
        "stock": producto.stock,
        "hay_stock": producto.hay_stock,
        "se_puede_comprar": producto.se_puede_comprar,
        "requiere_fotos": producto.requiere_fotos,
        "imagen": imagen_principal,
        "imagenes": fotos,
        "descripcion": producto.descripcion or "",
        "destacado": producto.destacado,
    }


def index(request):
    """Página de inicio (landing / index)."""
    # Si Mercado Pago redirige a la raíz tras un pago aprobado (fallback de URLs anteriores)
    collection_status = request.GET.get("collection_status") or request.GET.get("status")
    if collection_status == "approved" and (request.GET.get("external_reference") or request.GET.get("preference_id")):
        from django.urls import reverse
        query_string = request.META.get("QUERY_STRING", "")
        return redirect(f"{reverse('pago_exitoso')}?{query_string}")

    promos_qs = (
        Producto.objects.filter(activo=True, destacado=True)
        .select_related("categoria")
        .prefetch_related("imagenes")
    )
    if not promos_qs.exists():
        # Fallback a los últimos 6 productos si no hay ninguno marcado como destacado
        promos_qs = (
            Producto.objects.filter(activo=True)
            .select_related("categoria")
            .prefetch_related("imagenes")[:6]
        )

    promos_data = [_serializar_promo(p, i) for i, p in enumerate(promos_qs)]

    context = {
        "promos": promos_data,
        "promos_json": json.dumps(promos_data, ensure_ascii=False),
        "numero_wsp": NUMERO_WSP,
        "total_items_carrito": _obtener_total_items_carrito(request),
    }
    return render(request, "index.html", context)


def catalogo(request):
    """Página completa del catálogo interactivo."""
    categorias = Categoria.objects.filter(activa=True).order_by("orden", "nombre")
    
    productos_qs = (
        Producto.objects.filter(activo=True)
        .select_related("categoria")
        .prefetch_related("imagenes")
        .order_by("-destacado", "-id")
    )

    promos_qs = (
        Producto.objects.filter(activo=True, destacado=True)
        .select_related("categoria")
        .prefetch_related("imagenes")
        .order_by("-id")
    )
    if not promos_qs.exists():
        promos_qs = productos_qs.filter(precio__isnull=False)[:6]

    productos_data = [_serializar_producto(p) for p in productos_qs]
    promos_data = [_serializar_promo(p, i) for i, p in enumerate(promos_qs)]

    # Interceptar código postal para cotización de Envíopack (GET o POST)
    codigo_postal = request.POST.get("codigo_postal") or request.GET.get("codigo_postal")
    opciones_envio = None

    # TODO: El modelo Producto aún no tiene campos de peso y dimensiones (peso, alto, ancho, largo).
    # Temporalmente se usan valores por defecto: peso=1, alto=10, ancho=10, largo=10.
    peso_envio = 1.0
    alto_envio = 10.0
    ancho_envio = 10.0
    largo_envio = 10.0

    if codigo_postal:
        codigo_postal = str(codigo_postal).strip()
        opciones_envio = obtener_cotizacion_enviopack(
            codigo_postal=codigo_postal,
            peso=peso_envio,
            alto=alto_envio,
            ancho=ancho_envio,
            largo=largo_envio,
        )

    context = {
        "categorias": categorias,
        "productos": productos_qs,
        "productos_json": json.dumps(productos_data, ensure_ascii=False),
        "promos": promos_data,
        "promos_json": json.dumps(promos_data, ensure_ascii=False),
        "numero_wsp": NUMERO_WSP,
        "total_productos": len(productos_data),
        "codigo_postal": codigo_postal,
        "opciones_envio": opciones_envio,
        "total_items_carrito": _obtener_total_items_carrito(request),
    }
    return render(request, "catalogo.html", context)


def carrito(request):
    """
    Vista del carrito de compras y checkout.
    Integra cotización de envíos con Envíopack y generación de preferencia de Mercado Pago.
    """
    # 1. Procesar modificaciones al carrito (agregar, remover, eliminar, vaciar)
    agregar_id = request.POST.get("agregar") or request.GET.get("agregar")
    remover_id = request.POST.get("remover") or request.GET.get("remover")
    eliminar_id = request.POST.get("eliminar") or request.GET.get("eliminar")
    vaciar = request.POST.get("vaciar") or request.GET.get("vaciar")

    carrito_sesion = request.session.get("carrito", {})
    if not isinstance(carrito_sesion, dict):
        carrito_sesion = {}

    modificado = False
    prod_agregado = None
    if agregar_id and str(agregar_id).isdigit():
        p = Producto.objects.filter(pk=int(agregar_id), activo=True).first()
        if p and p.se_puede_comprar:
            prod_agregado = p
            str_id = str(p.id)
            cant_actual = carrito_sesion.get(str_id, 0)
            if isinstance(cant_actual, dict):
                cant_actual = cant_actual.get("cantidad", 0)
            
            # Permitir cantidad personalizada (ej. desde el modal de Quick View)
            cant_param = request.POST.get("cantidad") or request.GET.get("cantidad")
            try:
                cantidad_a_sumar = max(1, int(cant_param)) if cant_param else 1
            except (ValueError, TypeError):
                cantidad_a_sumar = 1

            nueva_cant = min(p.stock, cant_actual + cantidad_a_sumar)
            if nueva_cant > cant_actual:
                carrito_sesion[str_id] = nueva_cant
                modificado = True

    if remover_id and str(remover_id) in carrito_sesion:
        str_id = str(remover_id)
        if carrito_sesion[str_id] > 1:
            carrito_sesion[str_id] -= 1
        else:
            del carrito_sesion[str_id]
        modificado = True

    if eliminar_id and str(eliminar_id) in carrito_sesion:
        del carrito_sesion[str(eliminar_id)]
        modificado = True

    if vaciar:
        carrito_sesion = {}
        modificado = True

    if modificado:
        request.session["carrito"] = carrito_sesion
        request.session.modified = True

    # 2. Reconstruir lista detallada de productos y subtotal
    items_carrito = []
    subtotal_productos = Decimal("0")
    cantidad_total_articulos = 0

    if carrito_sesion:
        ids = [int(k) for k in carrito_sesion.keys() if str(k).isdigit()]
        productos_map = {p.id: p for p in Producto.objects.filter(id__in=ids, activo=True)}

        for str_id, cant in carrito_sesion.items():
            if not str(str_id).isdigit():
                continue
            p_id = int(str_id)
            prod = productos_map.get(p_id)
            if prod and prod.precio_final:
                cantidad = int(cant) if isinstance(cant, int) else int(cant.get("cantidad", 1))
                subtotal = prod.precio_final * Decimal(cantidad)
                subtotal_productos += subtotal
                cantidad_total_articulos += cantidad
                items_carrito.append({
                    "producto": prod,
                    "cantidad": cantidad,
                    "precio_unitario": prod.precio_final,
                    "subtotal": subtotal,
                })

    # 3. Interceptar código postal y cotizar Envíopack
    codigo_postal = request.POST.get("codigo_postal") or request.GET.get("codigo_postal")
    opciones_envio = None

    # TODO: El modelo Producto aún no tiene campos de peso y dimensiones (peso, alto, ancho, largo).
    # Temporalmente se usan valores por defecto (ej: peso=1, alto=10, ancho=10, largo=10).
    peso_default = 1.0
    alto_default = 10.0
    ancho_default = 10.0
    largo_default = 10.0

    # Calcular peso y dimensiones totales en base a los productos en el carrito (sesión)
    cantidad_total = 1
    if isinstance(carrito_sesion, dict) and carrito_sesion:
        cantidad_total = sum(
            c if isinstance(c, int) else c.get("cantidad", 1)
            for c in carrito_sesion.values()
            if isinstance(c, (int, dict))
        ) or 1
    elif isinstance(carrito_sesion, list) and carrito_sesion:
        cantidad_total = len(carrito_sesion) or 1

    peso_total = peso_default * cantidad_total
    alto_total = alto_default * cantidad_total
    ancho_total = ancho_default
    largo_total = largo_default

    if codigo_postal:
        codigo_postal = str(codigo_postal).strip()
        opciones_envio = obtener_cotizacion_enviopack(
            codigo_postal=codigo_postal,
            peso=peso_total,
            alto=alto_total,
            ancho=ancho_total,
            largo=largo_total,
        )
        if isinstance(opciones_envio, list):
            for opc in opciones_envio:
                if isinstance(opc, dict):
                    val = opc.get("valor") or opc.get("costo") or opc.get("precio")
                    if val is not None:
                        try:
                            num = float(val)
                            opc["valor"] = num
                            opc["costo"] = num
                        except (ValueError, TypeError):
                            pass

    # 4. Determinar costo de envío seleccionado
    costo_envio_param = request.POST.get("costo_envio") or request.GET.get("costo_envio")
    envio_nombre = request.POST.get("envio_nombre") or request.GET.get("envio_nombre") or ""

    costo_envio = Decimal("0")
    if costo_envio_param is not None and str(costo_envio_param).strip() != "":
        try:
            costo_envio = Decimal(str(costo_envio_param).replace(",", "."))
            # Persistir en sesión para recordar el envío seleccionado
            request.session["envio_seleccionado"] = {
                "codigo_postal": str(codigo_postal or "").strip(),
                "costo": str(costo_envio),
                "nombre": envio_nombre,
            }
            request.session.modified = True
        except (ValueError, TypeError, ArithmeticError):
            costo_envio = Decimal("0")
    elif request.session.get("envio_seleccionado") and request.session["envio_seleccionado"].get("codigo_postal") == str(codigo_postal or "").strip():
        try:
            saved_envio = request.session["envio_seleccionado"]
            costo_envio = Decimal(str(saved_envio.get("costo", "0")))
            if not envio_nombre:
                envio_nombre = saved_envio.get("nombre", "")
        except (ValueError, TypeError, ArithmeticError):
            pass
    elif opciones_envio and isinstance(opciones_envio, list) and len(opciones_envio) > 0:
        primera_opc = opciones_envio[0]
        val = primera_opc.get("valor") or primera_opc.get("costo") or primera_opc.get("precio")
        if val is not None:
            try:
                costo_envio = Decimal(str(val))
                correo_info = primera_opc.get("correo")
                envio_nombre = (
                    correo_info.get("nombre") if isinstance(correo_info, dict) else correo_info
                ) or "Envíopack"
            except (ValueError, TypeError, ArithmeticError):
                pass

    total_con_envio = subtotal_productos + costo_envio

    # 5. Generar preferencia de Mercado Pago (sumando productos + envío)
    mp_items = []
    for item in items_carrito:
        mp_items.append({
            "id": str(item["producto"].sku or item["producto"].id),
            "title": item["producto"].nombre[:256],
            "quantity": int(item["cantidad"]),
            "unit_price": float(item["precio_unitario"]),
            "currency_id": getattr(settings, "MONEDA", "ARS"),
        })

    # Si hay costo de envío seleccionado, se suma como un ítem a Mercado Pago
    if costo_envio > Decimal("0"):
        mp_items.append({
            "id": "ENVIO",
            "title": f"Costo de Envío ({envio_nombre or 'Envíopack'})",
            "quantity": 1,
            "unit_price": float(costo_envio),
            "currency_id": getattr(settings, "MONEDA", "ARS"),
        })

    mp_preference_url = None
    if mp_items:
        from django.urls import reverse
        try:
            success_url = request.build_absolute_uri(reverse("pago_exitoso"))
        except Exception:
            success_url = request.build_absolute_uri("/pago/exitoso/")
        try:
            cart_url = request.build_absolute_uri(reverse("carrito"))
        except Exception:
            cart_url = request.build_absolute_uri("/carrito/")
        back_urls = {
            "success": success_url,
            "failure": cart_url,
            "pending": success_url,
        }
        resultado_mp = crear_preferencia_mp(
            items=mp_items,
            back_urls=back_urls,
        )
        if resultado_mp:
            mp_preference_url = resultado_mp.get("init_point")
        else:
            print("[CARRITO VIEW] Aviso: mp_preference_url no se pudo generar (crear_preferencia_mp retornó None).")

    # 6. Preparar texto predeterminado para WhatsApp
    lineas_wsp = ["Hola! Quiero coordinar el siguiente pedido en Fotografía Vitale:"]
    for it in items_carrito:
        lineas_wsp.append(f"• {it['cantidad']}x {it['producto'].nombre} - ${int(it['subtotal']):,}".replace(",", "."))
    if codigo_postal:
        lineas_wsp.append(f"Envío a CP {codigo_postal}")
    if costo_envio > Decimal("0"):
        lineas_wsp.append(f"Costo de envío: ${int(costo_envio):,}".replace(",", ".") + f" ({envio_nombre})")
    lineas_wsp.append(f"Total: ${int(total_con_envio):,}".replace(",", "."))
    mensaje_wsp = "\n".join(lineas_wsp)

    context = {
        "items_carrito": items_carrito,
        "subtotal_productos": subtotal_productos,
        "costo_envio": costo_envio,
        "envio_nombre": envio_nombre,
        "total_con_envio": total_con_envio,
        "codigo_postal": codigo_postal,
        "opciones_envio": opciones_envio,
        "peso_total": peso_total,
        "alto_total": alto_total,
        "ancho_total": ancho_total,
        "largo_total": largo_total,
        "mp_preference_url": mp_preference_url,
        "credenciales_mp": credenciales_configuradas(),
        "numero_wsp": NUMERO_WSP,
        "mensaje_wsp": mensaje_wsp,
        "total_items_carrito": cantidad_total_articulos,
        "costo_envio_param": costo_envio_param,
    }

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
        return JsonResponse({
            "status": "ok",
            "costo_envio": float(costo_envio),
            "envio_nombre": envio_nombre,
            "total_con_envio": float(total_con_envio),
            "subtotal_productos": float(subtotal_productos),
            "total_items_carrito": cantidad_total_articulos,
            "nombre_producto": prod_agregado.nombre if prod_agregado else "",
            "mp_preference_url": mp_preference_url,
            "credenciales_mp": credenciales_configuradas(),
            "mensaje_wsp": mensaje_wsp,
            "numero_wsp": NUMERO_WSP,
        })

    return render(request, "carrito.html", context)


def checkout(request):
    """
    Procesa el formulario de checkout:
    1. Valida datos de contacto y datos de envío (la dirección es obligatoria solo si es a domicilio).
    2. Guarda el Pedido en estado 'pendiente' junto con los ItemPedido en la base de datos.
    3. Genera la preferencia de Mercado Pago con external_reference = str(pedido.id).
    4. Devuelve la URL de Mercado Pago (init_point) para redirigir al cliente.
    """
    if request.method != "POST":
        return redirect("carrito")

    carrito_sesion = request.session.get("carrito", {})
    if not isinstance(carrito_sesion, dict) or not carrito_sesion:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
            return JsonResponse({"status": "error", "message": "Tu carrito actualmente está vacío."}, status=400)
        return redirect("carrito")

    # Extraer y validar items del carrito
    ids = [int(k) for k in carrito_sesion.keys() if str(k).isdigit()]
    productos_map = {p.id: p for p in Producto.objects.filter(id__in=ids, activo=True)}

    items_carrito = []
    subtotal_productos = Decimal("0")
    for str_id, cant in carrito_sesion.items():
        if not str(str_id).isdigit():
            continue
        p_id = int(str_id)
        prod = productos_map.get(p_id)
        if prod and prod.precio_final:
            cantidad = int(cant) if isinstance(cant, int) else int(cant.get("cantidad", 1))
            subtotal = prod.precio_final * Decimal(cantidad)
            subtotal_productos += subtotal
            items_carrito.append({
                "producto": prod,
                "cantidad": cantidad,
                "precio_unitario": prod.precio_final,
                "subtotal": subtotal,
            })

    if not items_carrito:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
            return JsonResponse({"status": "error", "message": "No se encontraron productos disponibles para comprar."}, status=400)
        return redirect("carrito")

    # Datos del comprador (autocompletar con usuario autenticado si vienen vacíos)
    nombre = request.POST.get("nombre", "").strip()
    apellido = request.POST.get("apellido", "").strip()
    email = request.POST.get("email", "").strip()
    telefono = request.POST.get("telefono", "").strip()

    if request.user.is_authenticated:
        if not nombre:
            nombre = request.user.first_name or request.user.username
        if not apellido:
            apellido = request.user.last_name
        if not email:
            email = request.user.email

    # Datos postales y de entrega
    calle = request.POST.get("calle", "").strip()
    numero = request.POST.get("numero", "").strip()
    piso_depto = request.POST.get("piso_depto", "").strip()
    localidad = request.POST.get("localidad", "").strip()
    codigo_postal = request.POST.get("codigo_postal", "").strip()

    # Datos del transporte
    envio_nombre = request.POST.get("envio_nombre", "").strip() or "Envíopack"
    envio_modalidad = request.POST.get("envio_modalidad", "").strip() or "D"
    costo_envio_param = request.POST.get("costo_envio", "0")

    try:
        costo_envio = Decimal(str(costo_envio_param).replace(",", "."))
    except (ValueError, TypeError, ArithmeticError):
        costo_envio = Decimal("0")

    # Validaciones
    errores = []
    if not nombre:
        errores.append("El nombre es obligatorio.")
    if not apellido:
        errores.append("El apellido es obligatorio.")
    if not email:
        errores.append("El email es obligatorio.")
    if not telefono:
        errores.append("El teléfono es obligatorio.")

    # La dirección solo es obligatoria si la modalidad es a domicilio ('D' o 'N')
    es_a_domicilio = envio_modalidad.upper() in ("D", "N", "DOMICILIO") or "domicilio" in envio_modalidad.lower()
    if es_a_domicilio:
        if not calle:
            errores.append("La calle es obligatoria para envíos a domicilio.")
        if not numero:
            errores.append("El número es obligatorio para envíos a domicilio.")
        if not localidad:
            errores.append("La localidad es obligatoria para envíos a domicilio.")

    if errores:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
            return JsonResponse({"status": "error", "message": " ".join(errores), "errores": errores}, status=400)
        return redirect("carrito")

    total_con_envio = subtotal_productos + costo_envio

    from pedidos.models import Pedido, ItemPedido
    from pedidos.services.mercadopago import crear_preferencia

    # Detectar si algún producto requiere imágenes personalizadas
    requiere_fotos_pedido = any(
        bool(it["producto"] and getattr(it["producto"], "requiere_fotos", False))
        for it in items_carrito
    )
    usuario_pedido = request.user if request.user.is_authenticated else None

    # 1. Guardar el Pedido en la base de datos en estado PENDIENTE
    pedido = Pedido.objects.create(
        usuario=usuario_pedido,
        requiere_fotos=requiere_fotos_pedido,
        nombre=nombre,
        apellido=apellido,
        email=email,
        telefono=telefono,
        calle=calle,
        numero=numero,
        piso_depto=piso_depto,
        localidad=localidad,
        codigo_postal=codigo_postal,
        envio_nombre=envio_nombre,
        envio_modalidad=envio_modalidad,
        costo_envio=costo_envio,
        subtotal=subtotal_productos,
        total=total_con_envio,
        estado=Pedido.Estado.PENDIENTE,
    )

    # 2. Guardar los ítems del pedido
    for it in items_carrito:
        ItemPedido.objects.create(
            pedido=pedido,
            producto=it["producto"],
            nombre_producto=it["producto"].nombre,
            precio_unitario=it["precio_unitario"],
            cantidad=it["cantidad"],
        )
    pedido.verificar_requiere_fotos(guardar=True)

    # 3. Generar la preferencia de Mercado Pago pasándole el ID del pedido como external_reference
    init_point = crear_preferencia(
        pedido=pedido,
        request=request,
        costo_envio=costo_envio,
        envio_nombre=envio_nombre,
    )

    if not init_point:
        error_msg = "No se pudo generar la preferencia de Mercado Pago. Revisá las credenciales o la consola del servidor."
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
            return JsonResponse({"status": "error", "message": error_msg, "pedido_id": pedido.id}, status=500)
        return redirect("carrito")

    # Guardar ID del pedido en la sesión para máxima trazabilidad al retornar de Mercado Pago
    request.session["ultimo_pedido_id"] = pedido.id
    # Vaciar el carrito de compras una vez creado el pedido
    request.session["carrito"] = {}
    request.session.modified = True

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("format") == "json":
        return JsonResponse({
            "status": "ok",
            "init_point": init_point,
            "pedido_id": pedido.id,
            "codigo": str(pedido.codigo),
        })

    return redirect(init_point)


def pago_exitoso(request):
    """
    Vista de retorno de éxito (Success URL) de Mercado Pago tras un pago aprobado.
    - Extrae exhaustivamente los parámetros de request.GET (payment_id, status, collection_status, external_reference, etc.).
    - Busca el pedido correspondiente con múltiples capas de resolución (external_reference, pedido_id, preference_id, sesión, etc.).
    - Imprime en consola todos los datos para facilitar debugging.
    - Cambia el estado a 'Pagado' (Pedido.Estado.PAGADO).
    - Descuenta la cantidad de cada producto del stock en la base de datos de manera atómica e idempotente.
    - Registra el objeto Pago (si viene payment_id / collection_id).
    - Vacía el carrito de compras de la sesión.
    - Renderiza la plantilla de confirmación de pago (pago_exitoso.html).
    """
    from django.db import transaction
    from pedidos.models import Pedido, Pago

    # 1. Extracción exhaustiva de parámetros de request.GET
    payment_id = (request.GET.get("payment_id") or request.GET.get("collection_id") or "").strip()
    status = (request.GET.get("status") or "").strip().lower()
    collection_status = (request.GET.get("collection_status") or "").strip().lower()
    external_reference = (request.GET.get("external_reference") or "").strip()
    preference_id = (request.GET.get("preference_id") or "").strip()
    pedido_id = (request.GET.get("pedido_id") or "").strip()

    print("\n" + "=" * 65)
    print("[DEBUG PAGO EXITOSO] Petición recibida en URL de retorno de Mercado Pago:")
    print(f"  > request.GET dict completo: {dict(request.GET)}")
    print(f"  > payment_id: '{payment_id}'")
    print(f"  > status: '{status}'")
    print(f"  > collection_status: '{collection_status}'")
    print(f"  > external_reference: '{external_reference}'")
    print(f"  > preference_id: '{preference_id}'")
    print(f"  > pedido_id en URL: '{pedido_id}'")
    print(f"  > ultimo_pedido_id en sesión: '{request.session.get('ultimo_pedido_id')}'")

    # 2. Resolución y búsqueda del Pedido
    pedido = None

    # Capa 1: Búsqueda por external_reference (numérico o UUID)
    if external_reference and external_reference.lower() not in ("null", "none", "undefined", ""):
        if external_reference.isdigit():
            pedido = Pedido.objects.filter(id=int(external_reference)).first()
            if pedido:
                print(f"  [+] Pedido encontrado por external_reference (ID numérico): #{pedido.id}")
        if not pedido:
            try:
                pedido = Pedido.objects.filter(codigo=external_reference).first()
                if pedido:
                    print(f"  [+] Pedido encontrado por external_reference (UUID): #{pedido.id}")
            except Exception:
                pass

    # Capa 2: Búsqueda por pedido_id explícito en GET
    if not pedido and pedido_id and pedido_id.isdigit():
        pedido = Pedido.objects.filter(id=int(pedido_id)).first()
        if pedido:
            print(f"  [+] Pedido encontrado por pedido_id en GET: #{pedido.id}")

    # Capa 3: Búsqueda por preference_id
    if not pedido and preference_id and preference_id.lower() not in ("null", "none", "undefined", ""):
        pedido = Pedido.objects.filter(mp_preference_id=preference_id).first()
        if pedido:
            print(f"  [+] Pedido encontrado por mp_preference_id: #{pedido.id}")

    # Capa 4: Búsqueda por ID guardado en sesión
    if not pedido:
        session_pedido_id = request.session.get("ultimo_pedido_id")
        if session_pedido_id and str(session_pedido_id).isdigit():
            pedido = Pedido.objects.filter(id=int(session_pedido_id)).first()
            if pedido:
                print(f"  [+] Pedido encontrado por sesión (ultimo_pedido_id={session_pedido_id}): #{pedido.id}")

    # Capa 5: Búsqueda por registro previo de Pago
    if not pedido and payment_id and payment_id.isdigit():
        pago_existente = Pago.objects.filter(mp_payment_id=payment_id).select_related("pedido").first()
        if pago_existente:
            pedido = pago_existente.pedido
            print(f"  [+] Pedido encontrado por Pago previo (payment_id={payment_id}): #{pedido.id}")

    # Capa 6: Fallback de seguridad al último pedido pendiente
    if not pedido:
        pedido = Pedido.objects.filter(estado=Pedido.Estado.PENDIENTE).order_by("-creado").first()
        if pedido:
            print(f"  [+] Pedido resuelto por fallback (último pedido pendiente en base de datos): #{pedido.id}")

    print(f"  > Pedido resultante: {pedido} (ID: {getattr(pedido, 'id', None)}, Estado actual: {getattr(pedido, 'estado', None)})")

    # 3. Evaluación de estado de pago aprobado
    es_rechazado = status in ("rejected", "cancelled", "refunded", "in_mediation", "charged_back") or collection_status in ("rejected", "cancelled", "refunded")
    es_aprobado = not es_rechazado and (
        status in ("approved", "accredited", "authorized")
        or collection_status in ("approved", "accredited", "authorized")
        or (not status and not collection_status)
        or status in ("null", "none", "")
        or collection_status in ("null", "none", "")
    )
    print(f"  > Evaluación condición pago: es_aprobado={es_aprobado} (es_rechazado={es_rechazado})")

    # 4. Actualización a PAGADO y deducción de stock
    if pedido and es_aprobado:
        with transaction.atomic():
            p_actualizado = Pedido.objects.select_for_update().filter(pk=pedido.pk).first()
            if p_actualizado:
                if p_actualizado.estado != Pedido.Estado.PAGADO:
                    print(f"  [*] Descontando stock de productos para Pedido #{p_actualizado.id}:")
                    for item in p_actualizado.items.select_related("producto"):
                        if item.producto_id:
                            prod = Producto.objects.select_for_update().get(pk=item.producto_id)
                            stock_anterior = prod.stock
                            prod.stock = max(0, prod.stock - item.cantidad)
                            prod.save(update_fields=["stock", "actualizado"])
                            print(f"      - '{prod.nombre}' (ID {prod.id}): stock anterior={stock_anterior}, cant={item.cantidad}, nuevo stock={prod.stock}")
                    p_actualizado.estado = Pedido.Estado.PAGADO
                    p_actualizado.save(update_fields=["estado", "actualizado"])
                    pedido = p_actualizado
                    print(f"  [*] ¡Pedido #{p_actualizado.id} actualizado exitosamente a estado PAGADO!")
                else:
                    print(f"  [*] Pedido #{p_actualizado.id} ya se encontraba en estado PAGADO. No se duplica el descuento de stock.")
    else:
        if not pedido:
            print("  [!] ADVERTENCIA: No se encontró ningún Pedido para procesar.")
        if not es_aprobado:
            print(f"  [!] ADVERTENCIA: El pago no fue considerado aprobado (status='{status}', collection_status='{collection_status}').")

    # 5. Registro de Pago en la base de datos
    if pedido and payment_id and payment_id.lower() not in ("null", "none", ""):
        try:
            Pago.objects.get_or_create(
                mp_payment_id=str(payment_id),
                defaults={
                    "pedido": pedido,
                    "estado_mp": Pago.EstadoMP.APPROVED if es_aprobado else Pago.EstadoMP.PENDING,
                    "monto": pedido.total,
                    "estado_detalle": status or collection_status or "approved",
                }
            )
            print(f"  [*] Objeto Pago #{payment_id} registrado en BD.")
        except Exception as e:
            print(f"  [!] Aviso al registrar Pago: {e}")

    # 6. Vaciar el carrito de la sesión
    request.session["carrito"] = {}
    request.session.modified = True
    print("  [*] Carrito de compras vaciado de la sesión.")
    print("=" * 65 + "\n")

    if pedido:
        pedido.verificar_requiere_fotos(guardar=True)
        if request.user.is_authenticated and not pedido.usuario:
            pedido.usuario = request.user
            pedido.save(update_fields=["usuario", "actualizado"])

    context = {
        "pedido": pedido,
        "items": pedido.items.select_related("producto").all() if pedido else [],
        "payment_id": payment_id,
        "status": status or collection_status,
        "numero_wsp": NUMERO_WSP,
        "total_items_carrito": 0,
    }
    return render(request, "pago_exitoso.html", context)


# ---------------------------------------------------------------------------
# Autenticación y Perfil de Usuario
# ---------------------------------------------------------------------------

def registro_view(request):
    """Vista de registro para nuevos clientes de la tienda."""
    if request.user.is_authenticated:
        return redirect("perfil")

    if request.method == "POST":
        form = RegistroUsuarioForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            # Asociar compras previas realizadas como invitado con este email
            Pedido.objects.filter(usuario__isnull=True, email__iexact=user.email).update(usuario=user)
            messages.success(request, f"¡Bienvenido a Fotografía Vitale, {user.first_name or user.username}! Tu cuenta fue creada con éxito.")
            next_url = request.GET.get("next") or request.POST.get("next") or "perfil"
            return redirect(next_url)
    else:
        form = RegistroUsuarioForm()

    return render(request, "registro.html", {
        "form": form,
        "total_items_carrito": _obtener_total_items_carrito(request),
        "numero_wsp": NUMERO_WSP,
    })


def login_view(request):
    """Vista de inicio de sesión."""
    if request.user.is_authenticated:
        return redirect("perfil")

    if request.method == "POST":
        form = LoginUsuarioForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            # Asociar compras previas realizadas como invitado con este email
            Pedido.objects.filter(usuario__isnull=True, email__iexact=user.email).update(usuario=user)
            messages.success(request, f"¡Hola de nuevo, {user.first_name or user.username}!")
            next_url = request.GET.get("next") or request.POST.get("next") or "perfil"
            return redirect(next_url)
    else:
        form = LoginUsuarioForm(request)

    return render(request, "login.html", {
        "form": form,
        "total_items_carrito": _obtener_total_items_carrito(request),
        "numero_wsp": NUMERO_WSP,
    })


def logout_view(request):
    """Cierre de sesión de usuarios."""
    logout(request)
    messages.info(request, "Has cerrado sesión correctamente. ¡Esperamos verte pronto!")
    return redirect("inicio")


@login_required(login_url="login")
def perfil_view(request):
    """Panel de perfil del usuario con su historial completo de pedidos."""
    # Asociar automáticamente pedidos previos como invitado con este email
    Pedido.objects.filter(usuario__isnull=True, email__iexact=request.user.email).update(usuario=request.user)

    pedidos = (
        Pedido.objects.filter(usuario=request.user)
        .prefetch_related("items__producto", "pagos")
        .order_by("-creado")
    )

    # Actualizar estado de requiere_fotos en cada pedido
    for p in pedidos:
        p.verificar_requiere_fotos(guardar=True)

    return render(request, "perfil.html", {
        "pedidos": pedidos,
        "total_pedidos": pedidos.count(),
        "total_items_carrito": _obtener_total_items_carrito(request),
        "numero_wsp": NUMERO_WSP,
    })


# ---------------------------------------------------------------------------
# Technical SEO, Crawlers y Archivos de Rastreo
# ---------------------------------------------------------------------------

def robots_txt(request):
    """Genera dinámicamente el archivo robots.txt para motores de búsqueda."""
    sitemap_url = request.build_absolute_uri(reverse("sitemap_xml"))
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /carrito/",
        "Disallow: /checkout/",
        "Disallow: /pago/",
        "Disallow: /perfil/",
        "Disallow: /login/",
        "Disallow: /registro/",
        "",
        f"Sitemap: {sitemap_url}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


def sitemap_xml(request):
    """Genera dinámicamente el mapa del sitio (sitemap.xml) con URLs canónicas."""
    from django.utils import timezone
    
    base_url = f"{request.scheme}://{request.get_host()}"
    hoy = timezone.now().strftime("%Y-%m-%d")
    
    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        '  <url>',
        f'    <loc>{base_url}{reverse("inicio")}</loc>',
        f'    <lastmod>{hoy}</lastmod>',
        '    <changefreq>daily</changefreq>',
        '    <priority>1.0</priority>',
        '  </url>',
        '  <url>',
        f'    <loc>{base_url}{reverse("catalogo")}</loc>',
        f'    <lastmod>{hoy}</lastmod>',
        '    <changefreq>daily</changefreq>',
        '    <priority>0.9</priority>',
        '  </url>',
    ]
    
    # Categorías activas
    for cat in Categoria.objects.filter(activa=True):
        xml_parts.extend([
            '  <url>',
            f'    <loc>{base_url}{reverse("catalogo")}?cat={cat.slug}</loc>',
            f'    <lastmod>{hoy}</lastmod>',
            '    <changefreq>weekly</changefreq>',
            '    <priority>0.8</priority>',
            '  </url>',
        ])
        
    # Productos activos
    for prod in Producto.objects.filter(activo=True):
        xml_parts.extend([
            '  <url>',
            f'    <loc>{base_url}{reverse("catalogo")}#prod-{prod.id}</loc>',
            f'    <lastmod>{hoy}</lastmod>',
            '    <changefreq>weekly</changefreq>',
            '    <priority>0.7</priority>',
            '  </url>',
        ])
        
    xml_parts.append('</urlset>')
    return HttpResponse("\n".join(xml_parts), content_type="application/xml; charset=utf-8")


def llms_txt(request):
    """
    Archivo estandarizado llms.txt para consumo por modelos de lenguaje e inteligencias artificiales.
    Proporciona un resumen estructurado del negocio, productos y canales de atención.
    """
    base_url = f"{request.scheme}://{request.get_host()}"
    content = f"""# Fotografía Vitale

> Multiespacio fotográfico profesional, tecnología, camping, pesca, caza y cuchillería en San Martín, Mendoza, Argentina.

## Información General
- **Nombre**: Fotografía Vitale
- **Ubicación**: San Martín, Mendoza, Argentina
- **WhatsApp**: +54 9 263 477-9824
- **Email**: fotografiavitale.fv@gmail.com
- **Sitio Web**: {base_url}

## Rubros y Especialidades
1. **Fotografía & Laboratorio Profesional**:
   - Revelado analógico y digital en alta definición.
   - Copias Polaroid personalizadas, fotolibros y cuadros.
   - Gigantografías, lonas e impresiones para fotógrafos y eventos.
   - Personalización: Los clientes envían sus imágenes por WhatsApp indicando el número de pedido.

2. **Tecnología & Computación**:
   - Periféricos gamer (mouse, teclados, auriculares), cables, memorias, almacenamiento y accesorios.

3. **Outdoor, Caza, Pesca & Camping**:
   - Cañas de pescar, reels, linternas tácticas, cuchillería artesanal, termos, carpas y artículos de aventura.

## Modalidades de Compra y Envío
- **Tienda Online**: Catálogo interactivo con carrito integrado y cotización de envíos en tiempo real ({base_url}/catalogo/).
- **Pagos**: Mercado Pago Checkout Pro (tarjetas de crédito, débito, dinero en cuenta) o efectivo en el local.
- **Logística**: Envíos a todo el país mediante Envíopack (a domicilio o sucursal) o retiro sin costo en el local comercial.

## URLs Principales
- Inicio: {base_url}/
- Catálogo: {base_url}/catalogo/
- Carrito de compras: {base_url}/carrito/
"""
    return HttpResponse(content.strip(), content_type="text/markdown; charset=utf-8")


def custom_404_view(request, exception=None):
    """Vista personalizada para páginas no encontradas (Error 404)."""
    return render(request, "404.html", {
        "numero_wsp": NUMERO_WSP,
        "total_items_carrito": _obtener_total_items_carrito(request),
    }, status=404)

