"""Pago simulado del plan pro. Nunca se recibe el número completo de la tarjeta."""
import secrets
from datetime import timedelta

from fastapi import HTTPException

from .. import config
from ..database import SessionLocal, ahora_utc
from ..repositories import suscripciones as repo_suscripciones
from .cuotas import suscripcion_vigente


def contratar_pro(usuario_id: int, marca: str, ultimos4: str) -> dict:
    """Registra el método de pago y el pago, y cambia al usuario al plan pro."""
    marca = marca.strip()
    if not marca or len(marca) > 30:
        raise HTTPException(400, "La marca debe tener entre 1 y 30 caracteres.")
    if len(ultimos4) != 4 or not (ultimos4.isascii() and ultimos4.isdigit()):
        raise HTTPException(400, "Manda solo los últimos 4 dígitos de la tarjeta.")

    with SessionLocal() as db:
        actual = suscripcion_vigente(db, usuario_id)
        if actual.plan.nombre == "pro":
            raise HTTPException(409, "Ya tienes el plan pro.")
        plan = repo_suscripciones.buscar_plan(db, "pro")

        actual.estado = "cancelada"
        db.flush()
        inicio = ahora_utc()
        fin = inicio + timedelta(days=config.DIAS_PERIODO)
        nueva = repo_suscripciones.crear_suscripcion(db, usuario_id, plan, inicio, fin)
        metodo = repo_suscripciones.crear_metodo_pago(
            db, usuario_id, marca, ultimos4, f"tok_sim_{secrets.token_hex(16)}"
        )
        id_transaccion = f"txn_sim_{secrets.token_hex(16)}"
        repo_suscripciones.crear_pago(db, nueva.id, metodo.id, plan.precio_mensual, "pagado", id_transaccion)
        db.commit()  # todo se guarda junto, o nada
        return {
            "plan": plan.nombre,
            "monto": str(plan.precio_mensual),
            "moneda": "MXN",
            "id_transaccion": id_transaccion,
            "fin_periodo": f"{fin.isoformat()}Z",
        }


def cancelar_pro(usuario_id: int) -> dict:
    """Pasa al usuario al plan gratis desde ahora. El plan pro no se renueva solo, así que cancelar
    al final del periodo no cambiaría nada; el pago (simulado) no se devuelve.

    El plan gratis sigue con las mismas fechas del periodo pro: los trabajos que ya se hicieron en él
    siguen contando, así que cancelar no da trabajos nuevos. Al terminar ese periodo empieza uno
    gratis normal."""
    with SessionLocal() as db:
        actual = suscripcion_vigente(db, usuario_id)
        if actual.plan.nombre != "pro":
            raise HTTPException(409, "No tienes el plan pro.")
        actual.estado = "cancelada"
        db.flush()
        gratis = repo_suscripciones.buscar_plan(db, "gratis")
        nueva = repo_suscripciones.crear_suscripcion(
            db, usuario_id, gratis, actual.inicio_periodo, actual.fin_periodo
        )
        db.commit()  # todo se guarda junto, o nada
        return {"plan": "gratis", "fin_periodo": f"{nueva.fin_periodo.isoformat()}Z"}
