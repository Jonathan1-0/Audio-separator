"""Cola de trabajos, con un hilo por GPU de Modal.

En memoria quedan los trabajos activos y los de invitados; los de cuentas terminados viven en la base.
"""
from __future__ import annotations

import logging
import queue
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from . import config
from .database import SessionLocal, ahora_utc
from .engine import gpu_seconds_del_hilo
from .models.tablas import Trabajo
from .repositories import trabajos as repo_trabajos
from .services.cuotas import minutos_guardado, plan_vigente

log = logging.getLogger("splitter.jobs")

QUEUED, PROCESSING, DONE, ERROR = "queued", "processing", "done", "error"
# Fase de un trabajo en proceso: esperando a que Modal asigne una GPU, o ya separando.
WAITING_GPU, SEPARATING = "waiting_gpu", "separating"
ESTADOS_BD = {QUEUED: "en_cola", PROCESSING: "procesando", DONE: "completado", ERROR: "error"}
ESTADOS_JOB = {v: k for k, v in ESTADOS_BD.items()}
MENSAJES = {QUEUED: "En cola", PROCESSING: "Separando audio…", DONE: "Listo", ERROR: "Error al procesar el audio"}


@dataclass
class Job:
    id: str
    usuario_id: Optional[int]  # None = sin cuenta: el trabajo solo vive en memoria
    original_name: str
    preset: str
    wanted_stems: List[str]
    input_path: Path
    out_dir: Path
    size_bytes: int = 0
    duration_seconds: Optional[float] = None
    status: str = QUEUED
    progress: Optional[float] = 0.0  # 0..1, None si no se puede medir
    message: str = "En cola"
    error: Optional[str] = None
    phase: Optional[str] = None  # waiting_gpu | separating; None si no se está procesando
    stem_files: Dict[str, Path] = field(default_factory=dict)
    gpu_seconds: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    expires_at: Optional[float] = None  # cuándo se borran sus pistas; depende del plan
    version: int = 0  # sube con cada cambio; el SSE lo usa para saber si hay novedades

    def touch(self) -> None:
        self.version += 1


def _segundos(fecha) -> Optional[float]:
    """Fecha UTC de la base -> time.time()."""
    return fecha.replace(tzinfo=timezone.utc).timestamp() if fecha else None


def _job_desde_fila(fila: Trabajo) -> Optional[Job]:
    """Arma un Job desde la base. Devuelve None si sus archivos ya expiraron."""
    status = ESTADOS_JOB[fila.estado]
    ahora = ahora_utc()
    vigentes = [r for r in fila.resultados if r.expira_en > ahora]
    stems = {r.stem: Path(r.ruta_archivo) for r in vigentes}
    if status == DONE and not stems:
        return None
    carpeta = config.DATA_DIR / fila.id
    return Job(
        id=fila.id,
        usuario_id=fila.usuario_id,
        original_name=fila.nombre_original,
        preset=fila.preset,
        wanted_stems=fila.pistas_pedidas.split(","),
        input_path=carpeta / "input",
        out_dir=carpeta / "out",
        size_bytes=fila.tamano_bytes,
        duration_seconds=fila.duracion_audio_seg,
        status=status,
        progress=None if status == ERROR else fila.progreso / 100,
        message=MENSAJES[status],
        error=fila.mensaje_error,
        stem_files=stems,
        gpu_seconds=fila.gpu_seconds,
        created_at=_segundos(fila.creado_en),
        finished_at=_segundos(fila.terminado_en),
        expires_at=max((_segundos(r.expira_en) for r in vigentes), default=None),
    )


