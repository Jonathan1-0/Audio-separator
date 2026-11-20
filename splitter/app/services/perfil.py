"""Perfil: nombre, correo, teléfono, foto y contraseña."""
import re
import secrets
from pathlib import Path
from typing import Callable, Optional

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from .. import config
from ..database import SessionLocal
from ..models.tablas import Trabajo, Usuario
from ..repositories import usuarios as repo_usuarios
from . import auth, correo, verificacion

CARPETA_FOTOS = config.DATA_DIR / "fotos"
# Primeros bytes de cada tipo de imagen: no se confía en lo que diga el navegador
_FIRMAS_IMAGEN = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)
NOMBRE_FOTO = re.compile(r"^\d+_[0-9a-f]{16}\.(png|jpg|webp)$")
TIPOS_FOTO = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def foto_url(usuario: Usuario) -> Optional[str]:
    return f"/auth/fotos/{usuario.foto}" if usuario.foto else None


def datos_publicos(usuario: Usuario) -> dict:
    return {
        "nombre": usuario.nombre,
        "email": usuario.email,
        "telefono": usuario.telefono,
        "foto_url": foto_url(usuario),
        "email_verificado": bool(usuario.email_verificado),
    }


def _validar_telefono(valor: str) -> Optional[str]:
    if not valor:
        return None  # vacío lo borra
    if len(valor) > 20 or not re.fullmatch(r"\+?[\d\s().-]+", valor):
        raise HTTPException(400, "Usa solo números, espacios y el signo + al inicio.")
    if not 7 <= len(re.sub(r"\D", "", valor)) <= 15:
        raise HTTPException(400, "El teléfono debe tener entre 7 y 15 dígitos.")
    return valor


def cambiar_dato(usuario_id: int, campos: dict, base: str = "") -> dict:
    """Cambia un solo dato por llamada: nombre, email o telefono.

    El correo no cambia aquí: se manda un enlace al correo nuevo y cambia al abrirlo.
    """
    campos = {k: v for k, v in campos.items() if v is not None}
    if len(campos) != 1:
        raise HTTPException(400, "Manda un solo dato: nombre, email o telefono.")
    campo, valor = next(iter(campos.items()))
    valor = valor.strip()

    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if campo == "nombre":
            if not valor or len(valor) > 100:
                raise HTTPException(400, "El nombre debe tener entre 1 y 100 caracteres.")
            usuario.nombre = valor
        elif campo == "email":
            valor = valor.lower()
            auth.validar_email(valor)
            if valor != usuario.email:
                otro = repo_usuarios.buscar_por_email(db, valor)
                if otro is not None:
                    raise HTTPException(409, "Ya existe una cuenta con ese correo.")
                verificacion.pedir_cambio(usuario, valor, base)
                datos = datos_publicos(usuario)
                datos["email_pendiente"] = valor
                datos["mensaje"] = f"Te enviamos un enlace a {valor}. Tu correo cambia cuando lo abras."
                return datos
        else:
            usuario.telefono = _validar_telefono(valor)
        try:
            db.commit()
        except IntegrityError:  # el mismo correo guardado al mismo tiempo
            db.rollback()
            raise HTTPException(409, "Ya existe una cuenta con ese correo.")
        return datos_publicos(usuario)


def _tipo_imagen(contenido: bytes) -> Optional[str]:
    for firma, tipo in _FIRMAS_IMAGEN:
        if contenido.startswith(firma):
            return tipo
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "webp"
    return None


def guardar_foto(usuario_id: int, contenido: bytes) -> dict:
    if not contenido:
        raise HTTPException(400, "Elige una foto.")
    if len(contenido) > config.MAX_FOTO_BYTES:
        raise HTTPException(413, "La foto debe pesar menos de 2 MB.")
    tipo = _tipo_imagen(contenido)
    if tipo is None:
        raise HTTPException(415, "La foto debe ser PNG, JPG o WebP.")

    CARPETA_FOTOS.mkdir(parents=True, exist_ok=True)
    nombre = f"{usuario_id}_{secrets.token_hex(8)}.{tipo}"
    (CARPETA_FOTOS / nombre).write_bytes(contenido)
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        anterior = usuario.foto
        usuario.foto = nombre
        db.commit()
    if anterior:
        (CARPETA_FOTOS / anterior).unlink(missing_ok=True)
    return {"foto_url": f"/auth/fotos/{nombre}"}


