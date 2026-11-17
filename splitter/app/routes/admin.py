"""Panel de administración: solo para la cuenta con plan admin."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .. import config
from ..dependencies import usuario_actual
from ..models.tablas import Usuario
from ..services import admin

router = APIRouter(prefix="/admin", tags=["admin"])


def solo_admin(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    if not admin.es_admin(usuario.id):
        raise HTTPException(403, "Solo la cuenta de administrador puede ver esto.")
    if config.ADMIN_REQUIERE_DOS_PASOS and not usuario.totp_activo:
        raise HTTPException(403, "Activa la verificación en dos pasos en tu perfil para usar el panel.")
    return usuario


def _cola(request: Request) -> dict:
    manager = request.app.state.manager
    estados = [job.status for job in list(manager.jobs.values())]
    return {
        "en_cola": estados.count("queued"),
        "procesando": estados.count("processing"),
        "trabajos_en_memoria": len(estados),
    }


@router.get("/resumen")
async def resumen(request: Request, _admin: Usuario = Depends(solo_admin)):
    return await run_in_threadpool(admin.resumen, _cola(request))


@router.get("/usuarios")
def usuarios(q: str = "", pagina: int = 1, _admin: Usuario = Depends(solo_admin)):
    return admin.usuarios(q, pagina)


class DatosEstado(BaseModel):
    estado: str


@router.post("/usuarios/{usuario_id}/estado")
def cambiar_estado(usuario_id: int, datos: DatosEstado, yo: Usuario = Depends(solo_admin)):
    """Suspende o reactiva una cuenta. Suspender cierra sus sesiones."""
    return admin.cambiar_estado(yo.id, usuario_id, datos.estado)


@router.get("/trabajos")
def trabajos(estado: str = "", pagina: int = 1, _admin: Usuario = Depends(solo_admin)):
    return admin.trabajos(estado, pagina)


@router.get("/pagos")
def pagos(pagina: int = 1, _admin: Usuario = Depends(solo_admin)):
    return admin.pagos(pagina)
