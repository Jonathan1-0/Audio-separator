"""Datos del panel de administración: resumen, usuarios, trabajos y pagos."""
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from ..database import Base, SessionLocal, ahora_utc
from ..models.tablas import Pago, Plan, Suscripcion, Trabajo, Usuario
from ..repositories import usuarios as repo_usuarios
from .cuotas import plan_vigente

POR_PAGINA = 25
ESTADOS_USUARIO = {"activo", "suspendido"}


def _fecha(valor) -> Optional[str]:
    return f"{valor.isoformat()}Z" if valor else None


def es_admin(usuario_id: int) -> bool:
    with SessionLocal() as db:
        return plan_vigente(db, usuario_id) == "admin"


def resumen(cola: dict) -> dict:
    ahora = ahora_utc()
    hace_1, hace_7, hace_30 = ahora - timedelta(days=1), ahora - timedelta(days=7), ahora - timedelta(days=30)
    with SessionLocal() as db:
        contar = lambda *condiciones: db.scalar(select(func.count()).select_from(Usuario).where(*condiciones)) or 0  # noqa: E731
        vivos = Usuario.estado != "borrada"
        por_plan = dict(
            db.execute(
                select(Plan.nombre, func.count(Suscripcion.id))
                .join(Plan, Plan.id == Suscripcion.plan_id)
                .where(Suscripcion.estado == "activa", Suscripcion.fin_periodo > ahora)
                .group_by(Plan.nombre)
            ).all()
        )

        def trabajos(desde, *extra):
            return db.scalar(select(func.count()).select_from(Trabajo).where(Trabajo.creado_en >= desde, *extra)) or 0

        gpu_7 = db.scalar(select(func.coalesce(func.sum(Trabajo.gpu_seconds), 0)).where(Trabajo.creado_en >= hace_7))
        gpu_30 = db.scalar(select(func.coalesce(func.sum(Trabajo.gpu_seconds), 0)).where(Trabajo.creado_en >= hace_30))
        ingresos_30 = db.scalar(
            select(func.coalesce(func.sum(Pago.monto), 0)).where(Pago.estado == "pagado", Pago.fecha >= hace_30)
        )
        return {
            "usuarios": {
                "total": contar(vivos),
                "nuevos_7_dias": contar(vivos, Usuario.creado_en >= hace_7),
                "correo_confirmado": contar(vivos, Usuario.email_verificado.is_(True)),
                "suspendidos": contar(Usuario.estado == "suspendido"),
                "por_plan": por_plan,
            },
            "trabajos": {
                "ultimas_24_h": trabajos(hace_1),
                "ultimos_7_dias": trabajos(hace_7),
                "ultimos_30_dias": trabajos(hace_30),
                "errores_7_dias": trabajos(hace_7, Trabajo.estado == "error"),
                "minutos_gpu_7_dias": round(float(gpu_7 or 0) / 60, 1),
                "minutos_gpu_30_dias": round(float(gpu_30 or 0) / 60, 1),
            },
            "ingresos_30_dias": str(ingresos_30 or 0),
            "moneda": "MXN",
            "cola": cola,
        }


def usuarios(texto: str = "", pagina: int = 1) -> dict:
    pagina = max(1, pagina)
    with SessionLocal() as db:
        filtro = [Usuario.estado != "borrada"]
        if texto.strip():
            patron = f"%{texto.strip().lower()}%"
            filtro.append(or_(func.lower(Usuario.email).like(patron), func.lower(Usuario.nombre).like(patron)))
        total = db.scalar(select(func.count()).select_from(Usuario).where(*filtro)) or 0
        conteo = (
            select(Trabajo.usuario_id, func.count(Trabajo.id).label("n")).group_by(Trabajo.usuario_id).subquery()
        )
        filas = db.execute(
            select(Usuario, func.coalesce(conteo.c.n, 0))
            .outerjoin(conteo, conteo.c.usuario_id == Usuario.id)
            .where(*filtro)
            .order_by(Usuario.creado_en.desc(), Usuario.id.desc())
            .offset((pagina - 1) * POR_PAGINA)
            .limit(POR_PAGINA)
        ).all()
        lista = [
            {
                "id": u.id,
                "email": u.email,
                "nombre": u.nombre,
                "plan": plan_vigente(db, u.id),
                "estado": u.estado,
                "email_verificado": bool(u.email_verificado),
                "proveedor": u.proveedor,
                "creado_en": _fecha(u.creado_en),
                "trabajos": n,
            }
            for u, n in filas
        ]
        return {"total": total, "pagina": pagina, "por_pagina": POR_PAGINA, "usuarios": lista}


