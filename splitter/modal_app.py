"""Separación de audio en la GPU de Modal. Para subirlo:
    SPLITTER_GPU=L4 modal deploy modal_app.py   # splitter-gpu-l4
"""
from __future__ import annotations

import os

import modal

SUPPORTED_GPUS = ("T4", "L4")
GPU = os.environ.get("SPLITTER_GPU", "L4").upper()
if GPU not in SUPPORTED_GPUS:
    raise ValueError(f"SPLITTER_GPU debe ser uno de {SUPPORTED_GPUS}, no {GPU!r}")

APP_NAME = f"splitter-gpu-{GPU.lower()}"
# Si no hay L4 libre, usa una T4
GPU_OPTIONS = ["L4", "T4"] if GPU == "L4" else [GPU]
# GPUs a la vez. Igual que SPLITTER_PARALLEL_JOBS
MAX_CONTAINERS = int(os.environ.get("SPLITTER_MAX_CONTAINERS", "3"))
MODEL_DIR = "/models"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    # python-dotenv: app/config.py lo importa al arrancar
    .pip_install("audio-separator[gpu]==0.47.0", "audioread", "python-dotenv")
    # El contenedor necesita las mismas variables que al desplegar
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
    gpu=GPU_OPTIONS,
    volumes={MODEL_DIR: models},
    timeout=20 * 60,
    max_containers=MAX_CONTAINERS,
    # Se apaga a los 2 minutos sin trabajo
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
        """Separa el audio y manda el avance a la cola."""
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
            if fraction - last >= 0.01:
                last = fraction
                progress.put({"value": fraction})

        work = Path(tempfile.mkdtemp())
        try:
            src = work / Path(filename).name
            src.write_bytes(audio)
            files_before = set(os.listdir(MODEL_DIR)) if os.path.isdir(MODEL_DIR) else set()
            files = self.engine.separate(src, work / "out", preset, report)
            if set(os.listdir(MODEL_DIR)) != files_before:
                models.commit()  # guarda el modelo descargado

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
                "gpu": self.engine.device_info().get("device", GPU),
                "gpu_seconds": time.perf_counter() - started,
                "load_seconds": timings["load_seconds"],
                "separate_seconds": timings["separate_seconds"],
            }
            return {"stems": stems, "stats": stats}
        finally:
            # Limpia los temporales del trabajo
            shutil.rmtree(work, ignore_errors=True)
