"""Registro, inicio y cierre de sesión."""
import secrets
from datetime import timedelta

import bcrypt
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from .. import config
from ..database import SessionLocal, ahora_utc
from ..models.tablas import Usuario
from ..ratelimit import RateLimiter
from ..repositories import usuarios as repo_usuarios
from .cuotas import crear_periodo_gratis

# Se guardan en DATA_DIR: reiniciar el servidor no borra los intentos
_login_por_ip = RateLimiter(config.LOGIN_POR_IP, 15 * 60, config.DATA_DIR / "limite_login_ip.json")
_fallos_por_cuenta = RateLimiter(config.LOGIN_FALLOS_POR_CUENTA, 15 * 60, config.DATA_DIR / "limite_login_cuenta.json")
_registros_por_ip = RateLimiter(config.REGISTROS_POR_IP, 3600, config.DATA_DIR / "limite_registros.json")
_HASH_FALSO = bcrypt.hashpw(b"no-es-una-cuenta", bcrypt.gensalt()).decode()


def _minutos(segundos: float) -> str:
    minutos = max(1, round(segundos / 60))
    return f"{minutos} minuto{'s' if minutos != 1 else ''}"

MAX_BYTES_PASSWORD = 72  # límite de bcrypt


def validar_email(email: str) -> None:
    if "@" not in email or "." not in email.rsplit("@", 1)[-1] or len(email) > 255 or " " in email:
        raise HTTPException(400, "El email no es válido.")


def _validar_datos(email: str, nombre: str, password: str) -> None:
    validar_email(email)
    if not nombre or len(nombre) > 100:
        raise HTTPException(400, "El nombre debe tener entre 1 y 100 caracteres.")
    validar_password(password)


def registrar(email: str, nombre: str, password: str, ip: str = "") -> Usuario:
    """Crea la cuenta "pendiente": se activa al escribir el código que llega al correo.

    Si ya había un registro pendiente con ese correo (nunca se confirmó), se reemplaza:
    así nadie puede apartar un correo ajeno registrándose sin confirmarlo.
    """
    email, nombre = email.strip().lower(), nombre.strip()
    _validar_datos(email, nombre, password)
    espera = _registros_por_ip.acquire(ip)
    if espera:
        raise HTTPException(429, f"Se crearon demasiadas cuentas desde tu red. Intenta en {_minutos(espera)}.")
    password_hash = crear_hash(password)
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email)
        if usuario is not None and usuario.estado != "pendiente":
            raise HTTPException(409, "Ya existe una cuenta con ese email.")
        try:
            if usuario is None:
                usuario = repo_usuarios.crear(db, email, nombre, password_hash)
                crear_periodo_gratis(db, usuario.id)
            else:
                usuario.nombre, usuario.password_hash = nombre, password_hash
            usuario.estado = "pendiente"
            db.commit()
        except IntegrityError:  # correo repetido
            db.rollback()
            raise HTTPException(409, "Ya existe una cuenta con ese email.")
    return usuario


CABECERA_CONFIRMAR = "X-Splitter-Confirmar"


def password_correcta(usuario: Usuario, password: str) -> bool:
    return len(password.encode()) <= MAX_BYTES_PASSWORD and bcrypt.checkpw(password.encode(), usuario.password_hash.encode())


def pedir_confirmacion(usuario: Usuario) -> dict:
    """Envía el código para confirmar la cuenta y lo que la página necesita para pedirlo."""
    from . import codigos  # aquí: codigos usa este módulo de forma indirecta

    oculto = codigos.correo_oculto(usuario.email)
    return {
        "pendiente": codigos.enviar_codigo(usuario),
        "correo": oculto,
        "mensaje": f"Te enviamos un código de 6 dígitos a {oculto}.",
    }


