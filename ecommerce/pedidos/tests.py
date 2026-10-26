from decimal import Decimal

from django.test import TestCase

from catalogo.models import Categoria, Producto

from .models import ItemPedido, Pedido


class PedidoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Categoria.objects.get(slug="fotografia")
        cls.producto = Producto.objects.create(
            nombre="Promo 40 fotos", categoria=cat, precio=Decimal("23000"), stock=10
        )

    def test_item_copia_nombre_y_precio(self):
        pedido = Pedido.objects.create(nombre="Ana", email="ana@x.com")
        item = ItemPedido.objects.create(pedido=pedido, producto=self.producto, cantidad=2)
        self.assertEqual(item.nombre_producto, "Promo 40 fotos")
        self.assertEqual(item.precio_unitario, Decimal("23000"))

        # Cambiar el precio del producto no altera el pedido ya hecho.
        self.producto.precio = Decimal("30000")
        self.producto.save()
        item.refresh_from_db()
        self.assertEqual(item.precio_unitario, Decimal("23000"))
        self.assertEqual(pedido.recalcular_total(), Decimal("46000"))

    def test_to_mp_preference(self):
        pedido = Pedido.objects.create(nombre="Ana", email="ana@x.com")
        ItemPedido.objects.create(pedido=pedido, producto=self.producto, cantidad=1)
        pref = pedido.to_mp_preference(
            back_urls={"success": "https://x/ok"}, notification_url="https://x/webhook"
        )
        self.assertEqual(pref["external_reference"], str(pedido.codigo))
        self.assertEqual(pref["items"][0]["unit_price"], 23000.0)
        self.assertEqual(pref["payer"]["email"], "ana@x.com")
        self.assertEqual(pref["auto_return"], "approved")
        self.assertEqual(pref["notification_url"], "https://x/webhook")

    def test_crear_preferencia_suma_costo_de_envio(self):
        from unittest.mock import patch
        from pedidos.services.mercadopago import crear_preferencia

        pedido = Pedido.objects.create(nombre="Carlos", email="carlos@test.com")
        ItemPedido.objects.create(pedido=pedido, producto=self.producto, cantidad=1)

        with patch("pedidos.services.mercadopago.crear_preferencia_mp") as mock_mp:
            mock_mp.return_value = {
                "id": "pref-12345",
                "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=pref-12345"
            }
            url = crear_preferencia(pedido, costo_envio=3500, envio_nombre="Andreani Domicilio")
            self.assertIn("pref_id=pref-12345", url)
            pedido.refresh_from_db()
            self.assertEqual(pedido.mp_preference_id, "pref-12345")

            # Validar que los items incluyan el producto y el costo de envío
            items_enviados = mock_mp.call_args[1]["items"]
            self.assertEqual(len(items_enviados), 2)
            self.assertEqual(items_enviados[0]["title"], "Promo 40 fotos")
            self.assertEqual(items_enviados[1]["id"], "ENVIO")
            self.assertEqual(items_enviados[1]["unit_price"], 3500.0)
            self.assertIn("Andreani Domicilio", items_enviados[1]["title"])

    def test_crear_preferencia_mp_respeta_protocolo_local(self):
        from unittest.mock import patch, MagicMock
        from pedidos.services.mercadopago import crear_preferencia_mp

        with patch("mercadopago.SDK") as mock_sdk_class:
            mock_sdk = MagicMock()
            mock_sdk_class.return_value = mock_sdk
            mock_pref = MagicMock()
            mock_sdk.preference.return_value = mock_pref
            mock_pref.create.return_value = {
                "status": 201,
                "response": {"id": "pref-local-1", "init_point": "https://mp.com/checkout"}
            }

            local_back_urls = {
                "success": "http://127.0.0.1:8000/pago/exitoso/",
                "failure": "http://127.0.0.1:8000/carrito/",
                "pending": "http://127.0.0.1:8000/pago/exitoso/",
            }
            items = [{"title": "Test", "quantity": 1, "unit_price": 500.0}]

            crear_preferencia_mp(items=items, back_urls=local_back_urls)

            mock_pref.create.assert_called_once()
            called_pref_data = mock_pref.create.call_args[0][0]
            # Debe respetar el protocolo http:// sin reemplazarlo por https://
            self.assertEqual(called_pref_data["back_urls"]["success"], "http://127.0.0.1:8000/pago/exitoso/")
            self.assertEqual(called_pref_data["back_urls"]["failure"], "http://127.0.0.1:8000/carrito/")
            # En http no debe enviar auto_return para evitar error 400 de MP
            self.assertNotIn("auto_return", called_pref_data)