def cambiar_estado(admin_id: int, usuario_id: int, estado: str) -> dict:
    if estado not in ESTADOS_USUARIO:
        raise HTTPException(400, "El estado debe ser activo o suspendido.")
    if usuario_id == admin_id:
        raise HTTPException(400, "No puedes suspender tu propia cuenta.")
    with SessionLocal() as db:
        usuario = repo_usuarios.buscar_por_id(db, usuario_id)
        if usuario is None or usuario.estado == "borrada":
            raise HTTPException(404, "Ese usuario no existe.")
        usuario.estado = estado
        if estado == "suspendido":
            repo_usuarios.borrar_sesiones_de(db, usuario_id)  # sale de inmediato
        db.commit()
        return {"id": usuario.id, "estado": usuario.estado}


def trabajos(estado: str = "", pagina: int = 1) -> dict:
    pagina = max(1, pagina)
    with SessionLocal() as db:
        filtro = [Trabajo.estado == estado] if estado else []
        total = db.scalar(select(func.count()).select_from(Trabajo).where(*filtro)) or 0
        filas = db.execute(
            select(Trabajo, Usuario.email)
            .join(Usuario, Usuario.id == Trabajo.usuario_id)
            .where(*filtro)
            .order_by(Trabajo.creado_en.desc())
            .offset((pagina - 1) * POR_PAGINA)
            .limit(POR_PAGINA)
        ).all()
        lista = [
            {
                "id": t.id,
                "email": email,
                "nombre_original": t.nombre_original,
                "preset": t.preset,
                "estado": t.estado,
                "duracion_audio_seg": t.duracion_audio_seg,
                "gpu_seconds": t.gpu_seconds,
                "mensaje_error": t.mensaje_error,
                "creado_en": _fecha(t.creado_en),
                "terminado_en": _fecha(t.terminado_en),
            }
            for t, email in filas
        ]
        return {"total": total, "pagina": pagina, "por_pagina": POR_PAGINA, "trabajos": lista}


def pagos(pagina: int = 1) -> dict:
    pagina = max(1, pagina)
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(Pago)) or 0
        filas = db.execute(
            select(Pago, Usuario.email, Plan.nombre)
            .join(Suscripcion, Suscripcion.id == Pago.suscripcion_id)
            .join(Usuario, Usuario.id == Suscripcion.usuario_id)
            .join(Plan, Plan.id == Suscripcion.plan_id)
            .order_by(Pago.fecha.desc())
            .offset((pagina - 1) * POR_PAGINA)
            .limit(POR_PAGINA)
        ).all()
        lista = [
            {
                "id": p.id,
                "email": email,
                "plan": plan,
                "monto": str(p.monto),
                "moneda": p.moneda,
                "estado": p.estado,
                "id_transaccion": p.id_transaccion,
                "fecha": _fecha(p.fecha),
            }
            for p, email, plan in filas
        ]
        return {"total": total, "pagina": pagina, "por_pagina": POR_PAGINA, "pagos": lista}


# Vista de la base: tablas completas en solo lectura, sin columnas secretas
OCULTAS = {"password_hash", "totp_secreto", "token", "token_pasarela"}


def _valor(columna: str, valor):
    if columna in OCULTAS and valor is not None:
        return "••••"
    if valor is None or isinstance(valor, (bool, int, float)):
        return valor
    return f"{valor.isoformat()}Z" if hasattr(valor, "isoformat") else str(valor)


def base_tablas() -> list[dict]:
    with SessionLocal() as db:
        return [
            {"nombre": nombre, "filas": db.scalar(select(func.count()).select_from(tabla)) or 0}
            for nombre, tabla in Base.metadata.tables.items()
        ]


def base_filas(nombre: str, pagina: int = 1) -> dict:
    tabla = Base.metadata.tables.get(nombre)
    if tabla is None:
        raise HTTPException(404, "Esa tabla no existe.")
    pagina = max(1, pagina)
    columnas = [c.name for c in tabla.columns]
    orden = [c.desc() for c in tabla.primary_key.columns]
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(tabla)) or 0
        filas = db.execute(
            select(tabla).order_by(*orden).offset((pagina - 1) * POR_PAGINA).limit(POR_PAGINA)
        ).mappings().all()
    return {
        "tabla": nombre,
        "columnas": columnas,
        "filas": [[_valor(c, f[c]) for c in columnas] for f in filas],
        "total": total,
        "pagina": pagina,
        "por_pagina": POR_PAGINA,
    }
