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
