from django.db import migrations


def cargar_datos_iniciales(apps, schema_editor):
    Categoria = apps.get_model("catalogo", "Categoria")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    # 1. Categorías iniciales del catálogo actual
    categorias = [
        {"nombre": "Fotografía", "slug": "fotografia", "orden": 1},
        {"nombre": "Tecnología y Computación", "slug": "tecnologia", "orden": 2},
        {"nombre": "Camping, Caza y Pesca", "slug": "outdoor", "orden": 3},
        {"nombre": "Accesorios y Varios", "slug": "varios", "orden": 4},
    ]
    for cat in categorias:
        Categoria.objects.get_or_create(slug=cat["slug"], defaults=cat)

    # 2. Grupo "Empleados" con permisos de ver/agregar/editar catálogo sin borrar ni ver pedidos
    grupo, _ = Group.objects.get_or_create(name="Empleados")

    codenames = [
        ("catalogo", "categoria", "view_categoria", "Can view categoría"),
        ("catalogo", "categoria", "add_categoria", "Can add categoría"),
        ("catalogo", "categoria", "change_categoria", "Can change categoría"),
        ("catalogo", "producto", "view_producto", "Can view producto"),
        ("catalogo", "producto", "add_producto", "Can add producto"),
        ("catalogo", "producto", "change_producto", "Can change producto"),
        ("catalogo", "imagenproducto", "view_imagenproducto", "Can view imagen adicional"),
        ("catalogo", "imagenproducto", "add_imagenproducto", "Can add imagen adicional"),
        ("catalogo", "imagenproducto", "change_imagenproducto", "Can change imagen adicional"),
    ]
    for app_label, model, codename, name in codenames:
        ct, _ = ContentType.objects.get_or_create(app_label=app_label, model=model)
        perm, _ = Permission.objects.get_or_create(
            content_type=ct, codename=codename, defaults={"name": name}
        )
        grupo.permissions.add(perm)


def revertir_datos_iniciales(apps, schema_editor):
    Categoria = apps.get_model("catalogo", "Categoria")
    Group = apps.get_model("auth", "Group")

    Categoria.objects.filter(slug__in=["fotografia", "tecnologia", "outdoor", "varios"]).delete()
    Group.objects.filter(name="Empleados").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalogo", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(cargar_datos_iniciales, revertir_datos_iniciales),
    ]
