"""Rutas del plan: contratar pro, cancelar y consultar."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import config
from ..database import SessionLocal
from ..dependencies import usuario_actual
from ..models.tablas import Usuario
from ..repositories import suscripciones as repo_suscripciones
from ..repositories import trabajos as repo_trabajos
from ..services import pagos
from ..services.cuotas import minutos_guardado, suscripcion_vigente

router = APIRouter(prefix="/suscripcion", tags=["suscripcion"])


class DatosPago(BaseModel):
    marca: str
    ultimos4: str


@router.post("/pro", status_code=201)
def contratar_pro(datos: DatosPago, usuario: Usuario = Depends(usuario_actual)):
    """Pasa al usuario al plan pro (pago simulado)."""
    return pagos.contratar_pro(usuario.id, datos.marca, datos.ultimos4)


@router.post("/cancelar")
def cancelar_pro(usuario: Usuario = Depends(usuario_actual)):
    """Cancela el plan pro."""
    return pagos.cancelar_pro(usuario.id)


def _plan_publico(plan) -> dict:
    return {
        "nombre": plan.nombre,
        "precio_mensual": str(plan.precio_mensual),
        "moneda": "MXN",
        "trabajos_por_mes": plan.trabajos_por_mes,
        "minutos_max_audio": plan.minutos_max_audio,
        "mejor_calidad": plan.mejor_calidad,
        "minutos_guardado": minutos_guardado(plan.nombre),
        "historial": plan.nombre in config.PLANES_CON_HISTORIAL,
    }


@router.get("/planes")
def planes():
    """Planes disponibles."""
    with SessionLocal() as db:
        return {
            "dias_periodo": config.DIAS_PERIODO,
            "planes": [_plan_publico(p) for p in repo_suscripciones.listar_planes(db) if p.nombre != "admin"],
        }


@router.get("")
def mi_plan(usuario: Usuario = Depends(usuario_actual)):
    """Cuenta, plan vigente y consumo."""
    with SessionLocal() as db:
        suscripcion = suscripcion_vigente(db, usuario.id)
        pro = repo_suscripciones.buscar_plan(db, "pro")
        return {
            "nombre": usuario.nombre,
            "email": usuario.email,
            "plan": suscripcion.plan.nombre,
            "mejor_calidad": suscripcion.plan.mejor_calidad,
            "fin_periodo": f"{suscripcion.fin_periodo.isoformat()}Z",
            "minutos_guardado": minutos_guardado(suscripcion.plan.nombre),
            "historial": suscripcion.plan.nombre in config.PLANES_CON_HISTORIAL,
            "trabajos_por_mes": suscripcion.plan.trabajos_por_mes,
            "trabajos_usados": repo_trabajos.contar_en_periodo(
                db, usuario.id, suscripcion.inicio_periodo, suscripcion.fin_periodo
            ),
            "minutos_max_audio": suscripcion.plan.minutos_max_audio,
            "pro": {
                "precio_mensual": str(pro.precio_mensual),
                "trabajos_por_mes": pro.trabajos_por_mes,
                "minutos_max_audio": pro.minutos_max_audio,
                "minutos_guardado": minutos_guardado("pro"),
                "dias_periodo": config.DIAS_PERIODO,
            },
        }
