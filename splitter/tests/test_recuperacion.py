"""Pruebas de recuperar la contraseña."""
import re
import uuid

import pytest

from app.services import correo, recuperacion

PASSWORD = "clave-segura-1"


@pytest.fixture
def buzon(monkeypatch):
    """Guarda los correos en una lista en vez de enviarlos."""
    recibidos = []
    monkeypatch.setattr(correo, "enviar", lambda destino, asunto, texto: recibidos.append((destino, texto)))
    monkeypatch.setattr(recuperacion._por_ip, "max_events", 0)  # sin límite por IP
    return recibidos


def _cuenta_nueva(cliente) -> str:
    email = f"prueba_{uuid.uuid4().hex[:10]}@ejemplo.com"
    cliente.post("/auth/registro", json={"email": email, "nombre": "Prueba", "password": PASSWORD})
    return email


def _codigo_del_correo(texto: str) -> str:
    return re.search(r"#restablecer=(\S+)", texto).group(1)


def _login(cliente, email, password):
    return cliente.post("/auth/login", json={"email": email, "password": password})


def test_pedir_enlace_envia_correo(cliente, buzon):
    email = _cuenta_nueva(cliente)
    res = cliente.post("/auth/recuperar", json={"email": email})
    assert res.status_code == 200
    assert len(buzon) == 1
    assert buzon[0][0] == email


def test_correo_sin_cuenta_responde_igual_y_no_envia(cliente, buzon):
    res = cliente.post("/auth/recuperar", json={"email": "nadie@ejemplo.com"})
    assert res.status_code == 200
    assert buzon == []


def test_cambiar_password_con_el_enlace(cliente, buzon):
    email = _cuenta_nueva(cliente)
    cliente.post("/auth/recuperar", json={"email": email})
    codigo = _codigo_del_correo(buzon[0][1])

    res = cliente.post("/auth/restablecer", json={"codigo": codigo, "password": "otra-clave-22"})
    assert res.status_code == 200
    assert _login(cliente, email, "otra-clave-22").status_code == 200
    assert _login(cliente, email, PASSWORD).status_code == 401


def test_el_enlace_solo_sirve_una_vez(cliente, buzon):
    email = _cuenta_nueva(cliente)
    cliente.post("/auth/recuperar", json={"email": email})
    codigo = _codigo_del_correo(buzon[0][1])
    cliente.post("/auth/restablecer", json={"codigo": codigo, "password": "otra-clave-22"})
    repetido = cliente.post("/auth/restablecer", json={"codigo": codigo, "password": "tercera-clave-3"})
    assert repetido.status_code == 400


def test_cambiar_password_cierra_las_sesiones(cliente, buzon):
    email = _cuenta_nueva(cliente)
    cabecera = {"Authorization": f"Bearer {_login(cliente, email, PASSWORD).json()['token']}"}
    cliente.post("/auth/recuperar", json={"email": email})
    cliente.post("/auth/restablecer", json={"codigo": _codigo_del_correo(buzon[0][1]), "password": "otra-clave-22"})
    assert cliente.get("/suscripcion", headers=cabecera).status_code == 401


def test_codigo_inventado_o_alterado(cliente, buzon):
    email = _cuenta_nueva(cliente)
    cliente.post("/auth/recuperar", json={"email": email})
    codigo = _codigo_del_correo(buzon[0][1])
    for malo in ("hola", "1.2.3", codigo[:-1] + ("0" if codigo[-1] != "0" else "1")):
        res = cliente.post("/auth/restablecer", json={"codigo": malo, "password": "otra-clave-22"})
        assert res.status_code == 400


def test_enlace_vencido(cliente, buzon, monkeypatch):
    email = _cuenta_nueva(cliente)
    monkeypatch.setattr(recuperacion.config, "MINUTOS_RECUPERACION", -1)  # ya vencido
    cliente.post("/auth/recuperar", json={"email": email})
    res = cliente.post("/auth/restablecer", json={"codigo": _codigo_del_correo(buzon[0][1]), "password": "otra-clave-22"})
    assert res.status_code == 400


def test_password_nueva_muy_corta(cliente, buzon):
    email = _cuenta_nueva(cliente)
    cliente.post("/auth/recuperar", json={"email": email})
    res = cliente.post("/auth/restablecer", json={"codigo": _codigo_del_correo(buzon[0][1]), "password": "corta"})
    assert res.status_code == 400


def test_limite_de_solicitudes_por_ip(cliente, buzon, monkeypatch):
    monkeypatch.setattr(recuperacion._por_ip, "max_events", 2)
    recuperacion._por_ip._events.clear()
    respuestas = [cliente.post("/auth/recuperar", json={"email": "nadie@ejemplo.com"}).status_code for _ in range(3)]
    assert respuestas == [200, 200, 429]
