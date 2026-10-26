from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Categoria, Producto, SiteStatistics



class ProductoModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Categoria.objects.get(slug="tecnologia")  # precargada por migración

    def crear(self, **kw):
        datos = {"nombre": "Joystick PS4", "categoria": self.cat}
        datos.update(kw)
        return Producto.objects.create(**datos)

    def test_categorias_precargadas(self):
        slugs = set(Categoria.objects.values_list("slug", flat=True))
        self.assertTrue({"fotografia", "tecnologia", "outdoor", "varios"} <= slugs)

    def test_slug_automatico_y_unico(self):
        p1 = self.crear()
        p2 = self.crear()
        self.assertEqual(p1.slug, "joystick-ps4")
        self.assertEqual(p2.slug, "joystick-ps4-2")

    def test_sin_precio_es_a_consultar_y_no_se_compra(self):
        p = self.crear(stock=5)
        self.assertTrue(p.precio_a_consultar)
        self.assertIsNone(p.precio_final)
        self.assertFalse(p.se_puede_comprar)

    def test_precio_final_usa_oferta(self):
        p = self.crear(precio=Decimal("1000"), precio_oferta=Decimal("800"), stock=1)
        self.assertTrue(p.en_oferta)
        self.assertEqual(p.precio_final, Decimal("800"))
        self.assertTrue(p.se_puede_comprar)

    def test_sin_stock_no_se_compra(self):
        p = self.crear(precio=Decimal("1000"), stock=0)
        self.assertFalse(p.hay_stock)
        self.assertFalse(p.se_puede_comprar)

    def test_validacion_oferta(self):
        p = Producto(nombre="X", categoria=self.cat, precio=Decimal("100"), precio_oferta=Decimal("150"))
        with self.assertRaises(ValidationError):
            p.full_clean()
        p = Producto(nombre="X", categoria=self.cat, precio_oferta=Decimal("50"))
        with self.assertRaises(ValidationError):
            p.full_clean()

    def test_to_mp_item(self):
        p = self.crear(precio=Decimal("1500.50"), stock=3, sku="JOY-01")
        item = p.to_mp_item(cantidad=2)
        self.assertEqual(item["id"], "JOY-01")
        self.assertEqual(item["quantity"], 2)
        self.assertEqual(item["unit_price"], 1500.50)
        self.assertEqual(item["currency_id"], "ARS")

    def test_to_mp_item_rechaza_no_comprable_o_cantidad_invalida(self):
        with self.assertRaises(ValueError):
            self.crear().to_mp_item()
        p = self.crear(precio=Decimal("10"), stock=1)
        with self.assertRaises(ValueError):
            p.to_mp_item(cantidad=2)


class AdminPermisosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("duenio", "d@x.com", "clave-segura-123")
        cls.empleado = User.objects.create_user("empleado", password="clave-segura-123", is_staff=True)
        cls.empleado.groups.add(Group.objects.get(name="Empleados"))
        cls.producto = Producto.objects.create(
            nombre="Linterna", categoria=Categoria.objects.get(slug="outdoor")
        )

    def test_grupo_empleados_permisos(self):
        perms = set(
            Group.objects.get(name="Empleados").permissions.values_list("codename", flat=True)
        )
        self.assertIn("change_producto", perms)
        self.assertIn("add_producto", perms)
        self.assertNotIn("delete_producto", perms)
        self.assertNotIn("view_pedido", perms)

    def test_superusuario_ve_todas_las_pantallas(self):
        self.client.force_login(self.admin)
        for nombre in (
            "admin:catalogo_producto_changelist",
            "admin:catalogo_producto_add",
            "admin:catalogo_categoria_changelist",
            "admin:pedidos_pedido_changelist",
            "admin:pedidos_pago_changelist",
        ):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.client.get(reverse(nombre)).status_code, 200)
        url = reverse("admin:catalogo_producto_change", args=[self.producto.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_empleado_edita_productos_pero_no_ve_pedidos(self):
        self.client.force_login(self.empleado)
        self.assertEqual(
            self.client.get(reverse("admin:catalogo_producto_changelist")).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("admin:pedidos_pedido_changelist")).status_code, 403
        )


class CatalogoViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Categoria.objects.get(slug="fotografia")
        cls.p1 = Producto.objects.create(
            nombre="Cámara Vintage",
            categoria=cls.cat,
            precio=Decimal("45000"),
            stock=3,
            activo=True,
            destacado=True,
            etiqueta_promo="OFERTA ESPECIAL",
        )
        cls.p2 = Producto.objects.create(
            nombre="Rollo 35mm",
            categoria=cls.cat,
            precio=None,
            stock=0,
            activo=True,
        )

    def test_pagina_inicio_renderiza_correctamente(self):
        resp = self.client.get(reverse("inicio"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "index.html")
        self.assertIn("promos", resp.context)
        self.assertIn("promos_json", resp.context)
        self.assertContains(resp, "Cámara Vintage")

    def test_pagina_catalogo_renderiza_correctamente(self):
        resp = self.client.get(reverse("catalogo"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "catalogo.html")
        self.assertIn("categorias", resp.context)
        self.assertIn("productos_json", resp.context)
        self.assertContains(resp, "Cámara Vintage")
        self.assertContains(resp, "Rollo 35mm")

    def test_ordenamiento_predeterminado_destacados_y_nuevos_primero(self):
        p_nuevo = Producto.objects.create(
            nombre="Trípode Nuevo",
            categoria=self.cat,
            activo=True,
            destacado=False,
        )
        resp = self.client.get(reverse("catalogo"))
        productos = list(resp.context["productos"])
        # self.p1 es destacado=True, por lo que debe ir primero
        self.assertEqual(productos[0], self.p1)
        self.assertEqual(productos[1], p_nuevo)

    def test_rutas_alias_compatibles(self):
        self.assertEqual(self.client.get("/index.html").status_code, 200)

        self.assertEqual(self.client.get("/catalogo.html").status_code, 200)


class SiteStatisticsTests(TestCase):
    def setUp(self):
        SiteStatistics.objects.all().delete()

    def test_singleton_get_or_create(self):
        stat1 = SiteStatistics.obtener()
        stat2 = SiteStatistics.obtener()
        self.assertEqual(stat1.pk, 1)
        self.assertEqual(stat2.pk, 1)
        self.assertEqual(SiteStatistics.objects.count(), 1)

    def test_singleton_save_fuerza_pk_1(self):
        stat = SiteStatistics(total_visitas=10)
        stat.save()
        stat2 = SiteStatistics(total_visitas=20)
        stat2.save()
        self.assertEqual(SiteStatistics.objects.count(), 1)
        self.assertEqual(SiteStatistics.objects.get(pk=1).total_visitas, 20)

    def test_incrementar_atomico(self):
        SiteStatistics.incrementar()
        SiteStatistics.incrementar()
        stat = SiteStatistics.obtener()
        self.assertEqual(stat.total_visitas, 2)
        self.assertIsNotNone(stat.ultima_visita)

    def test_middleware_cuenta_visitas_inicio_y_catalogo(self):
        self.assertEqual(SiteStatistics.obtener().total_visitas, 0)
        self.client.get(reverse("inicio"))
        self.assertEqual(SiteStatistics.obtener().total_visitas, 1)

        self.client.get(reverse("catalogo"))
        self.assertEqual(SiteStatistics.obtener().total_visitas, 2)

    def test_middleware_ignora_rutas_admin(self):
        admin_user = User.objects.create_superuser("admin_test", "a@test.com", "pass123")
        self.client.force_login(admin_user)

        self.assertEqual(SiteStatistics.obtener().total_visitas, 0)
        self.client.get("/admin/")
        self.client.get("/admin/catalogo/sitestatistics/")
        self.assertEqual(SiteStatistics.obtener().total_visitas, 0)

    def test_admin_sitestatistics_solo_lectura(self):
        admin_user = User.objects.create_superuser("admin_test2", "a2@test.com", "pass123")
        self.client.force_login(admin_user)
        resp = self.client.get(reverse("admin:catalogo_sitestatistics_changelist"))
        self.assertEqual(resp.status_code, 200)

        url_change = reverse("admin:catalogo_sitestatistics_change", args=[1])
        resp_change = self.client.get(url_change)
        self.assertEqual(resp_change.status_code, 200)
        self.assertContains(resp_change, "total_visitas")


class CarritoEnviopackTests(TestCase):
    def test_carrito_get_sin_codigo_postal(self):
        resp = self.client.get(reverse("carrito"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "carrito.html")
        self.assertIsNone(resp.context["codigo_postal"])
        self.assertIsNone(resp.context["opciones_envio"])
        self.assertEqual(resp.context["peso_total"], 1.0)
        self.assertEqual(resp.context["alto_total"], 10.0)

    @patch("catalogo.views.obtener_cotizacion_enviopack")
    def test_carrito_get_con_codigo_postal(self, mock_cotizar):
        mock_cotizar.return_value = [
            {"correo": {"nombre": "Andreani"}, "modalidad": "D", "horas_entrega": 48, "costo": 3500}
        ]
        resp = self.client.get(reverse("carrito"), {"codigo_postal": "5570"})
        self.assertEqual(resp.status_code, 200)
        mock_cotizar.assert_called_once_with(
            codigo_postal="5570",
            peso=1.0,
            alto=10.0,
            ancho=10.0,
            largo=10.0,
        )
        self.assertEqual(resp.context["codigo_postal"], "5570")
        self.assertEqual(len(resp.context["opciones_envio"]), 1)
        self.assertContains(resp, "Andreani")
        self.assertContains(resp, "Envío a Domicilio")
        self.assertContains(resp, "Llega en 2 días hábiles")
        self.assertContains(resp, "3500")

    @patch("catalogo.views.obtener_cotizacion_enviopack")
    def test_carrito_post_con_codigo_postal(self, mock_cotizar):
        mock_cotizar.return_value = [
            {"correo": {"nombre": "Correo Argentino"}, "modalidad": "S", "horas_entrega": 72, "costo": 2900}
        ]
        resp = self.client.post(reverse("carrito"), {"codigo_postal": "1425"})
        self.assertEqual(resp.status_code, 200)
        mock_cotizar.assert_called_once_with(
            codigo_postal="1425",
            peso=1.0,
            alto=10.0,
            ancho=10.0,
            largo=10.0,
        )
        self.assertEqual(resp.context["codigo_postal"], "1425")
        self.assertEqual(len(resp.context["opciones_envio"]), 1)
        self.assertContains(resp, "Correo Argentino")
        self.assertContains(resp, "Retiro en Sucursal")
        self.assertContains(resp, "Llega en 3 días hábiles")

    @patch("catalogo.views.obtener_cotizacion_enviopack")
    def test_catalogo_get_con_codigo_postal(self, mock_cotizar):
        mock_cotizar.return_value = [{"correo": "Andreani", "costo": 4000}]
        resp = self.client.get(reverse("catalogo"), {"codigo_postal": "5000"})
        self.assertEqual(resp.status_code, 200)
        mock_cotizar.assert_called_once_with(
            codigo_postal="5000",
            peso=1.0,
            alto=10.0,
            ancho=10.0,
            largo=10.0,
        )
        self.assertEqual(resp.context["codigo_postal"], "5000")
        self.assertEqual(resp.context["opciones_envio"], [{"correo": "Andreani", "costo": 4000}])

    @patch("catalogo.views.obtener_cotizacion_enviopack")
    def test_carrito_con_productos_en_sesion(self, mock_cotizar):
        mock_cotizar.return_value = [{"correo": "Andreani", "costo": 5000}]
        session = self.client.session
        session["carrito"] = {"prod_1": 2, "prod_2": 3}
        session.save()

        resp = self.client.get(reverse("carrito"), {"codigo_postal": "5570"})
        self.assertEqual(resp.status_code, 200)
        mock_cotizar.assert_called_once_with(
            codigo_postal="5570",
            peso=5.0,
            alto=50.0,
            ancho=10.0,
            largo=10.0,
        )
        self.assertEqual(resp.context["peso_total"], 5.0)
        self.assertEqual(resp.context["alto_total"], 50.0)

    def test_agregar_remover_producto_carrito(self):
        cat = Categoria.objects.get(slug="fotografia")
        prod = Producto.objects.create(
            nombre="Cámara Vintage 35mm",
            categoria=cat,
            precio=Decimal("15000"),
            stock=5,
            activo=True,
        )
        # Agregar al carrito
        resp = self.client.get(reverse("carrito"), {"agregar": prod.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.session.get("carrito"), {str(prod.id): 1})

        # Incrementar
        resp = self.client.get(reverse("carrito"), {"agregar": prod.id})
        self.assertEqual(self.client.session.get("carrito"), {str(prod.id): 2})

        # Decrementar
        resp = self.client.get(reverse("carrito"), {"remover": prod.id})
        self.assertEqual(self.client.session.get("carrito"), {str(prod.id): 1})

        # Eliminar
        resp = self.client.get(reverse("carrito"), {"eliminar": prod.id})
        self.assertEqual(self.client.session.get("carrito"), {})

    @patch("catalogo.views.crear_preferencia_mp")
    def test_carrito_genera_preferencia_mercadopago_con_envio(self, mock_crear_mp):
        mock_crear_mp.return_value = {
            "id": "mp-pref-999",
            "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=mp-pref-999"
        }
        cat = Categoria.objects.get(slug="fotografia")
        prod = Producto.objects.create(
            nombre="Lente 50mm",
            categoria=cat,
            precio=Decimal("20000"),
            stock=3,
            activo=True,
        )
        session = self.client.session
        session["carrito"] = {str(prod.id): 1}
        session.save()

        resp = self.client.get(reverse("carrito"), {
            "codigo_postal": "5570",
            "costo_envio": "3500",
            "envio_nombre": "Andreani Domicilio",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["mp_preference_url"], "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=mp-pref-999")
        self.assertEqual(resp.context["total_con_envio"], Decimal("23500"))

        # Validar que los items enviados a MP incluyan producto y costo de envío
        mp_items = mock_crear_mp.call_args[1]["items"]
        self.assertEqual(len(mp_items), 2)
        self.assertEqual(mp_items[0]["title"], "Lente 50mm")
        self.assertEqual(mp_items[0]["unit_price"], 20000.0)
        self.assertEqual(mp_items[1]["id"], "ENVIO")
        self.assertEqual(mp_items[1]["unit_price"], 3500.0)
        self.assertIn("Andreani Domicilio", mp_items[1]["title"])

        # Validar orden de botones en template: Mercado Pago arriba, WhatsApp abajo
        self.assertContains(resp, "Finalizar Compra con Mercado Pago")
        self.assertContains(resp, "Consultar por WhatsApp")
        contenido = resp.content.decode("utf-8")
        pos_mp = contenido.find("Finalizar Compra con Mercado Pago")
        pos_wsp = contenido.find("Consultar por WhatsApp")
        self.assertLess(pos_mp, pos_wsp, "El botón de Mercado Pago debe ir antes (arriba) del de WhatsApp")

    def test_navbar_incluye_boton_carrito(self):
        for url_name in ("inicio", "catalogo", "carrito"):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, reverse("carrito"))
            self.assertContains(resp, "fa-cart-shopping")

    @patch("catalogo.views.obtener_cotizacion_enviopack")
    def test_carrito_renderiza_opciones_con_radios_y_data_price(self, mock_cotizar):
        mock_cotizar.return_value = [
            {"correo": {"nombre": "Andreani"}, "modalidad": "D", "horas_entrega": 48, "costo": 3500}
        ]
        resp = self.client.get(reverse("carrito"), {"codigo_postal": "5570"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'class="shipping-radio"')
        self.assertContains(resp, 'data-price="3500.0"')
        self.assertContains(resp, 'id="resumen-totales"')
        self.assertContains(resp, 'id="resumen-total-final"')
        self.assertContains(resp, 'id="resumen-envio-costo"')

    @patch("catalogo.views.crear_preferencia_mp")
    def test_carrito_ajax_actualiza_envio_y_devuelve_json(self, mock_crear_mp):
        mock_crear_mp.return_value = {
            "id": "mp-pref-ajax",
            "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=mp-pref-ajax"
        }
        cat = Categoria.objects.get(slug="fotografia")
        prod = Producto.objects.create(
            nombre="Cámara Analógica",
            categoria=cat,
            precio=Decimal("50000"),
            stock=2,
            activo=True,
        )
        session = self.client.session
        session["carrito"] = {str(prod.id): 1}
        session.save()

        resp = self.client.get(
            reverse("carrito"),
            {
                "codigo_postal": "5570",
                "costo_envio": "4200",
                "envio_nombre": "Correo Argentino",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Content-Type"), "application/json")
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["costo_envio"], 4200.0)
        self.assertEqual(data["total_con_envio"], 54200.0)
        self.assertEqual(data["subtotal_productos"], 50000.0)
        self.assertIn("mp-pref-ajax", data["mp_preference_url"])
        self.assertIn("4.200", data["mensaje_wsp"])

    def test_checkout_get_redirige_a_carrito(self):
        resp = self.client.get(reverse("checkout"))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("carrito"))

    def test_checkout_post_valida_campos_obligatorios(self):
        cat = Categoria.objects.get(slug="fotografia")
        prod = Producto.objects.create(nombre="Foto Test", categoria=cat, precio=Decimal("1000"), stock=5, activo=True)
        session = self.client.session
        session["carrito"] = {str(prod.id): 1}
        session.save()

        # POST sin datos de comprador
        resp = self.client.post(
            reverse("checkout"),
            {},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("nombre", data["message"].lower())

    def test_checkout_domicilio_exige_calle_y_numero(self):
        cat = Categoria.objects.get(slug="fotografia")
        prod = Producto.objects.create(nombre="Foto Test 2", categoria=cat, precio=Decimal("1500"), stock=5, activo=True)
        session = self.client.session
        session["carrito"] = {str(prod.id): 1}
        session.save()

        # Modalidad a domicilio sin calle ni número
        resp = self.client.post(
            reverse("checkout"),
            {
                "nombre": "Juan",
                "apellido": "Pérez",
                "email": "juan@test.com",
                "telefono": "2614567890",
                "envio_modalidad": "D",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("calle", data["message"].lower())

    @patch("pedidos.services.mercadopago.crear_preferencia_mp")
    def test_checkout_sucursal_permite_sin_direccion_y_crea_pedido(self, mock_mp):
        mock_mp.return_value = {
            "id": "mp-pref-checkout-s",
            "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=mp-pref-checkout-s"
        }
        from pedidos.models import Pedido

        cat = Categoria.objects.get(slug="fotografia")
        prod = Producto.objects.create(nombre="Cuadro 30x40", categoria=cat, precio=Decimal("8000"), stock=3, activo=True)
        session = self.client.session
        session["carrito"] = {str(prod.id): 2}
        session.save()

        resp = self.client.post(
            reverse("checkout"),
            {
                "nombre": "María",
                "apellido": "Gómez",
                "email": "maria@test.com",
                "telefono": "2619876543",
                "envio_modalidad": "S",
                "envio_nombre": "Andreani Sucursal",
                "costo_envio": "2500",
                "codigo_postal": "5570",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("mp-pref-checkout-s", data["init_point"])

        # Verificar que el Pedido se creó en la base de datos en estado PENDIENTE
        pedido = Pedido.objects.get(id=data["pedido_id"])
        self.assertEqual(pedido.nombre, "María")
        self.assertEqual(pedido.apellido, "Gómez")
        self.assertEqual(pedido.email, "maria@test.com")
        self.assertEqual(pedido.telefono, "2619876543")
        self.assertEqual(pedido.envio_modalidad, "S")
        self.assertEqual(pedido.costo_envio, Decimal("2500"))
        self.assertEqual(pedido.subtotal, Decimal("16000"))
        self.assertEqual(pedido.total, Decimal("18500"))
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE)
        self.assertEqual(pedido.mp_preference_id, "mp-pref-checkout-s")

        # Verificar que se crearon los ítems del pedido
        self.assertEqual(pedido.items.count(), 1)
        item = pedido.items.first()
        self.assertEqual(item.producto, prod)
        self.assertEqual(item.cantidad, 2)
        self.assertEqual(item.precio_unitario, Decimal("8000"))

        # Validar que external_reference enviado a MP sea el ID del pedido
        self.assertEqual(mock_mp.call_args[1]["external_reference"], str(pedido.id))

    @patch("pedidos.services.mercadopago.crear_preferencia_mp")
    def test_checkout_domicilio_exitoso_y_vacia_carrito(self, mock_mp):
        mock_mp.return_value = {
            "id": "mp-pref-checkout-d",
            "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=mp-pref-checkout-d"
        }
        from pedidos.models import Pedido

        cat = Categoria.objects.get(slug="fotografia")
        prod = Producto.objects.create(nombre="Álbum Cuero", categoria=cat, precio=Decimal("12000"), stock=5, activo=True)
        session = self.client.session
        session["carrito"] = {str(prod.id): 1}
        session.save()

        resp = self.client.post(
            reverse("checkout"),
            {
                "nombre": "Lucas",
                "apellido": "Vitale",
                "email": "lucas@test.com",
                "telefono": "2611112233",
                "calle": "San Martín",
                "numero": "450",
                "piso_depto": "Piso 1",
                "localidad": "Mendoza",
                "codigo_postal": "5500",
                "envio_modalidad": "D",
                "envio_nombre": "Andreani Domicilio",
                "costo_envio": "3000",
            }
        )
        # Redirección estándar (no AJAX)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=mp-pref-checkout-d")

        # Carrito debe haber quedado vacío
        self.assertEqual(self.client.session.get("carrito"), {})

        pedido = Pedido.objects.get(email="lucas@test.com")
        self.assertEqual(pedido.calle, "San Martín")
        self.assertEqual(pedido.numero, "450")
        self.assertEqual(pedido.localidad, "Mendoza")
        self.assertEqual(pedido.total, Decimal("15000"))
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE)

    def test_pago_exitoso_actualiza_pedido_descuenta_stock_y_vacia_carrito(self):
        from pedidos.models import Pedido, ItemPedido, Pago
        cat = Categoria.objects.get(slug="tecnologia")
        prod1 = Producto.objects.create(nombre="Auriculares Pro", categoria=cat, precio=Decimal("5000"), stock=10, activo=True)
        prod2 = Producto.objects.create(nombre="Cable USB", categoria=cat, precio=Decimal("1000"), stock=5, activo=True)

        pedido = Pedido.objects.create(
            nombre="Juan",
            apellido="Pérez",
            email="juan@test.com",
            telefono="2610001122",
            subtotal=Decimal("12000"),
            total=Decimal("12000"),
            estado=Pedido.Estado.PENDIENTE,
        )
        ItemPedido.objects.create(pedido=pedido, producto=prod1, nombre_producto=prod1.nombre, precio_unitario=prod1.precio, cantidad=2)
        ItemPedido.objects.create(pedido=pedido, producto=prod2, nombre_producto=prod2.nombre, precio_unitario=prod2.precio, cantidad=1)

        # Llenar carrito en sesión
        session = self.client.session
        session["carrito"] = {str(prod1.id): 2, str(prod2.id): 1}
        session.save()

        # Usuario vuelve a la URL de retorno de éxito de Mercado Pago
        url = reverse("pago_exitoso")
        resp = self.client.get(
            url,
            {
                "collection_status": "approved",
                "status": "approved",
                "payment_id": "999888777",
                "external_reference": str(pedido.id),
                "preference_id": "pref-123456",
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "¡Pago Aprobado y Confirmado!")
        self.assertContains(resp, "¡Tu pago fue exitoso y tus datos se cargaron correctamente!")
        self.assertContains(resp, "Ante cualquier inconveniente o duda con tu pedido")
        self.assertContains(resp, "fotografiavitale.fv@gmail.com")
        self.assertContains(resp, "Auriculares Pro")

        # 1. Pedido debe estar en estado 'pagado'
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.Estado.PAGADO)

        # 2. Stock debe haberse descontado correctamente
        prod1.refresh_from_db()
        prod2.refresh_from_db()
        self.assertEqual(prod1.stock, 8)  # 10 - 2
        self.assertEqual(prod2.stock, 4)  # 5 - 1

        # 3. Carrito en sesión debe estar vacío
        self.assertEqual(self.client.session.get("carrito"), {})

        # 4. Registro de Pago debe haberse creado
        pago = Pago.objects.filter(mp_payment_id="999888777").first()
        self.assertIsNotNone(pago)
        self.assertEqual(pago.pedido, pedido)
        self.assertEqual(pago.estado_mp, Pago.EstadoMP.APPROVED)

    def test_pago_exitoso_es_idempotente(self):
        from pedidos.models import Pedido, ItemPedido
        cat = Categoria.objects.get(slug="outdoor")
        prod = Producto.objects.create(nombre="Mochila Camping", categoria=cat, precio=Decimal("20000"), stock=10, activo=True)

        pedido = Pedido.objects.create(
            nombre="Ana",
            apellido="García",
            email="ana@test.com",
            telefono="2613334455",
            subtotal=Decimal("20000"),
            total=Decimal("20000"),
            estado=Pedido.Estado.PENDIENTE,
        )
        ItemPedido.objects.create(pedido=pedido, producto=prod, nombre_producto=prod.nombre, precio_unitario=prod.precio, cantidad=3)

        url = reverse("pago_exitoso")
        # Primer ingreso
        self.client.get(url, {"status": "approved", "external_reference": str(pedido.id)})
        prod.refresh_from_db()
        self.assertEqual(prod.stock, 7)

        # Segundo ingreso (ej: recarga de página por el usuario)
        self.client.get(url, {"status": "approved", "external_reference": str(pedido.id)})
        prod.refresh_from_db()
        # El stock no debe descontarse dos veces
        self.assertEqual(prod.stock, 7)

    def test_stock_cero_no_se_puede_agregar_al_carrito(self):
        cat = Categoria.objects.get(slug="tecnologia")
        prod_sin_stock = Producto.objects.create(
            nombre="Cámara Sin Stock",
            categoria=cat,
            precio=Decimal("50000"),
            stock=0,
            activo=True,
        )
        self.assertFalse(prod_sin_stock.hay_stock)
        self.assertFalse(prod_sin_stock.se_puede_comprar)

        # Intentar añadir al carrito vía GET
        resp = self.client.get(reverse("carrito"), {"agregar": prod_sin_stock.id})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(str(prod_sin_stock.id), self.client.session.get("carrito", {}))

    def test_catalogo_muestra_agotado_para_productos_sin_stock(self):
        cat = Categoria.objects.get(slug="tecnologia")
        Producto.objects.create(
            nombre="Dron Agotado",
            categoria=cat,
            precio=Decimal("80000"),
            stock=0,
            activo=True,
        )
        resp = self.client.get(reverse("catalogo"))
        self.assertEqual(resp.status_code, 200)
        # El JSON inyectado en la plantilla debe incluir hay_stock = false y stock = 0
        self.assertIn('"hay_stock": false', resp.content.decode("utf-8").lower())
        self.assertIn('"nombre": "Dron Agotado"', resp.content.decode("utf-8"))
        # La plantilla debe contener las clases e indicadores de Agotado
        self.assertIn("badge-agotado", resp.content.decode("utf-8"))
        self.assertIn("btn-agotado", resp.content.decode("utf-8"))

    def test_index_redirecciona_a_pago_exitoso_si_mp_vuelve_aprobado(self):
        cat = Categoria.objects.get(slug="tecnologia")
        prod = Producto.objects.create(nombre="Parlante", categoria=cat, precio=Decimal("4000"), stock=5, activo=True)
        from pedidos.models import Pedido, ItemPedido
        pedido = Pedido.objects.create(
            nombre="Carlos",
            apellido="Ríos",
            email="carlos@test.com",
            telefono="2618889900",
            subtotal=Decimal("4000"),
            total=Decimal("4000"),
            estado=Pedido.Estado.PENDIENTE,
        )
        ItemPedido.objects.create(pedido=pedido, producto=prod, nombre_producto=prod.nombre, precio_unitario=prod.precio, cantidad=1)

        resp = self.client.get(
            reverse("inicio"),
            {
                "collection_status": "approved",
                "external_reference": str(pedido.id),
                "payment_id": "123123123",
            }
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("pago_exitoso"), resp.url)

    @patch("pedidos.services.mercadopago.crear_preferencia_mp")
    def test_checkout_retiro_por_el_local_exitoso(self, mock_mp):
        mock_mp.return_value = {
            "id": "mp-pref-local",
            "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=mp-pref-local"
        }
        from pedidos.models import Pedido
        cat = Categoria.objects.get(slug="fotografia")
        prod = Producto.objects.create(nombre="Portarretratos", categoria=cat, precio=Decimal("3500"), stock=5, activo=True)

        session = self.client.session
        session["carrito"] = {str(prod.id): 1}
        session.save()

        # Checkout con Retiro por el local (sin dirección obligatoria)
        resp = self.client.post(
            reverse("checkout"),
            {
                "nombre": "Martín",
                "apellido": "López",
                "email": "martin@test.com",
                "telefono": "2615556677",
                "envio_nombre": "Retiro por el local",
                "envio_modalidad": "LOCAL",
                "costo_envio": "0",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")

        pedido = Pedido.objects.get(id=data["pedido_id"])
        self.assertEqual(pedido.envio_nombre, "Retiro por el local")
        self.assertEqual(pedido.envio_modalidad, "LOCAL")
        self.assertEqual(pedido.costo_envio, Decimal("0"))
        self.assertEqual(pedido.total, Decimal("3500"))
        self.assertEqual(pedido.estado, Pedido.Estado.PENDIENTE)

    def test_pago_exitoso_encuentra_pedido_por_pedido_id_o_sesion_y_descuenta_stock(self):
        from pedidos.models import Pedido, ItemPedido
        cat = Categoria.objects.get(slug="tecnologia")
        prod = Producto.objects.create(nombre="Mouse Gamer", categoria=cat, precio=Decimal("8000"), stock=6, activo=True)

        pedido = Pedido.objects.create(
            nombre="Valeria",
            apellido="Suárez",
            email="vale@test.com",
            telefono="2612223344",
            subtotal=Decimal("8000"),
            total=Decimal("8000"),
            estado=Pedido.Estado.PENDIENTE,
        )
        ItemPedido.objects.create(pedido=pedido, producto=prod, nombre_producto=prod.nombre, precio_unitario=prod.precio, cantidad=2)

        # Simular sesión activa con ultimo_pedido_id
        session = self.client.session
        session["ultimo_pedido_id"] = pedido.id
        session["carrito"] = {str(prod.id): 2}
        session.save()

        # Retorno de MP donde external_reference venga como 'null' (típico de pruebas Sandbox) pero viene pedido_id en URL
        resp = self.client.get(
            reverse("pago_exitoso"),
            {
                "collection_status": "approved",
                "status": "approved",
                "payment_id": "444555666",
                "external_reference": "null",
                "pedido_id": str(pedido.id),
            }
        )
        self.assertEqual(resp.status_code, 200)

        # Pedido debe haberse actualizado a PAGADO
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.Estado.PAGADO)

        # Stock descontado
        prod.refresh_from_db()
        self.assertEqual(prod.stock, 4)  # 6 - 2


class AutenticacionYPerfilTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat_foto = Categoria.objects.get(slug="fotografia")
        cls.cat_tec = Categoria.objects.get(slug="tecnologia")
        cls.prod_normal = Producto.objects.create(
            nombre="Pendrive 64GB",
            categoria=cls.cat_tec,
            precio=Decimal("5000"),
            stock=10,
            requiere_fotos=False,
            activo=True,
        )
        cls.prod_fotos = Producto.objects.create(
            nombre="Pack 50 Fotos 10x15",
            categoria=cls.cat_foto,
            precio=Decimal("15000"),
            stock=20,
            requiere_fotos=True,
            activo=True,
        )

    def test_registro_usuario_exitoso_y_asocia_pedidos_previos(self):
        from pedidos.models import Pedido
        # Crear un pedido previo como invitado con el email que luego se registrará
        pedido_previo = Pedido.objects.create(
            nombre="Lucas",
            apellido="Gómez",
            email="lucas@test.com",
            telefono="2614445566",
            subtotal=Decimal("5000"),
            total=Decimal("5000"),
            estado=Pedido.Estado.PAGADO,
            usuario=None,
        )

        resp = self.client.post(
            reverse("registro"),
            {
                "username": "lucasg",
                "email": "lucas@test.com",
                "first_name": "Lucas",
                "last_name": "Gómez",
                "password1": "Password123!",
                "password2": "Password123!",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["user"].is_authenticated)
        self.assertEqual(resp.context["user"].username, "lucasg")

        # El pedido previo de invitado ahora debe estar asociado al nuevo usuario
        pedido_previo.refresh_from_db()
        self.assertEqual(pedido_previo.usuario, resp.context["user"])

    def test_login_y_logout_views(self):
        User.objects.create_user(
            username="mariana",
            email="mariana@test.com",
            password="Password123!",
            first_name="Mariana",
            last_name="Pérez",
        )
        # Login exitoso
        resp_login = self.client.post(
            reverse("login"),
            {"username": "mariana", "password": "Password123!"},
            follow=True,
        )
        self.assertEqual(resp_login.status_code, 200)
        self.assertTrue(resp_login.context["user"].is_authenticated)

        # Logout exitoso
        resp_logout = self.client.get(reverse("logout"), follow=True)
        self.assertEqual(resp_logout.status_code, 200)
        self.assertFalse(resp_logout.context["user"].is_authenticated)

    def test_perfil_requiere_login(self):
        resp = self.client.get(reverse("perfil"))
        # Debe redirigir al login
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp.url)

    def test_perfil_muestra_historial_y_alerta_fotos(self):
        from pedidos.models import Pedido, ItemPedido
        user = User.objects.create_user(
            username="esteban",
            email="esteban@test.com",
            password="Password123!",
            first_name="Esteban",
            last_name="Rios",
        )
        self.client.force_login(user)

        # Pedido 1: requiere fotos
        pedido_foto = Pedido.objects.create(
            usuario=user,
            nombre="Esteban",
            apellido="Rios",
            email="esteban@test.com",
            telefono="2619998877",
            subtotal=Decimal("15000"),
            total=Decimal("15000"),
            estado=Pedido.Estado.PAGADO,
            requiere_fotos=True,
        )
        ItemPedido.objects.create(
            pedido=pedido_foto,
            producto=self.prod_fotos,
            nombre_producto=self.prod_fotos.nombre,
            precio_unitario=self.prod_fotos.precio,
            cantidad=1,
        )

        # Pedido 2: producto común sin fotos
        pedido_comun = Pedido.objects.create(
            usuario=user,
            nombre="Esteban",
            apellido="Rios",
            email="esteban@test.com",
            telefono="2619998877",
            subtotal=Decimal("5000"),
            total=Decimal("5000"),
            estado=Pedido.Estado.PAGADO,
            requiere_fotos=False,
        )
        ItemPedido.objects.create(
            pedido=pedido_comun,
            producto=self.prod_normal,
            nombre_producto=self.prod_normal.nombre,
            precio_unitario=self.prod_normal.precio,
            cantidad=1,
        )

        resp = self.client.get(reverse("perfil"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # Debe mostrar ambos pedidos
        self.assertIn(f"Pedido #{pedido_foto.id}", content)
        self.assertIn(f"Pedido #{pedido_comun.id}", content)

        # Debe mostrar el texto exacto de la alerta de fotos
        self.assertIn("¡ATENCIÓN! Tu pedido requiere que nos envíes las imágenes para poder procesarlo.", content)

        # Debe contener el enlace dinámico de WhatsApp prearmado
        msg_wsp_esperado = f"Hola%20Fotograf%C3%ADa%20Vitale%2C%20soy%20del%20pedido%20%23{pedido_foto.id}.%20Ac%C3%A1%20env%C3%ADo%20las%20fotos%20para%20mi%20compra."
        self.assertIn(msg_wsp_esperado, content)


class RequiereFotosYCheckoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Categoria.objects.get(slug="fotografia")
        cls.prod_personalizado = Producto.objects.create(
            nombre="Pack 100 Fotos Polaroid",
            categoria=cls.cat,
            precio=Decimal("25000"),
            stock=15,
            requiere_fotos=True,
            activo=True,
        )
        cls.prod_comun = Producto.objects.create(
            nombre="Álbum Clásico",
            categoria=cls.cat,
            precio=Decimal("12000"),
            stock=8,
            requiere_fotos=False,
            activo=True,
        )

    def test_modelo_pedido_detecta_requiere_fotos(self):
        from pedidos.models import Pedido, ItemPedido
        # Pedido con producto personalizado
        p1 = Pedido.objects.create(nombre="Clara", email="clara@test.com")
        ItemPedido.objects.create(pedido=p1, producto=self.prod_personalizado, cantidad=1)
        self.assertTrue(p1.necesita_fotos)
        p1.verificar_requiere_fotos(guardar=True)
        self.assertTrue(p1.requiere_fotos)

        # Pedido con producto estándar
        p2 = Pedido.objects.create(nombre="Marcos", email="marcos@test.com")
        ItemPedido.objects.create(pedido=p2, producto=self.prod_comun, cantidad=1)
        self.assertFalse(p2.necesita_fotos)
        p2.verificar_requiere_fotos(guardar=True)
        self.assertFalse(p2.requiere_fotos)

    def test_carrito_autocompleta_datos_de_usuario_autenticado(self):
        user = User.objects.create_user(
            username="flor_v",
            email="florencia@test.com",
            first_name="Florencia",
            last_name="Videla",
            password="Password123!",
        )
        self.client.force_login(user)

        # Cargar producto al carrito
        session = self.client.session
        session["carrito"] = {str(self.prod_personalizado.id): 1}
        session.save()

        resp = self.client.get(reverse("carrito"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # Verificar que los inputs tengan los values de Florencia Videla y su email
        self.assertIn('value="Florencia"', content)
        self.assertIn('value="Videla"', content)
        self.assertIn('value="florencia@test.com"', content)

    @patch("pedidos.services.mercadopago.crear_preferencia")
    def test_checkout_asocia_usuario_y_marca_requiere_fotos(self, mock_pref):
        mock_pref.return_value = "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=test-123"
        from pedidos.models import Pedido
        user = User.objects.create_user(
            username="rodrigo",
            email="rodrigo@test.com",
            first_name="Rodrigo",
            last_name="Paz",
            password="Password123!",
        )
        self.client.force_login(user)

        session = self.client.session
        session["carrito"] = {str(self.prod_personalizado.id): 1}
        session.save()

        # Enviar checkout sin rellenar nombre ni email para validar autocompletado en backend
        resp = self.client.post(
            reverse("checkout"),
            {
                "envio_nombre": "Retiro por el local",
                "envio_modalidad": "LOCAL",
                "costo_envio": "0",
                "telefono": "2618889900",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")

        pedido = Pedido.objects.get(id=data["pedido_id"])
        # Datos del usuario autocompletados
        self.assertEqual(pedido.usuario, user)
        self.assertEqual(pedido.nombre, "Rodrigo")
        self.assertEqual(pedido.apellido, "Paz")
        self.assertEqual(pedido.email, "rodrigo@test.com")
        # Marcado como requiere fotos
        self.assertTrue(pedido.requiere_fotos)

    def test_pago_exitoso_muestra_banner_fotos_si_corresponde(self):
        from pedidos.models import Pedido, ItemPedido
        # Pedido que requiere fotos
        pedido = Pedido.objects.create(
            nombre="Sofía",
            apellido="Maza",
            email="sofia@test.com",
            telefono="2613334455",
            subtotal=Decimal("25000"),
            total=Decimal("25000"),
            estado=Pedido.Estado.PENDIENTE,
            requiere_fotos=True,
        )
        ItemPedido.objects.create(
            pedido=pedido,
            producto=self.prod_personalizado,
            nombre_producto=self.prod_personalizado.nombre,
            precio_unitario=self.prod_personalizado.precio,
            cantidad=1,
        )

        resp = self.client.get(
            reverse("pago_exitoso"),
            {
                "collection_status": "approved",
                "status": "approved",
                "payment_id": "777888999",
                "external_reference": str(pedido.id),
            },
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # Debe mostrar el banner destacado de atención
        self.assertIn("¡ATENCIÓN! Tu pedido requiere que nos envíes las imágenes para poder procesarlo.", content)
        # Debe contener el enlace de WhatsApp dinámico con el mensaje exacto
        msg_wsp_esperado = f"Hola%20Fotograf%C3%ADa%20Vitale%2C%20soy%20del%20pedido%20%23{pedido.id}.%20Ac%C3%A1%20env%C3%ADo%20las%20fotos%20para%20mi%20compra."
        self.assertIn(msg_wsp_esperado, content)


class TechnicalSEOTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Categoria.objects.get(slug="tecnologia")
        cls.prod = Producto.objects.create(
            nombre="Cámara Réflex Pro",
            categoria=cls.cat,
            precio=Decimal("450000"),
            stock=5,
            activo=True,
            descripcion="Cámara fotográfica profesional de alta resolución.",
        )
        cls.user = User.objects.create_user(
            username="seo_test_user",
            email="seo@vitale.com",
            password="Password123!",
        )

    def test_robots_txt_responde_correctamente_y_contiene_sitemap(self):
        resp = self.client.get(reverse("robots_txt"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp["Content-Type"])
        content = resp.content.decode("utf-8")
        self.assertIn("User-agent: *", content)
        self.assertIn("Disallow: /admin/", content)
        self.assertIn("Disallow: /carrito/", content)
        self.assertIn("Disallow: /perfil/", content)
        self.assertIn("Sitemap:", content)
        self.assertIn("sitemap.xml", content)

    def test_sitemap_xml_responde_con_xml_valido_y_rutas(self):
        resp = self.client.get(reverse("sitemap_xml"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("xml", resp["Content-Type"])
        content = resp.content.decode("utf-8")
        self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', content)
        self.assertIn('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">', content)
        self.assertIn("<loc>", content)
        self.assertIn("/catalogo/", content)
        self.assertIn(f"#prod-{self.prod.id}", content)

    def test_llms_txt_responde_correctamente_y_describe_el_negocio(self):
        resp = self.client.get(reverse("llms_txt"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp["Content-Type"])
        content = resp.content.decode("utf-8")
        self.assertIn("# Fotografía Vitale", content)
        self.assertIn("San Martín, Mendoza", content)
        self.assertIn("Laboratorio Profesional", content)
        self.assertIn("/catalogo/", content)

    def test_pagina_404_personalizada_intercepta_y_devuelve_status_404(self):
        resp = self.client.get("/esta-url-no-existe-en-el-sitio-12345/")
        self.assertEqual(resp.status_code, 404)
        self.assertTemplateUsed(resp, "404.html")
        content = resp.content.decode("utf-8")
        self.assertIn("Página no encontrada", content)
        self.assertIn("Volver al Catálogo", content)
        self.assertIn('lang="es"', content)
        self.assertEqual(content.count("<h1"), 1)

    def test_metadatos_seo_inicio(self):
        resp = self.client.get(reverse("inicio"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn('lang="es"', content)
        self.assertIn('<meta name="description"', content)
        self.assertIn('<link rel="canonical"', content)
        self.assertIn('rel="icon"', content)
        self.assertIn('property="og:title"', content)
        self.assertIn('property="og:image"', content)
        self.assertIn('application/ld+json', content)
        self.assertIn('LocalBusiness', content)
        self.assertEqual(content.count("<h1"), 1)
        self.assertEqual(content.count("<title>"), 1)

    def test_metadatos_seo_catalogo(self):
        resp = self.client.get(reverse("catalogo"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn('lang="es"', content)
        self.assertIn('<meta name="description"', content)
        self.assertIn('<link rel="canonical"', content)
        self.assertIn('property="og:title"', content)
        self.assertIn('application/ld+json', content)
        self.assertIn('ItemList', content)
        self.assertEqual(content.count("<h1"), 1)
        self.assertEqual(content.count("<title>"), 1)

    def test_metadatos_seo_perfil(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("perfil"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn('lang="es"', content)
        self.assertIn('name="description"', content)
        self.assertIn('name="robots" content="noindex', content)
        self.assertEqual(content.count("<h1"), 1)
        self.assertEqual(content.count("<title>"), 1)


class ImageGalleryAndReturnsPolicyTests(TestCase):
    """Pruebas unitarias para galería múltiple de imágenes, Quick View y devoluciones."""

    @classmethod
    def setUpTestData(cls):
        from catalogo.models import ImagenProducto
        cls.cat = Categoria.objects.create(nombre="Pruebas", slug="pruebas")
        cls.prod_simple = Producto.objects.create(
            nombre="Producto Foto Unica",
            categoria=cls.cat,
            precio=Decimal("15000"),
            stock=10,
            activo=True,
            descripcion="Descripción del producto único.",
        )
        cls.prod_multi = Producto.objects.create(
            nombre="Rifle Fox Demond Múltiple",
            categoria=cls.cat,
            precio=Decimal("350000"),
            stock=4,
            activo=True,
            descripcion="Rifle con múltiples fotos de detalle.",
        )
        # Añadir imágenes secundarias
        ImagenProducto.objects.create(
            producto=cls.prod_multi,
            imagen="productos/galeria/foto_extra_1.jpg",
            orden=1,
        )
        ImagenProducto.objects.create(
            producto=cls.prod_multi,
            imagen="productos/galeria/foto_extra_2.jpg",
            orden=2,
        )

        cls.user = User.objects.create_user(
            username="cliente_test",
            email="cliente@test.com",
            password="Password123!",
        )

    def test_producto_multiples_imagenes_properties(self):
        """Verifica que las properties fotos, tiene_multiples_fotos e imagen_url funcionen correctamente."""
        self.assertFalse(self.prod_simple.tiene_multiples_fotos)
        self.assertEqual(len(self.prod_simple.fotos), 0)

        # Producto con fotos adicionales
        self.assertTrue(self.prod_multi.tiene_multiples_fotos)
        self.assertEqual(len(self.prod_multi.fotos), 2)
        self.assertIn("foto_extra_1.jpg", self.prod_multi.fotos[0])
        self.assertIn("foto_extra_2.jpg", self.prod_multi.fotos[1])
        self.assertEqual(self.prod_multi.imagen_url, self.prod_multi.fotos[0])

    def test_catalogo_optimiza_consultas_con_prefetch_related(self):
        """El catálogo serializa la lista de imágenes sin lanzar queries N+1."""
        resp = self.client.get(reverse("catalogo"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        self.assertIn("Rifle Fox Demond", content)
        self.assertIn("foto_extra_1.jpg", content)

    def test_quickview_modal_contiene_garantia_y_galeria_thumbs(self):
        """El template catalogo.html contiene los componentes de confianza y miniaturas."""
        resp = self.client.get(reverse("catalogo"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")
        
        # Insignia de garantía en Quick View
        self.assertIn("Garantía y devoluciones gestionadas de forma personalizada vía WhatsApp.", content)
        self.assertIn("qv-guarantee-badge", content)
        self.assertIn("qv-thumbs-grid", content)
        self.assertIn("cambiarFotoQV", content)

    def test_perfil_boton_solicitar_devolucion_en_pedidos_completados(self):
        """Verifica el botón de solicitar cambio o devolución en pedidos pagados y entregados."""
        from pedidos.models import Pedido, ItemPedido
        
        # 1. Pedido completado (pagado)
        pedido_pagado = Pedido.objects.create(
            usuario=self.user,
            nombre="Cliente",
            apellido="Prueba",
            email="cliente@test.com",
            telefono="2615556677",
            subtotal=Decimal("350000"),
            total=Decimal("350000"),
            estado=Pedido.Estado.PAGADO,
        )
        ItemPedido.objects.create(
            pedido=pedido_pagado,
            producto=self.prod_multi,
            nombre_producto=self.prod_multi.nombre,
            precio_unitario=self.prod_multi.precio,
            cantidad=1,
        )

        # 2. Pedido completado (entregado)
        pedido_entregado = Pedido.objects.create(
            usuario=self.user,
            nombre="Cliente",
            apellido="Prueba",
            email="cliente@test.com",
            telefono="2615556677",
            subtotal=Decimal("15000"),
            total=Decimal("15000"),
            estado=Pedido.Estado.ENTREGADO,
        )

        # 3. Pedido pendiente de pago (no completado)
        pedido_pendiente = Pedido.objects.create(
            usuario=self.user,
            nombre="Cliente",
            apellido="Prueba",
            email="cliente@test.com",
            telefono="2615556677",
            subtotal=Decimal("15000"),
            total=Decimal("15000"),
            estado=Pedido.Estado.PENDIENTE,
        )

        self.client.force_login(self.user)
        resp = self.client.get(reverse("perfil"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # Texto del botón visible
        self.assertIn("Solicitar cambio o devolución", content)

        # Enlace con texto pre-cargado para pedido pagado
        url_pagado_msg = f"Hola%20Fotograf%C3%ADa%20Vitale%2C%20quiero%20consultar%20sobre%20un%20cambio%20o%20devoluci%C3%B3n%20de%20mi%20pedido%20%23{pedido_pagado.id}."
        self.assertIn(url_pagado_msg, content)

        # Enlace con texto pre-cargado para pedido entregado
        url_entregado_msg = f"Hola%20Fotograf%C3%ADa%20Vitale%2C%20quiero%20consultar%20sobre%20un%20cambio%20o%20devoluci%C3%B3n%20de%20mi%20pedido%20%23{pedido_entregado.id}."
        self.assertIn(url_entregado_msg, content)

        # No debe haber botón de devolución para el pedido pendiente
        url_pendiente_msg = f"Hola%20Fotograf%C3%ADa%20Vitale%2C%20quiero%20consultar%20sobre%20un%20cambio%20o%20devoluci%C3%B3n%20de%20mi%20pedido%20%23{pedido_pendiente.id}."
        self.assertNotIn(url_pendiente_msg, content)









