"""Consultas de trabajos y resultados."""
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models.tablas import Resultado, Trabajo


def crear(db: Session, **datos) -> None:
    """Guarda un trabajo nuevo."""
    db.add(Trabajo(**datos))
    db.commit()


def obtener(db: Session, trabajo_id: str) -> Optional[Trabajo]:
    """Busca un trabajo, junto con sus resultados."""
    consulta = select(Trabajo).options(selectinload(Trabajo.resultados)).where(Trabajo.id == trabajo_id)
    return db.scalar(consulta)


def borrar(db: Session, trabajo_id: str) -> None:
    """Quita un trabajo que no se pudo poner en la cola."""
    trabajo = db.get(Trabajo, trabajo_id)
    if trabajo is not None:
        db.delete(trabajo)
        db.commit()


def actualizar_estado(db: Session, trabajo_id: str, estado: str, progreso: int) -> None:
    """Cambia el estado y el progreso."""
    trabajo = db.get(Trabajo, trabajo_id)
    if trabajo is not None:
        trabajo.estado, trabajo.progreso = estado, progreso
        db.commit()


def terminar(
    db: Session,
    trabajo_id: str,
    estado: str,
    progreso: int,
    terminado_en: datetime,
    mensaje_error: Optional[str],
    gpu_seconds: Optional[float],
    pistas: Dict[str, str],
    expira_en: datetime,
) -> None:
    """Guarda el final del trabajo y una fila en resultados por cada pista."""
    trabajo = db.get(Trabajo, trabajo_id)
    if trabajo is None:
        return
    trabajo.estado, trabajo.progreso = estado, progreso
    trabajo.terminado_en, trabajo.mensaje_error, trabajo.gpu_seconds = terminado_en, mensaje_error, gpu_seconds
    for stem, ruta in pistas.items():
        db.add(Resultado(trabajo_id=trabajo_id, stem=stem, ruta_archivo=ruta, expira_en=expira_en))
    db.commit()


def marcar_borrado(db: Session, trabajo_id: str, ahora: datetime, cancelado: bool) -> None:
    """Conserva la fila para el historial y las cuotas, pero sus archivos ya no están."""
    trabajo = obtener(db, trabajo_id)
    if trabajo is None:
        return
    if cancelado:
        trabajo.estado, trabajo.mensaje_error, trabajo.terminado_en = "error", "Cancelado por el usuario", ahora
    for resultado in trabajo.resultados:
        resultado.expira_en = min(resultado.expira_en, ahora)
    db.commit()


def listar_pendientes(db: Session) -> List[Trabajo]:
    """Trabajos que quedaron sin terminar, del más antiguo al más nuevo."""
    consulta = (
        select(Trabajo).where(Trabajo.estado.in_(("en_cola", "procesando"))).order_by(Trabajo.creado_en)
    )
    return list(db.scalars(consulta))


def listar_por_usuario(db: Session, usuario_id: int) -> List[Trabajo]:
    """Historial del usuario, del más nuevo al más antiguo."""
    consulta = (
        select(Trabajo)
        .options(selectinload(Trabajo.resultados))
        .where(Trabajo.usuario_id == usuario_id)
        .order_by(Trabajo.creado_en.desc())
    )
    return list(db.scalars(consulta))


def contar_en_periodo(db: Session, usuario_id: int, inicio: datetime, fin: datetime) -> int:
    """Cuenta los trabajos del usuario dentro del periodo."""
    consulta = select(func.count(Trabajo.id)).where(
        Trabajo.usuario_id == usuario_id, Trabajo.creado_en >= inicio, Trabajo.creado_en < fin
    )
    return db.scalar(consulta) or 0
