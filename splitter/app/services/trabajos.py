"""Historial de trabajos ("Mis audios"), solo plan pro."""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import HTTPException

from .. import config
from ..database import SessionLocal, ahora_utc
from ..repositories import trabajos as repo_trabajos
from .cuotas import minutos_guardado, plan_vigente



def _fecha(valor: Optional[datetime]) -> Optional[str]:
    return f"{valor.isoformat()}Z" if valor else None


def historial(usuario_id: int) -> List[dict]:
    """Trabajos de la última semana."""
    ahora = ahora_utc()
    with SessionLocal() as db:
        plan = plan_vigente(db, usuario_id)
        if plan not in config.PLANES_CON_HISTORIAL:
            raise HTTPException(403, "El historial de tus audios es del plan Pro.")
        desde = ahora - timedelta(minutes=minutos_guardado(plan))
        trabajos = repo_trabajos.listar_por_usuario(db, usuario_id, desde)
        return [
            {
                "id": t.id,
                "nombre_original": t.nombre_original,
                "preset": t.preset,
                "pistas_pedidas": t.pistas_pedidas,
                "estado": t.estado,
                "progreso": t.progreso,
                "duracion_audio_seg": t.duracion_audio_seg,
                "mensaje_error": t.mensaje_error,
                "creado_en": _fecha(t.creado_en),
                "terminado_en": _fecha(t.terminado_en),
                "disponible": any(r.expira_en > ahora for r in t.resultados),
                "expira_en": _fecha(max((r.expira_en for r in t.resultados), default=None)),
                "resultados": [
                    {
                        "stem": r.stem,
                        "expira_en": _fecha(r.expira_en),
                        "disponible": r.expira_en > ahora,
                        "download_url": f"/api/jobs/{t.id}/stems/{r.stem}/download",
                    }
                    for r in t.resultados
                ],
            }
            for t in trabajos
        ]
