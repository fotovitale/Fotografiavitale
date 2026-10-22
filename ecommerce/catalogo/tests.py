from decimal import Decimal

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


