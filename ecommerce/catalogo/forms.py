"""
Formularios de autenticación y registro de usuarios para Fotografía Vitale.
"""
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User


class RegistroUsuarioForm(UserCreationForm):
    first_name = forms.CharField(
        label="Nombre",
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Tu nombre",
            "autocomplete": "given-name",
        })
    )
    last_name = forms.CharField(
        label="Apellido",
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Tu apellido",
            "autocomplete": "family-name",
        })
    )
    email = forms.EmailField(
        label="Correo Electrónico",
        required=True,
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "tu@email.com",
            "autocomplete": "email",
        })
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")
        labels = {
            "username": "Nombre de usuario",
        }
        help_texts = {
            "username": "Requerido. 150 caracteres o menos. Letras, dígitos y @/./+/-/_ solamente.",
        }
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nombre de usuario único",
                "autocomplete": "username",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if "class" not in field.widget.attrs:
                field.widget.attrs["class"] = "form-control"
            if field_name == "password1":
                field.widget.attrs["placeholder"] = "Contraseña segura"
            elif field_name == "password2":
                field.widget.attrs["placeholder"] = "Repite la contraseña"

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email:
            email = email.strip().lower()
            if User.objects.filter(email__iexact=email).exists():
                raise forms.ValidationError("Ya existe una cuenta registrada con este correo electrónico.")
        return email


class LoginUsuarioForm(AuthenticationForm):
    username = forms.CharField(
        label="Usuario o Email",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Tu nombre de usuario",
            "autocomplete": "username",
            "autofocus": True,
        })
    )
    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "••••••••",
            "autocomplete": "current-password",
        })
    )
