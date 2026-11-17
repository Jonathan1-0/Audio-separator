"""Limpieza de la base: corre cada hora en segundo plano.

- Sesiones vencidas (de todos los usuarios).
- Trabajos de hace más de DIAS_HISTORIAL_TRABAJOS días: sus audios ya se borraron hace mucho
  y no salen en "Mis audios"; solo ocupaban espacio. Los pagos y suscripciones no se tocan.
"""
import logging
import threading
from datetime import timedelta

from sqlalchemy import delete, select

from . import config
from .database import SessionLocal, ahora_utc
from .models.tablas import Resultado, Sesion, Trabajo

log = logging.getLogger("splitter.mantenimiento")


def limpiar_base() -> dict:
    ahora = ahora_utc()
    limite = ahora - timedelta(days=config.DIAS_HISTORIAL_TRABAJOS)
    with SessionLocal() as db:
        sesiones = db.execute(delete(Sesion).where(Sesion.expira_en < ahora)).rowcount or 0
        viejos = list(db.scalars(
            select(Trabajo.id).where(Trabajo.creado_en < limite, Trabajo.estado.in_(("completado", "error"))).limit(5000)
        ))
        if viejos:
            db.execute(delete(Resultado).where(Resultado.trabajo_id.in_(viejos)))
            db.execute(delete(Trabajo).where(Trabajo.id.in_(viejos)))
        db.commit()
    if sesiones or viejos:
        log.info("Limpieza: %d sesiones vencidas y %d trabajos viejos borrados", sesiones, len(viejos))
    return {"sesiones": sesiones, "trabajos": len(viejos)}


class Mantenimiento:
    def __init__(self, cada_segundos: int = 3600) -> None:
        self._parar = threading.Event()
        self._cada = cada_segundos
        self._hilo = threading.Thread(target=self._correr, name="splitter-mantenimiento", daemon=True)

    def start(self) -> None:
        self._hilo.start()

    def stop(self) -> None:
        self._parar.set()

    def _correr(self) -> None:
        while not self._parar.wait(self._cada):
            try:
                limpiar_base()
            except Exception:
                log.exception("Falló la limpieza de la base")
