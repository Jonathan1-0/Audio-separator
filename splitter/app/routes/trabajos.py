"""Ruta de "Mis audios"."""
from fastapi import APIRouter, Depends

from ..dependencies import usuario_actual
from ..models.tablas import Usuario
from ..services import trabajos

router = APIRouter(prefix="/trabajos", tags=["trabajos"])


@router.get("")
def mis_trabajos(usuario: Usuario = Depends(usuario_actual)):
    return trabajos.historial(usuario.id)
