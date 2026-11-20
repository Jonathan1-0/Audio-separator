"""Cancelar Pro al final del periodo, verificación en dos pasos, conectar Google y limpieza."""
from .conftest import registrar
import re
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from app import config
from app.database import SessionLocal, ahora_utc
from app.mantenimiento import limpiar_base
from app.models.tablas import Sesion, Trabajo
from app.repositories import trabajos as repo_trabajos
from app.repositories import usuarios as repo_usuarios
from app.services import correo, social

PASSWORD = "clave-segura-1"


@pytest.fixture
def buzon(monkeypatch):
    recibidos = []
    monkeypatch.setattr(correo, "enviar", lambda destino, asunto, texto, cuerpo_html=None: recibidos.append((destino, asunto, texto)))
    return recibidos


def _codigo(buzon) -> str:
    """El código de 6 dígitos del último correo de verificación."""
    asunto = next(a for _, a, _ in reversed(buzon) if a.startswith("Tu código de Splitter"))
    return re.search(r"(\d{6})$", asunto).group(1)


def _cuenta(cliente, buzon=None):
    email = f"segura_{uuid.uuid4().hex[:10]}@example.com"
    registrar(cliente, json={"email": email, "nombre": "Segura", "password": PASSWORD})
    res = cliente.post("/auth/login", json={"email": email, "password": PASSWORD})
    return email, {"Authorization": f"Bearer {res.cookies['splitter_sesion']}"}


def _confirmar_correo(cliente, buzon):
    """Abre el último enlace de confirmación (cambio de correo), si llegó alguno."""
    for _, _, texto in reversed(buzon):
        encontrado = re.search(r"#verificar=(\S+)", texto)
        if encontrado:
            cliente.post("/auth/verificar", json={"codigo": encontrado.group(1)})
            return


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
        # El periodo entero queda en el pasado (la base exige que el fin sea después del inicio)
        activa.inicio_periodo = ahora_utc() - timedelta(days=31)
        activa.fin_periodo = ahora_utc() - timedelta(minutes=1)
        db.commit()
    assert cliente.get("/suscripcion", headers=cab).json()["plan"] == "gratis"


# ---------- Registro con código por correo ----------
def _registrar_sin_confirmar(cliente, email, password=PASSWORD):
    return cliente.post("/auth/registro", json={"email": email, "nombre": "Nueva", "password": password})


def test_registro_pide_el_codigo_del_correo(cliente, buzon):
    email = f"nueva_{uuid.uuid4().hex[:8]}@example.com"
    res = _registrar_sin_confirmar(cliente, email)
    assert res.status_code == 201 and res.json()["pendiente"] and "Te enviamos un código" in res.json()["mensaje"]
    assert buzon[-1][0] == email

    # Sin confirmar no entra: se le manda otro código
    sin_confirmar = cliente.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert sin_confirmar.status_code == 403 and sin_confirmar.headers["X-Splitter-Confirmar"] == "requerido"
    pendiente = sin_confirmar.headers["X-Splitter-Pendiente"]

    assert cliente.post("/auth/registro/confirmar", json={"pendiente": pendiente, "codigo": "000000"}).status_code == 400
    bueno = cliente.post("/auth/registro/confirmar", json={"pendiente": pendiente, "codigo": _codigo(buzon)})
    assert bueno.status_code == 200 and bueno.cookies["splitter_sesion"]
    cab = {"Authorization": f"Bearer {bueno.cookies['splitter_sesion']}"}
    assert cliente.get("/suscripcion", headers=cab).json()["email_verificado"] is True
    # Ya confirmada, entra sin código
    assert cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    # Y el correo ya no se puede volver a registrar
    assert _registrar_sin_confirmar(cliente, email).status_code == 409


def test_registro_sin_confirmar_se_puede_rehacer(cliente, buzon):
    email = f"rehacer_{uuid.uuid4().hex[:8]}@example.com"
    _registrar_sin_confirmar(cliente, email, "clave-de-otro-1")
    res = _registrar_sin_confirmar(cliente, email, "mi-clave-buena-1")
    assert res.status_code == 201
    cliente.post("/auth/registro/confirmar", json={"pendiente": res.json()["pendiente"], "codigo": _codigo(buzon)})
    assert cliente.post("/auth/login", json={"email": email, "password": "mi-clave-buena-1"}).status_code == 200
    assert cliente.post("/auth/login", json={"email": email, "password": "clave-de-otro-1"}).status_code == 401


