"""Pruebas de perfil, foto, contraseña, Mis audios gratis, dueño de las descargas,
cuota, renovación a la 1:00 a. m., Facebook y planes del seed."""
from .conftest import registrar
import time
import uuid
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest

from app import config
from app.database import SessionLocal
from app.repositories import suscripciones as repo_suscripciones
from app.repositories import trabajos as repo_trabajos
from app.seed import PLANES, _preparar_planes
from app.services import correo, cuotas, social

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


@pytest.fixture
def buzon(monkeypatch):
    """Correos enviados: (destino, texto)."""
    recibidos = []
    monkeypatch.setattr(correo, "enviar", lambda destino, asunto, texto, cuerpo_html=None: recibidos.append((destino, texto)))
    return recibidos


def _codigo(texto: str) -> str:
    import re
    return re.search(r"#verificar=(\S+)", texto).group(1)


def _cuenta(cliente, password="clave-segura-1"):
    email = f"perfil_{uuid.uuid4().hex[:10]}@ejemplo.com"
    registrar(cliente, json={"email": email, "nombre": "Perfil", "password": password})
    token = cliente.post("/auth/login", json={"email": email, "password": password}).cookies["splitter_sesion"]
    return email, {"Authorization": f"Bearer {token}"}


# ---------- Perfil ----------
def test_cambiar_nombre_y_telefono(cliente):
    _, cab = _cuenta(cliente)
    res = cliente.patch("/auth/perfil", json={"nombre": "  Nuevo Nombre "}, headers=cab)
    assert res.status_code == 200 and res.json()["nombre"] == "Nuevo Nombre"
    res = cliente.patch("/auth/perfil", json={"telefono": "+52 55 1234 5678"}, headers=cab)
    assert res.status_code == 200
    cuenta = cliente.get("/suscripcion", headers=cab).json()
    assert cuenta["nombre"] == "Nuevo Nombre"
    assert cuenta["telefono"] == "+52 55 1234 5678"
    assert cuenta["foto_url"] is None
    # Vacío lo borra
    cliente.patch("/auth/perfil", json={"telefono": ""}, headers=cab)
    assert cliente.get("/suscripcion", headers=cab).json()["telefono"] is None


@pytest.mark.parametrize("cuerpo", [{}, {"nombre": "a", "email": "b@c.com"}, {"nombre": ""}, {"telefono": "123"},
                                    {"telefono": "abc12345678"}, {"email": "no-es-correo"}])
def test_perfil_rechaza_datos_malos(cliente, cuerpo):
    _, cab = _cuenta(cliente)
    assert cliente.patch("/auth/perfil", json=cuerpo, headers=cab).status_code == 400


def test_cambiar_email_pide_confirmarlo(cliente, buzon):
    viejo, cab = _cuenta(cliente)
    otro, _ = _cuenta(cliente)
    assert cliente.patch("/auth/perfil", json={"email": otro.upper()}, headers=cab).status_code == 409
    nuevo = f"nuevo_{uuid.uuid4().hex[:8]}@ejemplo.com"
    res = cliente.patch("/auth/perfil", json={"email": nuevo}, headers=cab)
    assert res.status_code == 200
    assert res.json()["email"] == viejo and res.json()["email_pendiente"] == nuevo
    # Hasta abrir el enlace, el correo sigue igual
    assert cliente.get("/suscripcion", headers=cab).json()["email"] == viejo
    destino, texto = buzon[-1]
    assert destino == nuevo
    res = cliente.post("/auth/verificar", json={"codigo": _codigo(texto)})
    assert res.status_code == 200
    cuenta = cliente.get("/suscripcion", headers=cab).json()
    assert cuenta["email"] == nuevo and cuenta["email_verificado"] is True
    assert buzon[-1][0] == viejo  # aviso al correo anterior
    assert cliente.post("/auth/login", json={"email": nuevo, "password": "clave-segura-1"}).status_code == 200


def test_perfil_pide_sesion(cliente):
    assert cliente.patch("/auth/perfil", json={"nombre": "x"}).status_code == 401


# ---------- Foto ----------
@pytest.mark.parametrize("contenido,tipo", [(PNG, "image/png"), (JPG, "image/jpeg"), (WEBP, "image/webp")])
def test_subir_foto(cliente, contenido, tipo):
    _, cab = _cuenta(cliente)
    res = cliente.put("/auth/perfil/foto", files={"foto": ("yo.img", contenido, "application/octet-stream")}, headers=cab)
    assert res.status_code == 200
    url = res.json()["foto_url"]
    assert cliente.get("/suscripcion", headers=cab).json()["foto_url"] == url
    imagen = cliente.get(url)
    assert imagen.status_code == 200 and imagen.headers["content-type"] == tipo and imagen.content == contenido


