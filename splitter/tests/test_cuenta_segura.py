"""Cancelar Pro al final del periodo, verificación en dos pasos, conectar Google y limpieza."""
import re
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from sqlalchemy import select

from app import config
from app.database import SessionLocal, ahora_utc
from app.mantenimiento import limpiar_base
from app.models.tablas import Sesion, Trabajo, Usuario
from app.repositories import trabajos as repo_trabajos
from app.repositories import usuarios as repo_usuarios
from app.services import correo, dos_pasos, social

PASSWORD = "clave-segura-1"


@pytest.fixture
def buzon(monkeypatch):
    recibidos = []
    monkeypatch.setattr(correo, "enviar", lambda destino, asunto, texto, cuerpo_html=None: recibidos.append((destino, asunto, texto)))
    return recibidos


@pytest.fixture(autouse=True)
def sin_codigos_usados(monkeypatch):
    # Cada prueba usa códigos del mismo minuto; la protección contra repetirlos se prueba aparte
    monkeypatch.setattr(dos_pasos, "_usados", {})


def _cuenta(cliente, buzon=None):
    email = f"segura_{uuid.uuid4().hex[:10]}@ejemplo.com"
    cliente.post("/auth/registro", json={"email": email, "nombre": "Segura", "password": PASSWORD})
    res = cliente.post("/auth/login", json={"email": email, "password": PASSWORD})
    return email, {"Authorization": f"Bearer {res.cookies['splitter_sesion']}"}


def _confirmar_correo(cliente, buzon):
    codigo = re.search(r"#verificar=(\S+)", buzon[-1][2]).group(1)
    cliente.post("/auth/verificar", json={"codigo": codigo})


# ---------- Cancelar Pro ----------
def test_cancelar_pro_sigue_hasta_el_fin_del_periodo(cliente, buzon):
    _, cab = _cuenta(cliente)
    _confirmar_correo(cliente, buzon)
    fin = cliente.post("/suscripcion/pro", json={"marca": "Visa", "ultimos4": "4242"}, headers=cab).json()["fin_periodo"]

    res = cliente.post("/suscripcion/cancelar", headers=cab)
    assert res.status_code == 200 and res.json()["cancelar_al_final"] is True
    cuenta = cliente.get("/suscripcion", headers=cab).json()
    assert cuenta["plan"] == "pro" and cuenta["cancelar_al_final"] is True and cuenta["fin_periodo"] == fin
    assert cliente.post("/suscripcion/cancelar", headers=cab).status_code == 409

    assert cliente.post("/suscripcion/reanudar", headers=cab).status_code == 200
    assert cliente.get("/suscripcion", headers=cab).json()["cancelar_al_final"] is False
    assert cliente.post("/suscripcion/reanudar", headers=cab).status_code == 409


def test_pro_cancelado_pasa_a_gratis_al_vencer(cliente, buzon):
    email, cab = _cuenta(cliente)
    _confirmar_correo(cliente, buzon)
    cliente.post("/suscripcion/pro", json={"marca": "Visa", "ultimos4": "4242"}, headers=cab)
    cliente.post("/suscripcion/cancelar", headers=cab)
    with SessionLocal() as db:
        from app.repositories import suscripciones as repo_suscripciones
        usuario = repo_usuarios.buscar_por_email(db, email)
        activa = repo_suscripciones.buscar_activa(db, usuario.id)
        activa.fin_periodo = ahora_utc() - timedelta(minutes=1)
        db.commit()
    assert cliente.get("/suscripcion", headers=cab).json()["plan"] == "gratis"


# ---------- Dos pasos ----------
def _activar(cliente, cab):
    datos = cliente.post("/auth/dos-pasos/iniciar", headers=cab).json()
    assert datos["qr"].startswith("data:image/svg+xml;base64,") and datos["enlace"].startswith("otpauth://totp/")
    secreto = datos["secreto"]
    assert cliente.post("/auth/dos-pasos/confirmar", json={"codigo": "000000"}, headers=cab).status_code == 400
    res = cliente.post("/auth/dos-pasos/confirmar", json={"codigo": dos_pasos.codigo_actual(secreto)}, headers=cab)
    assert res.status_code == 200
    return secreto, res.json()["codigos_respaldo"]


