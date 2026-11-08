"""Rutas del plan: contratar pro (pago simulado), cancelarlo y consultar el vigente."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import config
from ..database import SessionLocal
from ..dependencies import usuario_actual
from ..models.tablas import Usuario
from ..repositories import suscripciones as repo_suscripciones
from ..services import pagos
from ..services.cuotas import minutos_guardado, suscripcion_vigente

router = APIRouter(prefix="/suscripcion", tags=["suscripcion"])


class DatosPago(BaseModel):
    marca: str
    ultimos4: str


@router.post("/pro", status_code=201)
def contratar_pro(datos: DatosPago, usuario: Usuario = Depends(usuario_actual)):
    """Cambia al usuario al plan pro con un pago simulado."""
    return pagos.contratar_pro(usuario.id, datos.marca, datos.ultimos4)


@router.post("/cancelar")
def cancelar_pro(usuario: Usuario = Depends(usuario_actual)):
    """Cancela el plan pro y el usuario pasa al plan gratis desde ahora."""
    return pagos.cancelar_pro(usuario.id)


@router.get("")
def mi_plan(usuario: Usuario = Depends(usuario_actual)):
    """Plan vigente: la página lo usa para mostrar el historial (solo pro) y cuánto se guardan los audios."""
    with SessionLocal() as db:
        suscripcion = suscripcion_vigente(db, usuario.id)
        pro = repo_suscripciones.buscar_plan(db, "pro")
        return {
            "plan": suscripcion.plan.nombre,
            "fin_periodo": f"{suscripcion.fin_periodo.isoformat()}Z",
            "minutos_guardado": minutos_guardado(suscripcion.plan.nombre),
            "historial": suscripcion.plan.nombre == "pro",
            # Para la oferta de "Pasarse a Pro" en la página.
            "pro": {
                "precio_mensual": str(pro.precio_mensual),
                "trabajos_por_mes": pro.trabajos_por_mes,
                "minutos_max_audio": pro.minutos_max_audio,
                "minutos_guardado": minutos_guardado("pro"),
                "dias_periodo": config.DIAS_PERIODO,
            },
        }