def test_foto_nueva_borra_la_anterior(cliente):
    _, cab = _cuenta(cliente)
    primera = cliente.put("/auth/perfil/foto", files={"foto": ("a.png", PNG)}, headers=cab).json()["foto_url"]
    cliente.put("/auth/perfil/foto", files={"foto": ("b.jpg", JPG)}, headers=cab)
    assert cliente.get(primera).status_code == 404


def test_foto_rechaza_otros_archivos_y_grandes(cliente):
    _, cab = _cuenta(cliente)
    falsa = cliente.put("/auth/perfil/foto", files={"foto": ("x.png", b"<svg></svg>", "image/png")}, headers=cab)
    assert falsa.status_code == 415
    grande = cliente.put("/auth/perfil/foto", files={"foto": ("g.png", PNG + b"\x00" * config.MAX_FOTO_BYTES)}, headers=cab)
    assert grande.status_code == 413
    assert cliente.get("/auth/fotos/..%2F..%2Fsplitter.db").status_code == 404


# ---------- Contraseña ----------
def test_cambiar_password(cliente):
    email, cab = _cuenta(cliente)
    # Otra sesión abierta: se cierra al cambiar la contraseña
    otro_token = cliente.post("/auth/login", json={"email": email, "password": "clave-segura-1"}).cookies["splitter_sesion"]
    malo = cliente.post("/auth/password", json={"actual": "equivocada", "nueva": "otra-clave-2"}, headers=cab)
    assert malo.status_code == 403
    corta = cliente.post("/auth/password", json={"actual": "clave-segura-1", "nueva": "corta"}, headers=cab)
    assert corta.status_code == 400
    ok = cliente.post("/auth/password", json={"actual": "clave-segura-1", "nueva": "otra-clave-2"}, headers=cab)
    assert ok.status_code == 204
    assert cliente.get("/suscripcion", headers=cab).status_code == 200  # esta sesión sigue
    assert cliente.get("/suscripcion", headers={"Authorization": f"Bearer {otro_token}"}).status_code == 401
    assert cliente.post("/auth/login", json={"email": email, "password": "clave-segura-1"}).status_code == 401
    assert cliente.post("/auth/login", json={"email": email, "password": "otra-clave-2"}).status_code == 200


# ---------- Mis audios en Gratis y dueño de las descargas ----------
def _esperar(cliente, job_id, cab):
    limite = time.time() + 60
    while time.time() < limite:
        datos = cliente.get(f"/api/jobs/{job_id}", headers=cab).json()
        if datos["status"] in ("done", "error"):
            return datos
        time.sleep(0.3)
    raise AssertionError("El trabajo no terminó a tiempo")


def test_gratis_ve_mis_audios_y_nadie_mas_baja_sus_pistas(cliente, audio_wav):
    _, cab = _cuenta(cliente)
    cuenta = cliente.get("/suscripcion", headers=cab).json()
    assert cuenta["plan"] == "gratis" and cuenta["historial"] is True

    res = cliente.post("/api/jobs", files={"file": ("mio.wav", audio_wav, "audio/wav")}, data={"preset": "2stem"}, headers=cab)
    assert res.status_code == 202
    job_id = res.json()["id"]
    final = _esperar(cliente, job_id, cab)
    assert final["status"] == "done"

    historial = cliente.get("/trabajos", headers=cab)
    assert historial.status_code == 200
    assert [t["id"] for t in historial.json()] == [job_id]

    base = f"/api/jobs/{job_id}"
    sin_firma = [f"{base}/events", f"{base}/stems/vocals/preview", f"{base}/stems/vocals/download", f"{base}/download"]
    # Sin token ni firma: como si no existiera
    for url in sin_firma:
        assert cliente.get(url).status_code == 404, url
    assert cliente.get(f"{base}/stems/vocals/preview", params={"firma": "0" * 40}).status_code == 404
    # Otra cuenta con su propio token tampoco
    _, intruso = _cuenta(cliente)
    assert cliente.get(f"{base}/stems/vocals/download", headers=intruso).status_code == 404
    # El dueño con su token sí
    assert cliente.get(f"{base}/stems/vocals/preview", headers=cab).status_code == 200
    # Y con los enlaces firmados que le dio la API (lo que usa el navegador)
    pista = final["stems"][0]
    assert cliente.get(pista["preview_url"]).status_code == 200
    assert cliente.get(pista["download_url"] + "&format=mp3&prepare=1").json() == {"ready": True}
    assert cliente.get(final["download_all_url"] + "&format=wav").status_code == 200
    assert cliente.get(final["events_url"]).status_code == 200
    enlace = historial.json()[0]["resultados"][0]["download_url"]
    assert cliente.get(enlace).status_code == 200