def test_dos_pasos_completo(cliente, buzon, monkeypatch):
    email, cab = _cuenta(cliente)
    secreto, respaldo = _activar(cliente, cab)
    assert len(respaldo) == 8
    assert cliente.get("/suscripcion", headers=cab).json()["dos_pasos"] is True
    assert "dos pasos" in buzon[-1][1]

    sin_codigo = cliente.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert sin_codigo.status_code == 401 and sin_codigo.headers["X-Splitter-Dos-Pasos"] == "requerido"
    assert "splitter_sesion" not in sin_codigo.cookies
    malo = cliente.post("/auth/login", json={"email": email, "password": PASSWORD, "codigo": "123456"})
    assert malo.status_code == 401

    monkeypatch.setattr(dos_pasos, "_usados", {})
    bueno = cliente.post("/auth/login", json={"email": email, "password": PASSWORD, "codigo": dos_pasos.codigo_actual(secreto)})
    assert bueno.status_code == 200 and bueno.cookies["splitter_sesion"]

    # Un código de respaldo sirve una sola vez
    con_respaldo = {"email": email, "password": PASSWORD, "codigo": respaldo[0].upper()}
    assert cliente.post("/auth/login", json=con_respaldo).status_code == 200
    assert cliente.post("/auth/login", json=con_respaldo).status_code == 401

    # Desactivar pide contraseña y código
    assert cliente.post("/auth/dos-pasos/desactivar", json={"password": "mala", "codigo": respaldo[1]}, headers=cab).status_code == 403
    assert cliente.post("/auth/dos-pasos/desactivar", json={"password": PASSWORD, "codigo": respaldo[1]}, headers=cab).status_code == 204
    assert cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_codigo_no_se_puede_repetir(cliente):
    _, cab = _cuenta(cliente)
    secreto, _ = _activar(cliente, cab)
    # El mismo código que confirmó la activación ya no sirve para entrar
    with SessionLocal() as db:
        usuario = db.scalar(select(Usuario).where(Usuario.totp_secreto == secreto))
        assert dos_pasos.verificar(usuario, dos_pasos.codigo_actual(secreto), db) is False


def _admin(cliente):
    token = cliente.post("/auth/login", json={"email": "admin@pruebas.com", "password": "admin-pruebas-1"}).cookies["splitter_sesion"]
    return {"Authorization": f"Bearer {token}"}


