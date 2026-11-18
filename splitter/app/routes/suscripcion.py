"""Rutas del plan: contratar pro, cancelar y consultar."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config
from ..database import SessionLocal
from ..dependencies import usuario_actual
from ..models.tablas import Usuario
from ..repositories import suscripciones as repo_suscripciones
from ..repositories import trabajos as repo_trabajos
from ..services import pagos, perfil
from ..services.cuotas import PLANES_PRIORITARIOS, limite_trabajos, minutos_guardado, suscripcion_vigente

router = APIRouter(prefix="/suscripcion", tags=["suscripcion"])


class DatosPago(BaseModel):
    marca: str
    ultimos4: str


@router.post("/pro", status_code=201)
def contratar_pro(datos: DatosPago, usuario: Usuario = Depends(usuario_actual)):
    """Pasa al usuario al plan pro (pago simulado). Apagado salvo con SPLITTER_PAGOS_SIMULADOS=1."""
    if not config.PAGOS_SIMULADOS:
        raise HTTPException(503, "Pro estará disponible muy pronto.")
    if not usuario.email_verificado:
        raise HTTPException(403, "Confirma tu correo antes de contratar Pro. Te podemos reenviar el enlace desde tu perfil.")
    return pagos.contratar_pro(usuario.id, datos.marca, datos.ultimos4)


@router.post("/cancelar")
def cancelar_pro(usuario: Usuario = Depends(usuario_actual)):
    """Cancela la renovación: Pro sigue hasta fin_periodo y después pasa a gratis."""
    return pagos.cancelar_pro(usuario.id)


@router.post("/reanudar")
def reanudar_pro(usuario: Usuario = Depends(usuario_actual)):
    """Deshace la cancelación."""
    return pagos.reanudar_pro(usuario.id)


def _plan_publico(plan) -> dict:
    return {
        "nombre": plan.nombre,
        "precio_mensual": str(plan.precio_mensual),
        "moneda": "MXN",
        "trabajos_por_mes": limite_trabajos(plan),  # null = ilimitados
        "trabajos_ilimitados": limite_trabajos(plan) is None,
        "minutos_max_audio": plan.minutos_max_audio,
        "mejor_calidad": plan.mejor_calidad,
        "minutos_guardado": minutos_guardado(plan.nombre),
        "historial": plan.nombre in config.PLANES_CON_HISTORIAL,
        # GPU más rápida (L40S) y primero en la cola
        "prioridad": plan.nombre in PLANES_PRIORITARIOS,
    }


@router.get("/planes")
def planes():
    """Planes disponibles."""
    with SessionLocal() as db:
        return {
            "dias_periodo": config.DIAS_PERIODO,
            "pagos_activos": config.PAGOS_SIMULADOS,  # false: la página muestra Pro como "Próximamente"
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
            "telefono": usuario.telefono,
            "foto_url": perfil.foto_url(usuario),
            "email_verificado": bool(usuario.email_verificado),
            "proveedor": usuario.proveedor,
            "google_conectado": bool(usuario.google_id),
            "facebook_conectado": bool(usuario.facebook_id),
            "tiene_password": bool(usuario.tiene_password),
            "plan": suscripcion.plan.nombre,
            "mejor_calidad": suscripcion.plan.mejor_calidad,
            "fin_periodo": f"{suscripcion.fin_periodo.isoformat()}Z",
            "cancelar_al_final": bool(suscripcion.cancelar_al_final),
            "minutos_guardado": minutos_guardado(suscripcion.plan.nombre),
            "historial": suscripcion.plan.nombre in config.PLANES_CON_HISTORIAL,
            "trabajos_por_mes": limite_trabajos(suscripcion.plan),  # null = ilimitados
            "trabajos_ilimitados": limite_trabajos(suscripcion.plan) is None,
            "trabajos_usados": repo_trabajos.contar_en_periodo(
                db, usuario.id, suscripcion.inicio_periodo, suscripcion.fin_periodo
            ),
            "minutos_max_audio": suscripcion.plan.minutos_max_audio,
            "pro": {
                "precio_mensual": str(pro.precio_mensual),
                "trabajos_por_mes": limite_trabajos(pro),
                "trabajos_ilimitados": limite_trabajos(pro) is None,
                "minutos_max_audio": pro.minutos_max_audio,
                "minutos_guardado": minutos_guardado("pro"),
                "dias_periodo": config.DIAS_PERIODO,
            },
        }