def confirmar_registro(pendiente: str, codigo: str) -> dict:
    """Con el código correcto la cuenta queda activa y se abre la sesión."""
    from . import codigos

    inicio = (pendiente or "").split(".", 1)[0]
    if not inicio.isdigit():
        raise HTTPException(400, "Vuelve a crear tu cuenta: el registro no es válido.")
    usuario_id = int(inicio)
    if not codigos.verificar(usuario_id, pendiente, codigo):
        raise HTTPException(400, "El código no es correcto.")
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if usuario is None or usuario.estado not in ("pendiente", "activo"):
            raise HTTPException(400, "Vuelve a crear tu cuenta: el registro no es válido.")
        usuario.estado = "activo"
        usuario.email_verificado = True
        datos = abrir_sesion(db, usuario)
        db.commit()
    return datos


def reenviar_confirmacion(email: str) -> dict:
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email.strip().lower())
    if usuario is None or usuario.estado != "pendiente":
        raise HTTPException(404, "No hay una cuenta por confirmar con ese correo.")
    return pedir_confirmacion(usuario)


def login(email: str, password: str, ip: str = "") -> dict:
    email = email.strip().lower()
    espera = _login_por_ip.acquire(ip) or _fallos_por_cuenta.espera(email)
    if espera:
        raise HTTPException(429, f"Demasiados intentos. Espera {_minutos(espera)} e intenta de nuevo.",
                            headers={"Retry-After": str(int(espera) + 1)})
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_email(db, email)
        # Sin cuenta también se calcula un hash: así no se nota por el tiempo si el correo existe
        guardado = usuario.password_hash if usuario is not None else _HASH_FALSO
        correcta = len(password.encode()) <= MAX_BYTES_PASSWORD and bcrypt.checkpw(password.encode(), guardado.encode())
        correcta = correcta and usuario is not None
        if not correcta:
            _fallos_por_cuenta.acquire(email)
            raise HTTPException(401, "Email o contraseña incorrectos.")
        _fallos_por_cuenta.limpiar(email)
        if usuario.estado == "pendiente":
            # Se registró pero no escribió el código: se le manda otro para terminar
            datos = pedir_confirmacion(usuario)
            raise HTTPException(
                403,
                f"Confirma tu correo para terminar de crear tu cuenta. {datos['mensaje']}",
                headers={CABECERA_CONFIRMAR: "requerido", "X-Splitter-Pendiente": datos["pendiente"]},
            )
        if usuario.estado != "activo":
            raise HTTPException(403, "Tu cuenta está suspendida.")
        datos = abrir_sesion(db, usuario)
        db.commit()
    return datos


def abrir_sesion(db, usuario: Usuario) -> dict:
    """Crea el token de una sesión nueva."""
    ahora = ahora_utc()
    repo_usuarios.borrar_sesiones_vencidas(db, usuario.id, ahora)
    token = secrets.token_hex(32)
    expira_en = ahora + timedelta(days=config.DIAS_SESION)
    repo_usuarios.crear_sesion(db, usuario.id, token, expira_en)
    # "token" va solo en la cookie HttpOnly; "sesion" es un identificador para la página que no sirve para entrar
    return {"token": token, "sesion": secrets.token_hex(8), "expira_en": f"{expira_en.isoformat()}Z", "nombre": usuario.nombre}


def publico(datos: dict) -> dict:
    """Lo que ve la página de una sesión nueva (sin el token)."""
    return {k: v for k, v in datos.items() if k != "token"}


def validar_password(password: str) -> None:
    if len(password) < 8 or len(password.encode()) > MAX_BYTES_PASSWORD:
        raise HTTPException(400, "La contraseña debe tener entre 8 y 72 caracteres.")


def crear_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def logout(token: str) -> None:
    with SessionLocal() as db:
        repo_usuarios.borrar_sesion(db, token)
        db.commit()


def usuario_por_token(token: str) -> Usuario:
    """Devuelve el usuario del token, o 401."""
    with SessionLocal() as db:
        sesion = repo_usuarios.buscar_sesion(db, token)
        if sesion is None or sesion.expira_en <= ahora_utc():
            raise HTTPException(401, "Tu sesión no es válida. Inicia sesión de nuevo.")
        usuario = repo_usuarios.buscar_por_id(db, sesion.usuario_id)
    if usuario.estado != "activo":
        raise HTTPException(403, "Tu cuenta está suspendida.")
    return usuario
