"""Historial de trabajos del usuario ("Mis audios")."""
from datetime import datetime
from typing import List, Optional

from ..database import SessionLocal, ahora_utc
from ..repositories import trabajos as repo_trabajos


def _fecha(valor: Optional[datetime]) -> Optional[str]:
    """Fecha en texto, marcada como UTC."""
    return f"{valor.isoformat()}Z" if valor else None


def historial(usuario_id: int) -> List[dict]:
    """Trabajos del usuario con sus resultados."""
    ahora = ahora_utc()
    with SessionLocal() as db:
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
            for t in repo_trabajos.listar_por_usuario(db, usuario_id)
        ]