def ruta_foto(nombre: str) -> Path:
    ruta = CARPETA_FOTOS / nombre
    if not NOMBRE_FOTO.match(nombre) or not ruta.is_file():
        raise HTTPException(404, "Esa foto no existe.")
    return ruta


def cambiar_password(usuario_id: int, token: str, actual: str, nueva: str) -> None:
    """Pide la actual, guarda la nueva y cierra las otras sesiones."""
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        # Cuentas de Google o Facebook sin contraseña propia: la crean sin escribir una "actual"
        if usuario.tiene_password:
            if not auth.password_correcta(usuario, actual):
                raise HTTPException(403, "La contraseña actual no es correcta.")
            if nueva == actual:
                raise HTTPException(400, "La nueva contraseña debe ser distinta de la actual.")
        auth.validar_password(nueva)
        creada = not usuario.tiene_password
        repo_usuarios.cambiar_password(db, usuario, auth.crear_hash(nueva))
        usuario.tiene_password = True
        repo_usuarios.borrar_otras_sesiones(db, usuario_id, token)
        db.commit()
    correo.enviar_aviso(
        usuario.email,
        "Creaste tu contraseña de Splitter" if creada else "Cambiaste tu contraseña de Splitter",
        f"Hola, {usuario.nombre}",
        ["Ahora también puedes entrar con tu correo y tu contraseña. Cerramos tus otras sesiones." if creada
         else "La contraseña de tu cuenta de Splitter se cambió y cerramos tus otras sesiones."],
        pie="Si no fuiste tú, usa «¿Olvidaste tu contraseña?» en la página para recuperar tu cuenta.",
    )


def cerrar_todas(usuario_id: int) -> None:
    """Cierra la sesión en todos los dispositivos, también en este."""
    with SessionLocal() as db:
        repo_usuarios.borrar_sesiones_de(db, usuario_id)
        db.commit()


def borrar_cuenta(usuario_id: int, password: str, confirmacion: str, borrar_trabajo: Callable[[str], object]) -> None:
    """Borra los audios y los datos personales. Los pagos se conservan (sin datos de la persona)
    porque son registros contables; la fila del usuario queda anónima."""
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if usuario.tiene_password:
            if not auth.password_correcta(usuario, password):
                raise HTTPException(403, "La contraseña no es correcta.")
        elif confirmacion.strip().lower() != usuario.email:
            raise HTTPException(403, "Escribe tu correo para confirmar.")
        ids = list(db.scalars(select(Trabajo.id).where(Trabajo.usuario_id == usuario_id)))
        email, nombre, foto = usuario.email, usuario.nombre, usuario.foto

    for job_id in ids:
        borrar_trabajo(job_id)  # para la separación si sigue y borra los archivos

    with SessionLocal() as db:
        if ids:
            db.execute(delete(Trabajo).where(Trabajo.id.in_(ids)))
        repo_usuarios.borrar_sesiones_de(db, usuario_id)
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        usuario.email = f"borrada-{usuario_id}-{secrets.token_hex(4)}@splitter.invalid"
        usuario.nombre = "Cuenta borrada"
        usuario.telefono = None
        usuario.foto = None
        usuario.google_id = None
        usuario.facebook_id = None
        usuario.totp_secreto = None
        usuario.totp_activo = False
        usuario.totp_respaldo = None
        usuario.password_hash = auth.crear_hash(secrets.token_urlsafe(32))
        usuario.estado = "borrada"
        usuario.email_verificado = False
        db.commit()
    if foto:
        (CARPETA_FOTOS / foto).unlink(missing_ok=True)
    correo.enviar_aviso(
        email,
        "Borraste tu cuenta de Splitter",
        f"Adiós, {nombre}",
        ["Borramos tu cuenta, tus audios y tus datos personales. Si algún día quieres volver, "
         "puedes crear una cuenta nueva con este mismo correo."],
    )
