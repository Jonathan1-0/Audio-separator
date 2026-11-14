"""Pruebas de entrar con Google o Facebook (respuestas simuladas)."""
import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from app.services import social


@pytest.fixture
def proveedor_falso(monkeypatch):
    """Pone claves de prueba y simula la respuesta del proveedor."""
    perfil = {"email": f"social_{uuid.uuid4().hex[:8]}@ejemplo.com", "name": "Persona Social", "email_verified": True}
    for clave in ("google", "facebook"):
        monkeypatch.setitem(social.PROVEEDORES[clave], "id", "id-de-prueba")
        monkeypatch.setitem(social.PROVEEDORES[clave], "secreto", "secreto-de-prueba")

    def responder(url, datos=None, permiso=""):
        return {"access_token": "permiso-de-prueba"} if datos else perfil

    monkeypatch.setattr(social, "_pedir_json", responder)
    return perfil


def _empezar(cliente, proveedor):
    """Inicia el acceso y devuelve el estado y la dirección."""
    res = cliente.get(f"/auth/social/{proveedor}", follow_redirects=False)
    assert res.status_code == 307
    return parse_qs(urlparse(res.headers["location"]).query)["state"][0], res.headers["location"]


def _regresar(cliente, proveedor, estado, code="codigo"):
    return cliente.get(f"/auth/social/{proveedor}/regreso", params={"code": code, "state": estado}, follow_redirects=False)


def test_sin_claves_no_hay_botones(cliente):
    assert cliente.get("/auth/social").json() == {"google": False, "facebook": False}
    assert cliente.get("/auth/social/google", follow_redirects=False).status_code == 503


def test_proveedor_que_no_existe(cliente):
    assert cliente.get("/auth/social/apple", follow_redirects=False).status_code == 404


def test_con_claves_aparecen_los_botones(cliente, proveedor_falso):
    assert cliente.get("/auth/social").json() == {"google": True, "facebook": True}


def test_inicio_manda_a_google(cliente, proveedor_falso):
    _, destino = _empezar(cliente, "google")
    assert destino.startswith("https://accounts.google.com/")
    assert "client_id=id-de-prueba" in destino


@pytest.mark.parametrize("proveedor", ["google", "facebook"])
def test_entrar_crea_la_cuenta_y_abre_sesion(cliente, proveedor_falso, proveedor):
    estado, _ = _empezar(cliente, proveedor)
    res = _regresar(cliente, proveedor, estado)
    assert res.headers["location"].startswith("/#sesion=")
    token = res.headers["location"].split("=", 1)[1]
    cuenta = cliente.get("/suscripcion", headers={"Authorization": f"Bearer {token}"})
    assert cuenta.status_code == 200
    assert cuenta.json()["email"] == proveedor_falso["email"]
    assert cuenta.json()["plan"] == "gratis"


def test_entrar_dos_veces_usa_la_misma_cuenta(cliente, proveedor_falso):
    correos = []
    for _ in range(2):
        estado, _ = _empezar(cliente, "google")
        token = _regresar(cliente, "google", estado).headers["location"].split("=", 1)[1]
        correos.append(cliente.get("/suscripcion", headers={"Authorization": f"Bearer {token}"}).json()["email"])
    assert correos[0] == correos[1]


def test_estado_distinto_se_rechaza(cliente, proveedor_falso):
    _empezar(cliente, "google")
    res = _regresar(cliente, "google", "otro-estado")
    assert res.headers["location"].startswith("/#error=")


def test_cancelar_en_el_proveedor(cliente, proveedor_falso):
    estado, _ = _empezar(cliente, "google")
    res = cliente.get("/auth/social/google/regreso", params={"error": "access_denied", "state": estado}, follow_redirects=False)
    assert res.headers["location"].startswith("/#error=")


def test_google_con_correo_sin_verificar(cliente, proveedor_falso):
    proveedor_falso["email_verified"] = False
    estado, _ = _empezar(cliente, "google")
    assert _regresar(cliente, "google", estado).headers["location"].startswith("/#error=")


def test_facebook_sin_correo(cliente, proveedor_falso):
    proveedor_falso["email"] = ""
    estado, _ = _empezar(cliente, "facebook")
    assert _regresar(cliente, "facebook", estado).headers["location"].startswith("/#error=")