class JobManager:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.jobs: Dict[str, Job] = {}
        self._order: List[str] = []  # posición en la cola
        self._queue: "queue.Queue[str]" = queue.Queue(maxsize=config.MAX_QUEUE)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        n = max(1, getattr(engine, "parallel_jobs", 1))
        self._workers = [
            threading.Thread(target=self._run, name=f"splitter-worker-{i + 1}", daemon=True) for i in range(n)
        ]
        self._cleaner = threading.Thread(target=self._clean_loop, name="splitter-cleaner", daemon=True)

    def start(self) -> None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._restaurar()
        for w in self._workers:
            w.start()
        log.info("%d trabajo(s) en paralelo", len(self._workers))
        self._cleaner.start()

    def stop(self) -> None:
        self._stop.set()

    def new_job_dir(self) -> tuple[str, Path]:
        job_id = uuid.uuid4().hex
        d = config.DATA_DIR / job_id
        d.mkdir(parents=True, exist_ok=True)
        return job_id, d

    def submit(self, job: Job) -> None:
        """Guarda el trabajo y lo pone en la cola. Lanza queue.Full si la cola está llena."""
        if job.usuario_id is None:
            self._encolar(job)  # sin cuenta: no va a la base
            return
        with SessionLocal() as db:
            repo_trabajos.crear(
                db,
                id=job.id,
                usuario_id=job.usuario_id,
                nombre_original=job.original_name,
                tamano_bytes=job.size_bytes,
                preset=job.preset,
                pistas_pedidas=",".join(job.wanted_stems),
                duracion_audio_seg=job.duration_seconds,
            )
            try:
                self._encolar(job)
            except queue.Full:
                repo_trabajos.borrar(db, job.id)  # un rechazo no cuenta para la cuota
                raise

    def _encolar(self, job: Job) -> None:
        with self._lock:
            self._queue.put_nowait(job.id)
            self.jobs[job.id] = job
            self._order.append(job.id)

    def get(self, job_id: str) -> Optional[Job]:
        """Primero la memoria, luego la base."""
        job = self.jobs.get(job_id)
        if job is not None:
            return job
        with SessionLocal() as db:
            fila = repo_trabajos.obtener(db, job_id)
            return _job_desde_fila(fila) if fila is not None else None

    def queue_position(self, job_id: str) -> Optional[int]:
        with self._lock:
            if job_id in self._order:
                return self._order.index(job_id) + 1
        return None

    def delete(self, job_id: str) -> bool:
        """Borra los archivos. La fila se queda para el historial y las cuotas."""
        job = self.jobs.pop(job_id, None)
        activo = job is not None
        with self._lock:
            if job_id in self._order:
                self._order.remove(job_id)
        if job is not None and job.usuario_id is None:  # invitado: no tiene fila en la base
            shutil.rmtree(config.DATA_DIR / job_id, ignore_errors=True)
            return True
        with SessionLocal() as db:
            fila = repo_trabajos.obtener(db, job_id)
            if fila is None:
                return False
            repo_trabajos.marcar_borrado(db, job_id, ahora_utc(), cancelado=activo)
        shutil.rmtree(config.DATA_DIR / job_id, ignore_errors=True)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            job = self.jobs.get(job_id)
            with self._lock:
                if job_id in self._order:
                    self._order.remove(job_id)
            if job is None:  # se borró mientras esperaba
                continue
            self._process(job)

    def _process(self, job: Job) -> None:
        job.status, job.message, job.progress = PROCESSING, MENSAJES[PROCESSING], 0.0
        # Con Modal hay que esperar a que asigne una GPU; su primer avance avisa que ya empezó.
        if getattr(self.engine, "waits_for_gpu", False):
            job.phase, job.message = WAITING_GPU, "Esperando GPU…"
        else:
            job.phase = SEPARATING
        job.touch()
        self._guardar_estado(job)
        guardado = 0  # último progreso guardado en la base, de 0 a 100

        def on_progress(fraction: float) -> None:
            nonlocal guardado
            if job.phase == WAITING_GPU:  # llegó el primer avance: ya hay GPU
                job.phase, job.message = SEPARATING, "Separando audio…"
                job.touch()
            # Nunca baja, y se queda en 95 % hasta que termina de verdad.
            new = min(0.95, max(job.progress or 0.0, fraction * 0.95))
            if new - (job.progress or 0.0) >= 0.01:
                job.progress = new
                job.touch()
            # A la base solo cada 5 puntos, para no saturarla.
            if int(new * 100) - guardado >= 5:
                guardado = int(new * 100)
                self._guardar_estado(job)

        try:
            files = self.engine.separate(job.input_path, job.out_dir, job.preset, on_progress)
            job.gpu_seconds = gpu_seconds_del_hilo()
            # Solo se guardan las pistas que pidió el usuario.
            keep = {s: p for s, p in files.items() if s in job.wanted_stems}
            for s, p in files.items():
                if s not in keep:
                    p.unlink(missing_ok=True)
            job.stem_files = keep
            # Antes de marcarlo listo: el SSE manda el vencimiento en cuanto ve DONE.
            job.expires_at = self._vencimiento(job)
            job.status, job.progress, job.message = DONE, 1.0, MENSAJES[DONE]
        except Exception as exc:  # noqa: BLE001 - el error se muestra en la página
            if self.jobs.get(job.id) is not job:
                log.info("Trabajo %s borrado mientras se procesaba", job.id)
            else:
                log.exception("Falló el trabajo %s", job.id)
            job.status, job.progress, job.message = ERROR, None, MENSAJES[ERROR]
            job.error = str(exc)[:300]
        finally:
            job.phase = None
            job.finished_at = time.time()
            job.input_path.unlink(missing_ok=True)
            job.touch()
            if self.jobs.get(job.id) is job:
                # El de invitado se queda en memoria hasta que expire (ver _clean_loop).
                if job.usuario_id is not None and self._guardar_final(job):
                    self.jobs.pop(job.id, None)
            else:
                # Se borró mientras se procesaba: el motor volvió a crear la carpeta al escribir.
                shutil.rmtree(config.DATA_DIR / job.id, ignore_errors=True)

    def _guardar_estado(self, job: Job) -> None:
        """Si la base falla, el trabajo sigue igual."""
        if job.usuario_id is None:
            return
        try:
            with SessionLocal() as db:
                repo_trabajos.actualizar_estado(db, job.id, ESTADOS_BD[job.status], int((job.progress or 0) * 100))
        except SQLAlchemyError:
            log.exception("No se pudo guardar el progreso de %s", job.id)

    def _vencimiento(self, job: Job) -> float:
        """Cuándo se borran sus pistas. El plan que tiene al terminar decide: gratis 1 h, pro una semana."""
        minutos = config.JOB_TTL_MINUTES
        if job.usuario_id is not None:
            try:
                with SessionLocal() as db:
                    minutos = minutos_guardado(plan_vigente(db, job.usuario_id))
            except SQLAlchemyError:
                log.exception("No se pudo leer el plan de %s; se guarda %d min", job.id, minutos)
        return time.time() + minutos * 60

    def _guardar_final(self, job: Job) -> bool:
        """Si la base falla, el trabajo sigue en memoria."""
        ahora = ahora_utc()
        try:
            with SessionLocal() as db:
                expira_en = (
                    datetime.fromtimestamp(job.expires_at, timezone.utc).replace(tzinfo=None)
                    if job.expires_at
                    else ahora
                )
                repo_trabajos.terminar(
                    db,
                    job.id,
                    ESTADOS_BD[job.status],
                    100 if job.status == DONE else 0,
                    ahora,
                    job.error,
                    job.gpu_seconds,
                    {stem: str(ruta) for stem, ruta in job.stem_files.items()},
                    expira_en,
                )
            return True
        except SQLAlchemyError:
            log.exception("No se pudo guardar el final de %s", job.id)
            return False

    def _restaurar(self) -> None:
        """Al arrancar, lo que quedó sin terminar vuelve a la cola si todavía tiene su audio."""
        with SessionLocal() as db:
            pendientes = repo_trabajos.listar_pendientes(db)
            requeued = 0
            for fila in pendientes:
                carpeta = config.DATA_DIR / fila.id
                entradas = list(carpeta.glob("input.*"))
                if entradas and self._reencolar(_job_desde_fila(fila), entradas[0]):
                    repo_trabajos.actualizar_estado(db, fila.id, "en_cola", 0)
                    requeued += 1
                    continue
                shutil.rmtree(carpeta, ignore_errors=True)
                repo_trabajos.terminar(
                    db, fila.id, "error", 0, ahora_utc(), "El servidor se reinició y no se pudo retomar.",
                    None, {}, ahora_utc(),
                )
        if pendientes:
            log.info("%d trabajo(s) pendientes; %d vuelven a la cola", len(pendientes), requeued)

    def _reencolar(self, job: Job, entrada: Path) -> bool:
        job.input_path = entrada
        job.status, job.progress, job.message = QUEUED, 0.0, MENSAJES[QUEUED]
        shutil.rmtree(job.out_dir, ignore_errors=True)
        try:
            self._encolar(job)
            return True
        except queue.Full:
            return False

    def _clean_loop(self) -> None:
        while not self._stop.wait(60):
            cutoff = time.time() - config.JOB_TTL_MINUTES * 60
            # Los de invitado salen de la memoria al expirar; su carpeta se borra abajo.
            for job_id, job in list(self.jobs.items()):
                if job.usuario_id is None and job.finished_at and job.finished_at < cutoff:
                    self.jobs.pop(job_id, None)
            for d in config.DATA_DIR.iterdir():
                # La carpeta cambió por última vez al borrar el audio original, cuando terminó.
                if d.is_dir() and re.fullmatch(r"[0-9a-f]{32}", d.name) and d.name not in self.jobs:
                    if d.stat().st_mtime < cutoff and not self._sigue_vigente(d.name):
                        log.info("Borrando archivos expirados de %s", d.name)
                        shutil.rmtree(d, ignore_errors=True)

    def _sigue_vigente(self, job_id: str) -> bool:
        """Un trabajo con cuenta se guarda hasta su expira_en (una semana en pro)."""
        try:
            with SessionLocal() as db:
                fila = repo_trabajos.obtener(db, job_id)
                return fila is not None and any(r.expira_en > ahora_utc() for r in fila.resultados)
        except SQLAlchemyError:
            log.exception("No se pudo revisar si %s sigue vigente", job_id)
            return True  # ante la duda no se borra; se revisa en la siguiente vuelta
