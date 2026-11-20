"""Pruebas de seguridad: límites, cabeceras, verificación de correo, cerrar sesiones y borrar la cuenta."""
from .test_perfil import PNG
from .conftest import registrar
import re
import time
import uuid

import pytest

from app.services import auth, correo

PASSWORD = "clave-segura-1"


@pytest.fixture
def buzon(monkeypatch):
    recibidos = []
    monkeypatch.setattr(correo, "enviar", lambda destino, asunto, texto, cuerpo_html=None: recibidos.append((destino, asunto, texto, cuerpo_html)))
    return recibidos


def _cuenta(cliente):
    email = f"seg_{uuid.uuid4().hex[:10]}@example.com"
    registrar(cliente, json={"email": email, "nombre": "Seg", "password": PASSWORD})
    token = cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).cookies["splitter_sesion"]
    return email, {"Authorization": f"Bearer {token}"}


# ---------- Límites ----------
def test_login_bloquea_tras_muchos_fallos(cliente, monkeypatch):
    monkeypatch.setattr(auth._fallos_por_cuenta, "max_events", 3)
    email, _ = _cuenta(cliente)
    for _ in range(3):
        assert cliente.post("/auth/login", json={"email": email, "password": "mala-clave"}).status_code == 401
    bloqueado = cliente.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert bloqueado.status_code == 429 and "Retry-After" in bloqueado.headers
    auth._fallos_por_cuenta.limpiar(email)


def test_login_correcto_borra_los_fallos(cliente, monkeypatch):
    monkeypatch.setattr(auth._fallos_por_cuenta, "max_events", 3)
    email, _ = _cuenta(cliente)
    for _ in range(2):
        cliente.post("/auth/login", json={"email": email, "password": "mala-clave"})
    assert cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    for _ in range(2):
        cliente.post("/auth/login", json={"email": email, "password": "mala-clave"})
    assert cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_login_limite_por_ip(cliente, monkeypatch):
    monkeypatch.setattr(auth._login_por_ip, "max_events", 2)
    monkeypatch.setattr(auth._login_por_ip, "_events", type(auth._login_por_ip._events)(auth._login_por_ip._events.default_factory))
    for _ in range(2):
        cliente.post("/auth/login", json={"email": "x@example.com", "password": "loquesea1"})
    assert cliente.post("/auth/login", json={"email": "x@example.com", "password": "loquesea1"}).status_code == 429


def test_registro_limite_por_ip(cliente, monkeypatch):
    monkeypatch.setattr(auth._registros_por_ip, "max_events", 1)
    monkeypatch.setattr(auth._registros_por_ip, "_events", type(auth._registros_por_ip._events)(auth._registros_por_ip._events.default_factory))
    _cuenta(cliente)
    res = registrar(cliente, json={"email": f"r_{uuid.uuid4().hex[:8]}@example.com", "nombre": "R", "password": PASSWORD})
    assert res.status_code == 429


# ---------- Cabeceras ----------
def test_cabeceras_de_seguridad(cliente):
    res = cliente.get("/")
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    csp = res.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]