def test_panel_pide_dos_pasos(cliente, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_REQUIERE_DOS_PASOS", True)
    res = cliente.get("/admin/resumen", headers=_admin(cliente))
    assert res.status_code == 403 and "dos pasos" in res.json()["detail"]


# ---------- Google ----------
@pytest.fixture
def google(monkeypatch):
    perfil = {"email": "", "name": "Persona", "email_verified": True, "sub": ""}
    for clave in ("google", "facebook"):
        monkeypatch.setitem(social.PROVEEDORES[clave], "id", "id")
        monkeypatch.setitem(social.PROVEEDORES[clave], "secreto", "secreto")
    monkeypatch.setattr(social, "_pedir_json", lambda url, datos=None, permiso="": {"access_token": "t"} if datos else perfil)
    return perfil


def _google(cliente, cab=None, conectar=False):
    params = {"conectar": "1"} if conectar else {}
    inicio = cliente.get("/auth/social/google", params=params, headers=cab or {}, follow_redirects=False)
    estado = parse_qs(urlparse(inicio.headers["location"]).query)["state"][0]
    res = cliente.get("/auth/social/google/regreso", params={"code": "c", "state": estado}, headers=cab or {}, follow_redirects=False)
    return res


def test_google_no_abre_una_cuenta_con_contrasena(cliente, google):
    email, _ = _cuenta(cliente)
    google.update(email=email, sub=f"g-{uuid.uuid4().hex}")
    destino = unquote(_google(cliente).headers["location"])
    assert destino.startswith("/#error=") and "conecta Google desde tu perfil" in destino


def test_conectar_google_y_entrar_con_el(cliente, google):
    email, cab = _cuenta(cliente)
    google.update(email="otro-correo@gmail.com", sub=f"g-{uuid.uuid4().hex}")
    assert _google(cliente, cab, conectar=True).headers["location"] == "/#conectado=google"
    assert cliente.get("/suscripcion", headers=cab).json()["google_conectado"] is True
    # Ahora entra con esa cuenta de Google aunque el correo sea otro
    res = _google(cliente)
    assert res.headers["location"].startswith("/#sesion=")
    token = res.cookies["splitter_sesion"]
    assert cliente.get("/suscripcion", headers={"Authorization": f"Bearer {token}"}).json()["email"] == email
    # Se puede desconectar porque la cuenta tiene contraseña
    assert cliente.post("/auth/social/google/desconectar", headers=cab).status_code == 204
    assert _google(cliente).headers["location"].startswith("/#sesion=")  # crea una cuenta nueva con ese correo


def test_conectar_pide_sesion(cliente, google):
    res = cliente.get("/auth/social/google", params={"conectar": "1"}, follow_redirects=False)
    assert res.headers["location"].startswith("/#error=")


def test_entrar_con_google_y_dos_pasos(cliente, google):
    google.update(email=f"g2_{uuid.uuid4().hex[:8]}@gmail.com", sub=f"g-{uuid.uuid4().hex}")
    token = _google(cliente).cookies["splitter_sesion"]
    cab = {"Authorization": f"Bearer {token}"}
    secreto, _ = _activar(cliente, cab)

    destino = _google(cliente).headers["location"]
    assert destino.startswith("/#dos-pasos=")
    pendiente = destino.split("=", 1)[1]
    assert cliente.post("/auth/social/dos-pasos", json={"pendiente": pendiente, "codigo": "111111"}).status_code == 401
    dos_pasos._usados.clear()
    res = cliente.post("/auth/social/dos-pasos", json={"pendiente": pendiente, "codigo": dos_pasos.codigo_actual(secreto)})
    assert res.status_code == 200 and res.cookies["splitter_sesion"]
    assert cliente.post("/auth/social/dos-pasos", json={"pendiente": "1.2.3", "codigo": "1"}).status_code == 400


# ---------- Limpieza ----------
def test_limpieza_borra_sesiones_vencidas_y_trabajos_viejos(cliente):
    email, _ = _cuenta(cliente)
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email)
        repo_usuarios.crear_sesion(db, usuario.id, uuid.uuid4().hex, ahora_utc() - timedelta(days=1))
        viejo = uuid.uuid4().hex
        repo_trabajos.crear(db, id=viejo, usuario_id=usuario.id, nombre_original="x", tamano_bytes=1, preset="2stem",
                            pistas_pedidas="vocals", estado="completado",
                            creado_en=ahora_utc() - timedelta(days=config.DIAS_HISTORIAL_TRABAJOS + 1))
    resultado = limpiar_base()
    assert resultado["sesiones"] >= 1 and resultado["trabajos"] >= 1
    with SessionLocal() as db:
        assert db.get(Trabajo, viejo) is None
        assert db.query(Sesion).filter(Sesion.expira_en < ahora_utc()).count() == 0


def test_limites_se_guardan_en_disco(cliente):
    cliente.post("/auth/login", json={"email": "nadie@ejemplo.com", "password": "loquesea1"})
    time.sleep(0.05)
    assert (config.DATA_DIR / "limite_login_ip.json").exists()


# ---------- Planes: 15 audios en Gratis, ilimitados en Pro ----------
def test_planes_publicos(cliente):
    planes = {p["nombre"]: p for p in cliente.get("/suscripcion/planes").json()["planes"]}
    assert planes["gratis"]["trabajos_por_mes"] == 15 and planes["gratis"]["trabajos_ilimitados"] is False
    assert planes["pro"]["trabajos_por_mes"] is None and planes["pro"]["trabajos_ilimitados"] is True


def test_gratis_se_detiene_en_15_y_pro_no(cliente, buzon, monkeypatch):
    from app.services import cuotas
    email, cab = _cuenta(cliente)
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email)
        for _ in range(15):
            repo_trabajos.crear(db, id=uuid.uuid4().hex, usuario_id=usuario.id, nombre_original="x", tamano_bytes=1,
                                preset="2stem", pistas_pedidas="vocals", estado="completado")
        usuario_id = usuario.id
    cuenta = cliente.get("/suscripcion", headers=cab).json()
    assert cuenta["trabajos_usados"] == 15 and cuenta["trabajos_por_mes"] == 15
    with pytest.raises(Exception) as limite:
        cuotas.verificar_cantidad(usuario_id, "2stem")
    assert limite.value.status_code == 429

    _confirmar_correo(cliente, buzon)
    cliente.post("/suscripcion/pro", json={"marca": "Visa", "ultimos4": "4242"}, headers=cab)
    cuenta = cliente.get("/suscripcion", headers=cab).json()
    assert cuenta["plan"] == "pro" and cuenta["trabajos_ilimitados"] is True and cuenta["trabajos_por_mes"] is None
    cuotas.verificar_cantidad(usuario_id, "4stem")  # no lanza: ilimitados


