"""Lo que corre en la GPU de Modal. Cada GPU es una app aparte:

    SPLITTER_GPU=L4 modal deploy modal_app.py   # splitter-gpu-l4
    SPLITTER_GPU=T4 modal deploy modal_app.py   # splitter-gpu-t4

Hay que volver a desplegar cada vez que cambie este archivo o app/.
"""
from __future__ import annotations

import os

import modal

SUPPORTED_GPUS = ("T4", "L4")
GPU = os.environ.get("SPLITTER_GPU", "L4").upper()
if GPU not in SUPPORTED_GPUS:
    raise ValueError(f"SPLITTER_GPU debe ser uno de {SUPPORTED_GPUS}, no {GPU!r}")

APP_NAME = f"splitter-gpu-{GPU.lower()}"
# GPUs encendidas a la vez como máximo. Debe coincidir con SPLITTER_PARALLEL_JOBS.
MAX_CONTAINERS = int(os.environ.get("SPLITTER_MAX_CONTAINERS", "3"))
MODEL_DIR = "/models"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install("audio-separator[gpu]==0.47.0", "audioread")  # librosa 1.0 ya no instala audioread
    # El contenedor vuelve a importar este archivo: necesita las mismas variables que al desplegar.
    .env({
        "SPLITTER_MODEL_DIR": MODEL_DIR,
        "SPLITTER_DATA_DIR": "/tmp/splitter",
        "SPLITTER_GPU": GPU,
        "SPLITTER_MAX_CONTAINERS": str(MAX_CONTAINERS),
        "SPLITTER_AUTOCAST_2STEM": os.environ.get("SPLITTER_AUTOCAST_2STEM", "1"),
        "SPLITTER_MDXC_OVERLAP": os.environ.get("SPLITTER_MDXC_OVERLAP", "4"),
    })
    .add_local_python_source("app")
)

models = modal.Volume.from_name("splitter-models", create_if_missing=True)
app = modal.App(APP_NAME, image=image)


@app.cls(
    gpu=GPU,
    volumes={MODEL_DIR: models},
    timeout=20 * 60,
    max_containers=MAX_CONTAINERS,
    # Se apaga a los 2 min sin trabajo. La espera se cobra; volver a encender tarda ~15-25 s.
    scaledown_window=2 * 60,
)
class Separator:
    @modal.enter()
    def setup(self) -> None:
        from app.engine import RealEngine

        self.engine = RealEngine()

    @modal.method()
    def device_info(self) -> dict:
        return self.engine.device_info()

    @modal.method()
    def separate(self, audio: bytes, filename: str, preset: str, progress_queue_id: str) -> dict:
        """Manda el avance a la cola como {"value": 0..1} y devuelve {"stems": {nombre: FLAC}, "stats"}.
        El primer 0.0 le avisa al backend que ya hay GPU. No es generador para poder cancelarla."""
        import shutil
        import subprocess
        import tempfile
        import time
        from pathlib import Path

        started = time.perf_counter()
        progress = modal.Queue.from_id(progress_queue_id)
        progress.put({"value": 0.0})
        last = 0.0

        def report(fraction: float) -> None:
            nonlocal last
            if fraction - last >= 0.01:  # la cola es remota: no se manda cada paso
                last = fraction
                progress.put({"value": fraction})

        work = Path(tempfile.mkdtemp())
        try:
            src = work / Path(filename).name
            src.write_bytes(audio)
            files_before = set(os.listdir(MODEL_DIR)) if os.path.isdir(MODEL_DIR) else set()
            files = self.engine.separate(src, work / "out", preset, report)
            if set(os.listdir(MODEL_DIR)) != files_before:
                models.commit()  # guarda el modelo recién descargado para los próximos contenedores

            stems = {}
            for stem, wav in files.items():
                flac = wav.with_suffix(".flac")
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "flac", str(flac)],
                    check=True,
                )
                stems[stem] = flac.read_bytes()

            timings = self.engine.last_timings
            stats = {
                "gpu": GPU,
                "gpu_seconds": time.perf_counter() - started,
                "load_seconds": timings["load_seconds"],
                "separate_seconds": timings["separate_seconds"],
            }
            return {"stems": stems, "stats": stats}
        finally:
            # El contenedor atiende varios trabajos seguidos: que no se acumulen en /tmp.
            shutil.rmtree(work, ignore_errors=True)