def test_firma_de_un_trabajo_no_sirve_para_otro(cliente, audio_wav):
    _, cab = _cuenta(cliente)
    ids = []
    for _ in range(2):
        r = cliente.post("/api/jobs", files={"file": ("a.wav", audio_wav, "audio/wav")}, data={"preset": "2stem"}, headers=cab)
        ids.append(r.json()["id"])
    uno = _esperar(cliente, ids[0], cab)
    _esperar(cliente, ids[1], cab)
    firma = parse_qs(urlparse(uno["stems"][0]["preview_url"]).query)["firma"][0]
    assert cliente.get(f"/api/jobs/{ids[1]}/stems/vocals/preview", params={"firma": firma}).status_code == 404


# ---------- Cuota ----------
def test_errores_del_servidor_no_cuentan(cliente):
    _, cab = _cuenta(cliente)
    usuario_id = None
    with SessionLocal() as db:
        from app.repositories import usuarios as repo_usuarios
        email = cliente.get("/suscripcion", headers=cab).json()["email"]
        usuario_id = repo_usuarios.buscar_por_email(db, email).id
        datos = dict(usuario_id=usuario_id, nombre_original="x", tamano_bytes=1, preset="2stem", pistas_pedidas="vocals")
        repo_trabajos.crear(db, id=uuid.uuid4().hex, estado="error", mensaje_error="Falló la GPU", **datos)
        repo_trabajos.crear(db, id=uuid.uuid4().hex, estado="error", mensaje_error=repo_trabajos.CANCELADO, **datos)
        repo_trabajos.crear(db, id=uuid.uuid4().hex, estado="completado", **datos)
    assert cliente.get("/suscripcion", headers=cab).json()["trabajos_usados"] == 2


# ---------- Renovación a la 1:00 a. m. (hora de México) ----------
@pytest.mark.parametrize("inicio,fin", [
    # 14:30 en CDMX (20:30 UTC) -> 30 días después a la 1:00 CDMX = 7:00 UTC
    (datetime(2026, 11, 17, 20, 30), datetime(2026, 12, 17, 7, 0)),
    # 23:30 en CDMX del 16 (5:30 UTC del 17): el día local es el 16
    (datetime(2026, 11, 17, 5, 30), datetime(2026, 12, 16, 7, 0)),
])
def test_fin_de_periodo_a_la_una(inicio, fin):
    assert cuotas.fin_de_periodo(inicio) == fin


def test_cuenta_nueva_vence_a_la_una(cliente):
    _, cab = _cuenta(cliente)
    fin = cliente.get("/suscripcion", headers=cab).json()["fin_periodo"]
    assert fin.endswith("T07:00:00Z")


# ---------- Facebook ----------
@pytest.fixture
def facebook(monkeypatch):
    perfil = {"email": "", "name": "Alguien"}
    for clave in ("google", "facebook"):
        monkeypatch.setitem(social.PROVEEDORES[clave], "id", "id")
        monkeypatch.setitem(social.PROVEEDORES[clave], "secreto", "secreto")
    monkeypatch.setattr(social, "_pedir_json", lambda url, datos=None, permiso="": {"access_token": "t"} if datos else perfil)
    return perfil


def _entrar_con(cliente, proveedor):
    estado = parse_qs(urlparse(cliente.get(f"/auth/social/{proveedor}", follow_redirects=False).headers["location"]).query)["state"][0]
    return cliente.get(f"/auth/social/{proveedor}/regreso", params={"code": "c", "state": estado}, follow_redirects=False).headers["location"]


def test_facebook_no_entra_a_una_cuenta_con_contrasena(cliente, facebook):
    email, _ = _cuenta(cliente)
    facebook["email"] = email
    assert _entrar_con(cliente, "facebook").startswith("/#error=")


def test_facebook_si_entra_a_su_propia_cuenta(cliente, facebook):
    facebook["email"] = f"fb_{uuid.uuid4().hex[:8]}@ejemplo.com"
    assert _entrar_con(cliente, "facebook").startswith("/#sesion=")
    assert _entrar_con(cliente, "facebook").startswith("/#sesion=")


# ---------- Planes del seed ----------
def test_seed_actualiza_planes_existentes(cliente):
    with SessionLocal() as db:
        repo_suscripciones.buscar_plan(db, "pro").precio_mensual = 1
        db.commit()
    _preparar_planes()
    with SessionLocal() as db:
        pro = repo_suscripciones.buscar_plan(db, "pro")
        esperado = next(p for p in PLANES if p["nombre"] == "pro")
        assert pro.precio_mensual == esperado["precio_mensual"]