def test_reenviar_codigo(cliente, buzon):
    email = f"reenvio_{uuid.uuid4().hex[:8]}@example.com"
    _registrar_sin_confirmar(cliente, email)
    antes = len(buzon)
    res = cliente.post("/auth/registro/reenviar", json={"email": email})
    assert res.status_code == 200 and res.json()["pendiente"] and len(buzon) == antes + 1
    assert cliente.post("/auth/registro/reenviar", json={"email": "nadie@example.com"}).status_code == 404


def test_codigo_de_otro_registro_no_sirve(cliente, buzon):
    _registrar_sin_confirmar(cliente, f"a_{uuid.uuid4().hex[:8]}@example.com")
    codigo_a = _codigo(buzon)
    b = _registrar_sin_confirmar(cliente, f"b_{uuid.uuid4().hex[:8]}@example.com").json()
    assert cliente.post("/auth/registro/confirmar", json={"pendiente": b["pendiente"], "codigo": codigo_a}).status_code == 400


def test_demasiados_codigos_incorrectos(cliente, buzon):
    pendiente = _registrar_sin_confirmar(cliente, f"bloq_{uuid.uuid4().hex[:8]}@example.com").json()["pendiente"]
    for _ in range(5):
        cliente.post("/auth/registro/confirmar", json={"pendiente": pendiente, "codigo": "111111"})
    res = cliente.post("/auth/registro/confirmar", json={"pendiente": pendiente, "codigo": _codigo(buzon)})
    assert res.status_code == 429


def test_login_ya_no_pide_codigo(cliente, buzon):
    email, _ = _cuenta(cliente)
    antes = len(buzon)
    assert cliente.post("/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200
    assert len(buzon) == antes  # no se envió ningún código


def _admin(cliente):
    token = cliente.post("/auth/login", json={"email": "admin@pruebas.com", "password": "admin-pruebas-1"}).cookies["splitter_sesion"]
    return {"Authorization": f"Bearer {token}"}


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


def test_google_toma_un_registro_sin_confirmar(cliente, google, buzon):
    email = f"pend_{uuid.uuid4().hex[:8]}@gmail.com"
    _registrar_sin_confirmar(cliente, email, "clave-de-alguien-1")
    google.update(email=email, sub=f"g-{uuid.uuid4().hex}")
    res = _google(cliente)
    assert res.headers["location"].startswith("/#sesion=")
    cuenta = cliente.get("/suscripcion", headers={"Authorization": f"Bearer {res.cookies['splitter_sesion']}"}).json()
    assert cuenta["email"] == email and cuenta["tiene_password"] is False and cuenta["google_conectado"] is True
    # La contraseña que había puesto quien no confirmó ya no sirve
    assert cliente.post("/auth/login", json={"email": email, "password": "clave-de-alguien-1"}).status_code == 401


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
    pendiente = f"vieja_{uuid.uuid4().hex[:8]}@example.com"
    cliente.post("/auth/registro", json={"email": pendiente, "nombre": "Vieja", "password": PASSWORD})
    with SessionLocal() as db:
        repo_usuarios.buscar_por_email(db, pendiente).creado_en = ahora_utc() - timedelta(days=8)
        db.commit()
    resultado = limpiar_base()
    assert resultado["sesiones"] >= 1 and resultado["trabajos"] >= 1 and resultado["sin_confirmar"] >= 1
    with SessionLocal() as db:
        assert repo_usuarios.buscar_por_email(db, pendiente) is None
    with SessionLocal() as db:
        assert db.get(Trabajo, viejo) is None
        assert db.query(Sesion).filter(Sesion.expira_en < ahora_utc()).count() == 0


def test_limites_se_guardan_en_disco(cliente):
    cliente.post("/auth/login", json={"email": "nadie@example.com", "password": "loquesea1"})
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
    google.update(email="correo-de-facebook@example.com", id=f"fb-{uuid.uuid4().hex}", sub="")
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
    nuevo = f"nuevo_{uuid.uuid4().hex[:8]}@example.com"
    cliente.patch("/auth/perfil", json={"email": nuevo}, headers=cab)
    _confirmar_correo(cliente, buzon)  # el cambio de correo ya no exige contraseña después
    assert cliente.request("DELETE", "/auth/cuenta", json={"confirmacion": "otro@x.com"}, headers=cab).status_code == 403
    assert cliente.request("DELETE", "/auth/cuenta", json={"confirmacion": nuevo}, headers=cab).status_code == 204
