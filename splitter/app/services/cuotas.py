"""Periodo vigente y límites del plan del usuario."""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import config
from ..database import SessionLocal, ahora_utc
from ..models.tablas import Suscripcion
from ..repositories import suscripciones as repo_suscripciones
from ..repositories import trabajos as repo_trabajos


def crear_periodo_gratis(db: Session, usuario_id: int) -> Suscripcion:
    """Periodo nuevo del plan gratis; quien llama hace el commit."""
    plan = repo_suscripciones.buscar_plan(db, "gratis")
    inicio = ahora_utc()
    fin = inicio + timedelta(days=config.DIAS_PERIODO)
    return repo_suscripciones.crear_suscripcion(db, usuario_id, plan, inicio, fin)


def suscripcion_vigente(db: Session, usuario_id: int) -> Suscripcion:
    """Si la activa ya venció, el usuario pasa a un periodo gratis nuevo."""
    suscripcion = repo_suscripciones.buscar_activa(db, usuario_id)
    if suscripcion is not None and suscripcion.fin_periodo > ahora_utc():
        return suscripcion
    if suscripcion is not None:
        suscripcion.estado = "vencida"
    nueva = crear_periodo_gratis(db, usuario_id)
    db.commit()
    return nueva


def _revisar_cantidad(db: Session, suscripcion: Suscripcion) -> None:
    usados = repo_trabajos.contar_en_periodo(
        db, suscripcion.usuario_id, suscripcion.inicio_periodo, suscripcion.fin_periodo
    )
    limite = suscripcion.plan.trabajos_por_mes
    if usados >= limite:
        raise HTTPException(
            429,
            f"Ya usaste tus {limite} trabajos de este periodo del plan {suscripcion.plan.nombre}. "
            f"Se renuevan el {suscripcion.fin_periodo:%d/%m/%Y}.",
        )


def verificar_cantidad(usuario_id: int) -> None:
    with SessionLocal() as db:
        _revisar_cantidad(db, suscripcion_vigente(db, usuario_id))


def verificar_audio(usuario_id: int, segundos: float) -> None:
    """Con el audio ya subido: duración, y otra vez la cantidad por si hubo subidas a la vez."""
    with SessionLocal() as db:
        suscripcion = suscripcion_vigente(db, usuario_id)
        _revisar_cantidad(db, suscripcion)
        limite = suscripcion.plan.minutos_max_audio
        if segundos > limite * 60:
            raise HTTPException(
                413,
                f"El audio dura {int(segundos // 60)}:{int(segundos % 60):02d} y tu plan "
                f"{suscripcion.plan.nombre} permite hasta {limite} min.",
            )
