"""Consultas de planes, suscripciones, métodos de pago y pagos."""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models.tablas import MetodoPago, Pago, Plan, Suscripcion


def buscar_plan(db: Session, nombre: str) -> Optional[Plan]:
    return db.scalar(select(Plan).where(Plan.nombre == nombre))


def listar_planes(db: Session) -> List[Plan]:
    """Del más barato al más caro."""
    return list(db.scalars(select(Plan).order_by(Plan.precio_mensual, Plan.id)))


def crear_plan(db: Session, **datos) -> Plan:
    """Quien llama hace el commit."""
    plan = Plan(**datos)
    db.add(plan)
    return plan


def buscar_activa(db: Session, usuario_id: int) -> Optional[Suscripcion]:
    consulta = (
        select(Suscripcion)
        .options(joinedload(Suscripcion.plan))
        .where(Suscripcion.usuario_id == usuario_id, Suscripcion.estado == "activa")
    )
    return db.scalar(consulta)


def crear_suscripcion(db: Session, usuario_id: int, plan: Plan, inicio: datetime, fin: datetime) -> Suscripcion:
    """Quien llama hace el commit."""
    suscripcion = Suscripcion(
        usuario_id=usuario_id, plan=plan, estado="activa", inicio_periodo=inicio, fin_periodo=fin
    )
    db.add(suscripcion)
    db.flush()  # para que ya tenga id
    return suscripcion


def crear_metodo_pago(db: Session, usuario_id: int, marca: str, ultimos4: str, token: str) -> MetodoPago:
    """Quien llama hace el commit."""
    metodo = MetodoPago(usuario_id=usuario_id, marca=marca, ultimos4=ultimos4, token_pasarela=token)
    db.add(metodo)
    db.flush()  # para que ya tenga id
    return metodo


def crear_pago(
    db: Session, suscripcion_id: int, metodo_pago_id: int, monto: Decimal, estado: str, id_transaccion: str
) -> Pago:
    """Quien llama hace el commit."""
    pago = Pago(
        suscripcion_id=suscripcion_id,
        metodo_pago_id=metodo_pago_id,
        monto=monto,
        estado=estado,
        id_transaccion=id_transaccion,
    )
    db.add(pago)
    return pago
