"""Ruta del pago simulado."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..dependencies import usuario_actual
from ..models.tablas import Usuario
from ..services import pagos

router = APIRouter(prefix="/suscripcion", tags=["suscripcion"])


class DatosPago(BaseModel):
    marca: str
    ultimos4: str


@router.post("/pro", status_code=201)
def contratar_pro(datos: DatosPago, usuario: Usuario = Depends(usuario_actual)):
    """Cambia al usuario al plan pro con un pago simulado."""
    return pagos.contratar_pro(usuario.id, datos.marca, datos.ultimos4)