# ---------- Facebook conectado y cuentas sin contraseña propia ----------
def _red(cliente, proveedor, cab=None, conectar=False):
    params = {"conectar": "1"} if conectar else {}
    inicio = cliente.get(f"/auth/social/{proveedor}", params=params, headers=cab or {}, follow_redirects=False)
    estado = parse_qs(urlparse(inicio.headers["location"]).query)["state"][0]
    return cliente.get(f"/auth/social/{proveedor}/regreso", params={"code": "c", "state": estado}, headers=cab or {}, follow_redirects=False)


def test_conectar_facebook_y_entrar_con_el(cliente, google):
    email, cab = _cuenta(cliente)
    google.update(email="correo-de-facebook@ejemplo.com", id=f"fb-{uuid.uuid4().hex}", sub="")
    assert _red(cliente, "facebook", cab, conectar=True).headers["location"] == "/#conectado=facebook"
    assert cliente.get("/suscripcion", headers=cab).json()["facebook_conectado"] is True
    res = _red(cliente, "facebook")
    token = res.cookies["splitter_sesion"]
    assert cliente.get("/suscripcion", headers={"Authorization": f"Bearer {token}"}).json()["email"] == email


def test_facebook_con_el_correo_de_otra_cuenta_no_entra(cliente, google):
    email, _ = _cuenta(cliente)
    google.update(email=email, id=f"fb-{uuid.uuid4().hex}", sub="")
    destino = unquote(_red(cliente, "facebook").headers["location"])
    assert destino.startswith("/#error=") and "conecta Facebook desde tu perfil" in destino


def test_cuenta_de_google_crea_su_contrasena(cliente, google):
    email = f"sinclave_{uuid.uuid4().hex[:8]}@gmail.com"
    google.update(email=email, sub=f"g-{uuid.uuid4().hex}")
    cab = {"Authorization": f"Bearer {_red(cliente, 'google').cookies['splitter_sesion']}"}
    assert cliente.get("/suscripcion", headers=cab).json()["tiene_password"] is False

    # Sin contraseña ni otra red, desconectar Google la dejaría sin entrada
    res = cliente.post("/auth/social/google/desconectar", headers=cab)
    assert res.status_code == 409 and "Crea una contraseña" in res.json()["detail"]

    # Crea su contraseña sin escribir una "actual"
    assert cliente.post("/auth/password", json={"actual": "", "nueva": "mi-clave-nueva-1"}, headers=cab).status_code == 204
    assert cliente.get("/suscripcion", headers=cab).json()["tiene_password"] is True
    assert cliente.post("/auth/login", json={"email": email, "password": "mi-clave-nueva-1"}).status_code == 200
    # Ahora sí puede desconectar Google, y para cambiarla ya pide la actual
    assert cliente.post("/auth/social/google/desconectar", headers=cab).status_code == 204
    assert cliente.post("/auth/password", json={"actual": "", "nueva": "otra-clave-22"}, headers=cab).status_code == 403


def test_borrar_cuenta_de_google_pide_el_correo_aunque_lo_haya_cambiado(cliente, google, buzon):
    google.update(email=f"borrar_{uuid.uuid4().hex[:8]}@gmail.com", sub=f"g-{uuid.uuid4().hex}")
    cab = {"Authorization": f"Bearer {_red(cliente, 'google').cookies['splitter_sesion']}"}
    nuevo = f"nuevo_{uuid.uuid4().hex[:8]}@ejemplo.com"
    cliente.patch("/auth/perfil", json={"email": nuevo}, headers=cab)
    _confirmar_correo(cliente, buzon)  # el cambio de correo ya no exige contraseña después
    assert cliente.request("DELETE", "/auth/cuenta", json={"confirmacion": "otro@x.com"}, headers=cab).status_code == 403
    assert cliente.request("DELETE", "/auth/cuenta", json={"confirmacion": nuevo}, headers=cab).status_code == 204
