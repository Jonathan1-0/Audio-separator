"""Periodo vigente y límites del plan del usuario."""
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import config
from ..database import SessionLocal, ahora_utc
from ..models.tablas import Suscripcion
from ..repositories import suscripciones as repo_suscripciones
from ..repositories import trabajos as repo_trabajos


try:
    _ZONA = ZoneInfo(config.ZONA_HORARIA)
except (ZoneInfoNotFoundError, ValueError):
    _ZONA = timezone(timedelta(hours=-6))  # Ciudad de México, sin horario de verano


def fin_de_periodo(inicio: datetime) -> datetime:
    """Fin del periodo: el día de renovación a la HORA_RENOVACION local (en UTC, sin zona)."""
    local = inicio.replace(tzinfo=timezone.utc).astimezone(_ZONA)
    dia = (local + timedelta(days=config.DIAS_PERIODO)).date()
    fin = datetime.combine(dia, time(config.HORA_RENOVACION), tzinfo=_ZONA)
    return fin.astimezone(timezone.utc).replace(tzinfo=None)


def crear_periodo_gratis(db: Session, usuario_id: int, plan_nombre: str = "gratis") -> Suscripcion:
    """Crea un periodo nuevo del plan gratis."""
    plan = repo_suscripciones.buscar_plan(db, plan_nombre)
    inicio = ahora_utc()
    return repo_suscripciones.crear_suscripcion(db, usuario_id, plan, inicio, fin_de_periodo(inicio))


def suscripcion_vigente(db: Session, usuario_id: int) -> Suscripcion:
    """Suscripción vigente; si ya venció, pasa a gratis."""
    suscripcion = repo_suscripciones.buscar_activa(db, usuario_id)
    if suscripcion is not None and suscripcion.fin_periodo > ahora_utc():
        return suscripcion
    siguiente = "gratis"
    if suscripcion is not None:
        suscripcion.estado = "vencida"
        if suscripcion.plan.nombre == "admin":
            siguiente = "admin"
    nueva = crear_periodo_gratis(db, usuario_id, siguiente)
    db.commit()
    return nueva


def plan_vigente(db: Session, usuario_id: int) -> str:
    return suscripcion_vigente(db, usuario_id).plan.nombre


PLANES_PRIORITARIOS = {"pro", "admin"}


def prioridad(usuario_id: Optional[int]) -> int:
    """0 = sus trabajos pasan primero en la cola (Pro y admin); 1 = los demás."""
    if usuario_id is None:
        return 1
    with SessionLocal() as db:
        return 0 if plan_vigente(db, usuario_id) in PLANES_PRIORITARIOS else 1


def minutos_guardado(plan: str) -> int:
    """Minutos que se guardan las pistas en ese plan."""
    return config.MINUTOS_GUARDADO_PLAN.get(plan, config.JOB_TTL_MINUTES)


def limite_trabajos(plan) -> Optional[int]:
    """Audios por periodo del plan, o None si son ilimitados (0 en la base)."""
    return plan.trabajos_por_mes if plan.trabajos_por_mes and plan.trabajos_por_mes > 0 else None


def _revisar_cantidad(db: Session, suscripcion: Suscripcion) -> None:
    if limite_trabajos(suscripcion.plan) is None:
        return  # ilimitados: ni se cuentan
    usados = repo_trabajos.contar_en_periodo(
        db, suscripcion.usuario_id, suscripcion.inicio_periodo, suscripcion.fin_periodo
    )
    limite = limite_trabajos(suscripcion.plan)
    if limite is not None and usados >= limite:
        raise HTTPException(
            429,
            f"Ya usaste tus {limite} trabajos de este periodo del plan {suscripcion.plan.nombre}. "
            f"Se renuevan el {suscripcion.fin_periodo:%d/%m/%Y}.",
        )


def es_mejor_calidad(preset: str) -> bool:
    return bool(config.PRESETS.get(preset, {}).get("mejor_calidad"))


def verificar_cantidad(usuario_id: int, preset: str) -> None:
    """Antes de subir: que le queden trabajos y tenga esa calidad."""
    with SessionLocal() as db:
        suscripcion = suscripcion_vigente(db, usuario_id)
        if es_mejor_calidad(preset) and not suscripcion.plan.mejor_calidad:
            raise HTTPException(403, "La mejor calidad de separación es del plan Pro. Usa la calidad rápida o pásate a Pro.")
        _revisar_cantidad(db, suscripcion)


def verificar_audio(usuario_id: int, segundos: float) -> None:
    """Con el audio subido: revisa la duración."""
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
