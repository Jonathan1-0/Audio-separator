"""API de Splitter."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import shutil
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, media
from .dependencies import usuario_opcional
from .engine import build_engine
from .jobs import DONE, ERROR, Job, JobManager
from .models.tablas import Usuario
from .ratelimit import RateLimiter
from .routes import auth as rutas_auth
from .routes import suscripcion as rutas_suscripcion
from .routes import trabajos as rutas_trabajos
from .seed import preparar_base
from .services import cuotas, invitados

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("splitter.api")

engine = build_engine()
manager = JobManager(engine)
# Un solo contador para toda la página: es el tope de gasto en Modal.
daily_limiter = RateLimiter(config.MAX_JOBS_PER_DAY, 24 * 3600, config.DATA_DIR / "limite_dia.json")
ALL_USERS = "todos"


@asynccontextmanager
async def lifespan(app: FastAPI):
    preparar_base()
    manager.start()
    log.info("Splitter listo — motor: %s", engine.device_info())
    yield
    manager.stop()


app = FastAPI(title="Splitter API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
app.include_router(rutas_auth.router)
app.include_router(rutas_suscripcion.router)
app.include_router(rutas_trabajos.router)


# --- Utilidades
def _safe_base_name(filename: str) -> str:
    stem = Path(filename).stem
    cleaned = re.sub(r"[^\w\- .()\[\]]", "_", stem, flags=re.UNICODE).strip(" .")
    return cleaned[:80] or "audio"


def _job_or_404(job_id: str) -> Job:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "Ese trabajo no existe o ya expiró.")
    return job


def _job_del_solicitante(job_id: str, usuario: Optional[Usuario]) -> Job:
    """El trabajo de una cuenta solo lo ve su dueño; el de un invitado, quien tenga su id."""
    job = _job_or_404(job_id)
    if job.usuario_id is not None and (usuario is None or usuario.id != job.usuario_id):
        raise HTTPException(404, "Ese trabajo no existe o ya expiró.")
    return job


def _public(job: Job) -> dict:
    data = {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,  # 0..1 o null
        "message": job.message,
        "error": job.error,
        "filename": job.original_name,
        "preset": job.preset,
        "queue_position": manager.queue_position(job.id),
        "phase": job.phase,  # waiting_gpu | separating, solo en processing
    }
    if job.status == DONE:
        data["stems"] = [
            {
                "name": stem,
                "preview_url": f"/api/jobs/{job.id}/stems/{stem}/preview",
                "download_url": f"/api/jobs/{job.id}/stems/{stem}/download",
            }
            for stem in job.stem_files
        ]
        data["download_all_url"] = f"/api/jobs/{job.id}/download"
        # Invitado: JOB_TTL_MINUTES desde que terminó; con cuenta, lo que diga su plan.
        expira = job.expires_at or (job.finished_at or time.time()) + config.JOB_TTL_MINUTES * 60
        data["expires_in_minutes"] = max(0, round((expira - time.time()) / 60))
        data["expires_at"] = datetime.fromtimestamp(expira, timezone.utc).isoformat().replace("+00:00", "Z")
    return data


def _check_format(fmt: str) -> str:
    fmt = fmt.lower()
    if fmt not in config.OUTPUT_FORMATS:
        raise HTTPException(400, f"Formato no soportado. Usa uno de: {', '.join(config.OUTPUT_FORMATS)}.")
    return fmt


def _stem_path(job: Job, stem: str) -> Path:
    if job.status != DONE:
        raise HTTPException(409, "El trabajo todavía no termina.")
    path = job.stem_files.get(stem)
    if path is None or not path.exists():
        raise HTTPException(404, "Esa pista no existe en este trabajo.")
    return path


# --- Información general
@app.get("/api/health")
def health():
    return {
        "ok": True,
        "engine": engine.device_info(),
        "ffmpeg": media.ffmpeg_available(),
        "jobs_in_memory": len(manager.jobs),
    }


@app.get("/api/config")
def get_config():
    return {
        "max_upload_mb": config.MAX_UPLOAD_MB,
        "accepted_extensions": sorted(config.ALLOWED_INPUT_EXT),
        "output_formats": list(config.OUTPUT_FORMATS),
        "default_preset": config.DEFAULT_PRESET,
        "presets": {
            k: {"label": v["label"], "stems": v["stems"], "mejor_calidad": bool(v.get("mejor_calidad"))}
            for k, v in config.PRESETS.items()
        },
        "results_kept_minutes": config.JOB_TTL_MINUTES,
        "max_jobs_per_day": config.MAX_JOBS_PER_DAY or None,
        "invitado": {
            "max_audio_minutes": config.INVITADO_MINUTOS_AUDIO,
            "max_jobs_per_day": config.INVITADO_TRABAJOS_POR_DIA,
        },
    }


async def _audio_seconds(path: Path) -> float:
    """Sin la duración no se puede aplicar el límite del plan, así que el audio se rechaza."""
    if not media.ffprobe_available():
        log.error("ffprobe no está instalado: no se puede validar la duración del audio")
        raise HTTPException(503, "No se pudo revisar el audio. Intenta de nuevo más tarde.")
    try:
        return await run_in_threadpool(media.audio_duration, path)
    except ValueError as exc:
        log.info("Audio ilegible (%s): %s", path.name, exc)
        raise HTTPException(415, "No se pudo leer el audio. Revisa que el archivo no esté dañado.")


# --- Crear el trabajo
@app.post("/api/jobs", status_code=202)
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    preset: str = Form(config.DEFAULT_PRESET),
    stems: str = Form(""),
    usuario: Optional[Usuario] = Depends(usuario_opcional),
):
    """`stems`: pistas separadas por comas; vacío = todas."""
    if preset not in config.PRESETS:
        raise HTTPException(400, f"Preset inválido. Opciones: {', '.join(config.PRESETS)}.")
    available = config.PRESETS[preset]["stems"]
    wanted = [s.strip().lower() for s in stems.split(",") if s.strip()] or list(available)
    unknown = [s for s in wanted if s not in available]
    if unknown:
        raise HTTPException(400, f"Pistas no disponibles para '{preset}': {', '.join(unknown)}. Disponibles: {', '.join(available)}.")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in config.ALLOWED_INPUT_EXT:
        raise HTTPException(415, f"Tipo de archivo no soportado. Acepta: {', '.join(sorted(config.ALLOWED_INPUT_EXT))}.")

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > config.MAX_UPLOAD_BYTES + 1024 * 1024:
        raise HTTPException(413, f"El archivo supera el límite de {config.MAX_UPLOAD_MB} MB.")

    ip = invitados.ip_de(request)
    if usuario is not None:
        await run_in_threadpool(cuotas.verificar_cantidad, usuario.id, preset)
    else:
        invitados.verificar_preset(preset)
        invitados.reservar(ip)

    def liberar_limites() -> None:
        # Un archivo rechazado no cuenta.
        daily_limiter.release(ALL_USERS)
        if usuario is None:
            invitados.liberar(ip)

    wait = daily_limiter.acquire(ALL_USERS)
    if wait:
        if usuario is None:
            invitados.liberar(ip)
        hours = max(1, round(wait / 3600))
        raise HTTPException(
            429,
            f"La página llegó a su límite de {config.MAX_JOBS_PER_DAY} trabajos por día. "
            f"Intenta de nuevo en {hours} h.",
            headers={"Retry-After": str(int(wait) + 1)},
        )

    job_id, job_dir = manager.new_job_dir()
    input_path = job_dir / f"input{ext}"
    size = 0
    try:
        with open(input_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"El archivo supera el límite de {config.MAX_UPLOAD_MB} MB.")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "El archivo está vacío.")
        seconds = await _audio_seconds(input_path)
        if usuario is not None:
            await run_in_threadpool(cuotas.verificar_audio, usuario.id, seconds)
        else:
            invitados.verificar_audio(seconds)

        job = Job(
            id=job_id,
            usuario_id=usuario.id if usuario is not None else None,
            original_name=_safe_base_name(file.filename or "audio"),
            preset=preset,
            wanted_stems=wanted,
            input_path=input_path,
            out_dir=job_dir / "out",
            size_bytes=size,
            duration_seconds=seconds,
        )
        await run_in_threadpool(manager.submit, job)
    except queue.Full:
        shutil.rmtree(job_dir, ignore_errors=True)
        liberar_limites()
        raise HTTPException(503, "El servicio está muy ocupado. Intenta de nuevo en unos minutos.")
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        liberar_limites()
        raise
    return _public(job)


# --- Estado y progreso
@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, usuario: Optional[Usuario] = Depends(usuario_opcional)):
    return _public(_job_del_solicitante(job_id, usuario))


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    """SSE: manda el trabajo cada vez que cambia."""
    await run_in_threadpool(_job_or_404, job_id)

    async def stream():
        last_version = -1
        last_pos: Optional[int] = None
        last_beat = time.time()
        while True:
            if await request.is_disconnected():
                return
            job = await run_in_threadpool(manager.get, job_id)
            if job is None:
                yield "event: gone\ndata: {}\n\n"
                return
            pos = manager.queue_position(job_id)
            # Uno terminado puede venir de la base, sin contador de versión.
            if job.version != last_version or pos != last_pos or job.status in (DONE, ERROR):
                last_version, last_pos = job.version, pos
                yield f"event: update\ndata: {json.dumps(_public(job))}\n\n"
                last_beat = time.time()
                if job.status in (DONE, ERROR):
                    return
            elif time.time() - last_beat > 15:
                yield ": keep-alive\n\n"
                last_beat = time.time()
            await asyncio.sleep(0.4)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Vista previa y descargas
@app.get("/api/jobs/{job_id}/stems/{stem}/preview")
async def stem_preview(job_id: str, stem: str):
    """MP3 liviano para escuchar en la página."""
    job = await run_in_threadpool(_job_or_404, job_id)
    path = _stem_path(job, stem)
    try:
        mp3 = await run_in_threadpool(media.convert, path, "mp3", preview=True)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    return FileResponse(mp3, media_type="audio/mpeg")


# Con prepare=1 solo se convierte (queda en caché); la página muestra "Preparando…" y luego descarga.
@app.get("/api/jobs/{job_id}/stems/{stem}/download")
async def stem_download(job_id: str, stem: str, format: str = "wav", prepare: bool = False):
    job = await run_in_threadpool(_job_or_404, job_id)
    fmt = _check_format(format)
    path = _stem_path(job, stem)
    try:
        out = await run_in_threadpool(media.convert, path, fmt)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    if prepare:
        return {"ready": True}
    return FileResponse(
        out,
        media_type=config.OUTPUT_FORMATS[fmt],
        filename=f"{job.original_name} - {stem}.{fmt}",
    )


@app.get("/api/jobs/{job_id}/download")
async def download_all(job_id: str, format: str = "wav", prepare: bool = False):
    job = await run_in_threadpool(_job_or_404, job_id)
    fmt = _check_format(format)
    if job.status != DONE:
        raise HTTPException(409, "El trabajo todavía no termina.")
    try:
        zip_path = await run_in_threadpool(media.build_zip, job.stem_files, fmt, job.original_name, job.out_dir)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    if prepare:
        return {"ready": True}
    return FileResponse(zip_path, media_type="application/zip", filename=f"{job.original_name} - splitter.zip")


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, usuario: Optional[Usuario] = Depends(usuario_opcional)):
    _job_del_solicitante(job_id, usuario)
    manager.delete(job_id)


# --- La página: splitter/frontend, o la carpeta de SPLITTER_FRONTEND_DIR
_frontend = os.getenv("SPLITTER_FRONTEND_DIR") or str(Path(__file__).resolve().parent.parent / "frontend")
if Path(_frontend).is_dir():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
