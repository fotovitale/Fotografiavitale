# Fotografía Vitale — E-commerce (Django)

Backend de la tienda: catálogo administrable y base para cobros con Mercado Pago.

## Puesta en marcha (Windows / PowerShell)

```powershell
cd ecommerce
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # completar valores
python manage.py migrate
python manage.py createsuperuser # usuario del dueño
python manage.py runserver
```

Panel de administración: http://127.0.0.1:8000/admin/

## Alta de un empleado

1. Entrar al admin con el usuario del dueño.
2. **Usuarios → Agregar usuario**: elegir nombre y contraseña.
3. En la pantalla siguiente marcar **"Es staff"** y agregarlo al grupo **"Empleados"**.

El grupo *Empleados* puede ver, agregar y editar productos, imágenes y
categorías. No puede borrar productos, ni ver pedidos, pagos o usuarios.

## Estructura

| App | Contenido |
|---|---|
| `catalogo` | `Categoria`, `Producto`, `ImagenProducto` + admin |
| `pedidos` | `Pedido`, `ItemPedido`, `Pago` + esqueleto en `services/mercadopago.py` |

## Tests

```powershell
python manage.py test
```