def test_csp_permite_los_scripts_en_linea_de_la_pagina(cliente):
    import base64
    import hashlib
    html = cliente.get("/").text
    csp = cliente.get("/").headers["Content-Security-Policy"]
    for codigo in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S):
        digest = base64.b64encode(hashlib.sha256(codigo.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in csp


def test_datos_de_cuenta_no_se_guardan_en_cache(cliente):
    _, cab = _cuenta(cliente)
    assert cliente.get("/suscripcion", headers=cab).headers["Cache-Control"] == "no-store"


def test_sin_cors_para_otras_paginas(cliente):
    res = cliente.get("/suscripcion/planes", headers={"Origin": "https://malo.example"})
    assert "access-control-allow-origin" not in res.headers


# ---------- Verificar el correo ----------
def test_cuenta_nueva_queda_con_correo_confirmado(cliente):
    _, cab = _cuenta(cliente)
    assert cliente.get("/suscripcion", headers=cab).json()["email_verificado"] is True


def _sin_confirmar(email):
    from app.database import SessionLocal
    from app.repositories import usuarios as repo_usuarios
    with SessionLocal() as db:
        repo_usuarios.buscar_por_email(db, email).email_verificado = False
        db.commit()


def test_enlace_de_verificacion_alterado_no_sirve(cliente):
    assert cliente.post("/auth/verificar", json={"codigo": "basura"}).status_code == 400
    assert cliente.post("/auth/verificar", json={"codigo": "1.2.YQ.00"}).status_code == 400


def test_reenviar_confirmacion_a_cuentas_de_antes(cliente, buzon):
    email, cab = _cuenta(cliente)
    _sin_confirmar(email)  # como las cuentas creadas antes del código por correo
    antes = len(buzon)
    assert cliente.post("/auth/verificar/reenviar", headers=cab).status_code == 200
    assert len(buzon) == antes + 1
    codigo = re.search(r"#verificar=(\S+)", buzon[-1][2]).group(1)
    assert cliente.post("/auth/verificar", json={"codigo": codigo}).status_code == 200
    assert cliente.get("/suscripcion", headers=cab).json()["email_verificado"] is True


def test_pro_pide_correo_confirmado(cliente):
    email, cab = _cuenta(cliente)
    _sin_confirmar(email)
    datos = {"marca": "Visa", "ultimos4": "4242"}
    assert cliente.post("/suscripcion/pro", json=datos, headers=cab).status_code == 403


# ---------- Sesiones y cuenta ----------
def test_cerrar_todas_las_sesiones(cliente):
    email, cab = _cuenta(cliente)
    otra = cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).cookies["splitter_sesion"]
    assert cliente.post("/auth/logout-todo", headers=cab).status_code == 204
    assert cliente.get("/suscripcion", headers=cab).status_code == 401
    assert cliente.get("/suscripcion", headers={"Authorization": f"Bearer {otra}"}).status_code == 401


def test_cambiar_password_avisa_por_correo(cliente, buzon):
    email, cab = _cuenta(cliente)
    cliente.post("/auth/password", json={"actual": PASSWORD, "nueva": "otra-clave-9"}, headers=cab)
    assert buzon[-1][0] == email and "contraseña" in buzon[-1][1]


def test_borrar_cuenta(cliente, buzon, audio_wav):
    email, cab = _cuenta(cliente)
    foto = cliente.put("/auth/perfil/foto", files={"foto": ("a.png", PNG)}, headers=cab).json()["foto_url"]
    job = cliente.post("/api/jobs", files={"file": ("a.wav", audio_wav, "audio/wav")}, data={"preset": "2stem"}, headers=cab).json()
    limite = time.time() + 60
    while cliente.get(f"/api/jobs/{job['id']}", headers=cab).json()["status"] not in ("done", "error") and time.time() < limite:
        time.sleep(0.3)

    malo = cliente.request("DELETE", "/auth/cuenta", json={"password": "equivocada"}, headers=cab)
    assert malo.status_code == 403
    assert cliente.request("DELETE", "/auth/cuenta", json={"password": PASSWORD}, headers=cab).status_code == 204

    assert cliente.get("/suscripcion", headers=cab).status_code == 401
    assert cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert cliente.get(foto).status_code == 404
    assert cliente.get(f"/api/jobs/{job['id']}").status_code == 404
    assert buzon[-1][0] == email and "Borraste" in buzon[-1][1]
    # El correo queda libre para una cuenta nueva
    res = registrar(cliente, json={"email": email, "nombre": "Otra vez", "password": PASSWORD})
    assert res.status_code == 201


# ---------- Sesión en cookie ----------
def _login_cookie(cliente):
    email = f"cookie_{uuid.uuid4().hex[:10]}@example.com"
    registrar(cliente, json={"email": email, "nombre": "Galleta", "password": PASSWORD})
    token = cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).cookies["splitter_sesion"]
    return {"Cookie": f"splitter_sesion={token}"}


def test_la_cookie_abre_la_sesion(cliente):
    cookie = _login_cookie(cliente)
    assert cliente.get("/suscripcion", headers=cookie).status_code == 200
    res = cliente.patch("/auth/perfil", json={"nombre": "Desde aquí"}, headers={**cookie, "Origin": "http://testserver"})
    assert res.status_code == 200


def test_csrf_otro_sitio_no_puede_usar_la_cookie(cliente):
    cookie = _login_cookie(cliente)
    res = cliente.patch("/auth/perfil", json={"nombre": "Hackeado"}, headers={**cookie, "Origin": "https://malo.example"})
    assert res.status_code == 403
    res = cliente.request("DELETE", "/auth/cuenta", json={"password": PASSWORD}, headers={**cookie, "Origin": "https://malo.example"})
    assert res.status_code == 403


def test_logout_borra_la_cookie(cliente):
    cookie = _login_cookie(cliente)
    res = cliente.post("/auth/logout", headers={**cookie, "Origin": "http://testserver"})
    assert res.status_code == 204 and 'splitter_sesion=""' in res.headers["set-cookie"]
    assert cliente.get("/suscripcion", headers=cookie).status_code == 401


def test_cookie_vencida_no_rompe_lo_publico(cliente):
    # Un trabajo sin cuenta con una cookie que ya no sirve: se trata como sin sesión
    assert cliente.get("/api/jobs/noexiste", headers={"Cookie": "splitter_sesion=vieja"}).status_code == 404


def test_las_pruebas_nunca_mandan_correos_reales():
    from app import config
    assert config.SMTP_USER == ""


def test_sin_pagos_simulados_nadie_activa_pro(cliente, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "PAGOS_SIMULADOS", False)
    email, cab = _cuenta(cliente)
    res = cliente.post("/suscripcion/pro", json={"marca": "Visa", "ultimos4": "4242"}, headers=cab)
    assert res.status_code == 503
    assert cliente.get("/suscripcion/planes").json()["pagos_activos"] is False
