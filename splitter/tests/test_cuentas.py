"""Pruebas de registro, login, logout y planes."""
from .conftest import registrar
import uuid


def _correo() -> str:
    return f"prueba_{uuid.uuid4().hex[:10]}@ejemplo.com"


def _registrar(cliente, email=None, password="clave-segura-1"):
    email = email or _correo()
    res = registrar(cliente, json={"email": email, "nombre": "Prueba", "password": password})
    return email, res


def test_salud(cliente):
    res = cliente.get("/api/health")
    assert res.status_code == 200


def test_configuracion_publica(cliente):
    datos = cliente.get("/api/config").json()
    assert datos["max_upload_mb"] > 0
    assert ".mp3" in datos["accepted_extensions"]
    assert "mp3" in datos["output_formats"]
    assert "2stem" in datos["presets"]


def test_planes_gratis_y_pro(cliente):
    datos = cliente.get("/suscripcion/planes").json()
    nombres = [plan["nombre"] for plan in datos["planes"]]
    assert "gratis" in nombres and "pro" in nombres


def _sesion(cliente) -> dict:
    """Crea una cuenta, inicia sesión y devuelve la cabecera con su token."""
    email, _ = _registrar(cliente)
    token = cliente.post("/auth/login", json={"email": email, "password": "clave-segura-1"}).cookies["splitter_sesion"]
    return {"Authorization": f"Bearer {token}"}


def test_registro_crea_la_cuenta(cliente):
    email, res = _registrar(cliente)
    assert res.status_code == 201
    assert res.json()["email"] == email


def test_cuenta_nueva_empieza_en_plan_gratis(cliente):
    datos = cliente.get("/suscripcion", headers=_sesion(cliente)).json()
    assert "gratis" in str(datos)


def test_registro_rechaza_correo_repetido(cliente):
    email, _ = _registrar(cliente)
    _, repetido = _registrar(cliente, email=email)
    assert repetido.status_code == 409


def test_registro_rechaza_password_corta(cliente):
    _, res = _registrar(cliente, password="corta")
    assert res.status_code == 400


def test_login_correcto(cliente):
    email, _ = _registrar(cliente)
    res = cliente.post("/auth/login", json={"email": email, "password": "clave-segura-1"})
    assert res.status_code == 200
    assert res.cookies["splitter_sesion"]


def test_login_con_password_incorrecta(cliente):
    email, _ = _registrar(cliente)
    res = cliente.post("/auth/login", json={"email": email, "password": "otra-clave-9"})
    assert res.status_code == 401


def test_mi_plan_pide_sesion(cliente):
    assert cliente.get("/suscripcion").status_code == 401


def test_mi_plan_con_sesion(cliente):
    assert cliente.get("/suscripcion", headers=_sesion(cliente)).status_code == 200


def test_logout_invalida_el_token(cliente):
    cabecera = _sesion(cliente)
    assert cliente.post("/auth/logout", headers=cabecera).status_code == 204
    assert cliente.get("/suscripcion", headers=cabecera).status_code == 401
