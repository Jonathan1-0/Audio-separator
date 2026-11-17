"""Pago simulado del plan pro."""
import secrets

from fastapi import HTTPException

from ..database import SessionLocal, ahora_utc
from ..repositories import suscripciones as repo_suscripciones
from .cuotas import fin_de_periodo, suscripcion_vigente


def contratar_pro(usuario_id: int, marca: str, ultimos4: str) -> dict:
    """Registra el pago y pasa al usuario al plan pro."""
    marca = marca.strip()
    if not marca or len(marca) > 30:
        raise HTTPException(400, "La marca debe tener entre 1 y 30 caracteres.")
    if len(ultimos4) != 4 or not (ultimos4.isascii() and ultimos4.isdigit()):
        raise HTTPException(400, "Manda solo los últimos 4 dígitos de la tarjeta.")

    with SessionLocal() as db:
        actual = suscripcion_vigente(db, usuario_id)
        if actual.plan.nombre == "pro":
            raise HTTPException(409, "Ya tienes el plan pro.")
        if actual.plan.nombre != "gratis":
            raise HTTPException(409, "Tu cuenta ya tiene todo lo del plan pro.")
        plan = repo_suscripciones.buscar_plan(db, "pro")

        actual.estado = "cancelada"
        db.flush()
        inicio = ahora_utc()
        fin = fin_de_periodo(inicio)
        nueva = repo_suscripciones.crear_suscripcion(db, usuario_id, plan, inicio, fin)
        metodo = repo_suscripciones.crear_metodo_pago(
            db, usuario_id, marca, ultimos4, f"tok_sim_{secrets.token_hex(16)}"
        )
        id_transaccion = f"txn_sim_{secrets.token_hex(16)}"
        repo_suscripciones.crear_pago(db, nueva.id, metodo.id, plan.precio_mensual, "pagado", id_transaccion)
        db.commit()
        return {
            "plan": plan.nombre,
            "monto": str(plan.precio_mensual),
            "moneda": "MXN",
            "id_transaccion": id_transaccion,
            "fin_periodo": f"{fin.isoformat()}Z",
        }


def cancelar_pro(usuario_id: int) -> dict:
    """Cancela la renovación: sigue con Pro hasta fin_periodo (ya lo pagó) y después pasa a gratis."""
    with SessionLocal() as db:
        actual = suscripcion_vigente(db, usuario_id)
        if actual.plan.nombre != "pro":
            raise HTTPException(409, "No tienes el plan pro.")
        if actual.cancelar_al_final:
            raise HTTPException(409, f"Ya lo cancelaste: sigues con Pro hasta el {actual.fin_periodo:%d/%m/%Y}.")
        actual.cancelar_al_final = True
        db.commit()
        return {"plan": "pro", "cancelar_al_final": True, "fin_periodo": f"{actual.fin_periodo.isoformat()}Z"}


def reanudar_pro(usuario_id: int) -> dict:
    """Deshace la cancelación mientras el periodo sigue vigente."""
    with SessionLocal() as db:
        actual = suscripcion_vigente(db, usuario_id)
        if actual.plan.nombre != "pro" or not actual.cancelar_al_final:
            raise HTTPException(409, "No hay una cancelación que deshacer.")
        actual.cancelar_al_final = False
        db.commit()
        return {"plan": "pro", "cancelar_al_final": False, "fin_periodo": f"{actual.fin_periodo.isoformat()}Z"}
