"""Motores de separación: Modal, real (dentro de Modal) y de prueba."""
from __future__ import annotations

import logging
import math
import struct
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Dict, Optional

from . import config

log = logging.getLogger("splitter.engine")

ProgressCb = Callable[[float], None]  # 0 a 1

# La librería usa barras de tqdm; se leen para saber el avance
_local = threading.local()


def _report(fraction: float) -> None:
    """Junta las barras de demucs en un solo avance de 0 a 1."""
    cb: Optional[ProgressCb] = getattr(_local, "cb", None)
    if cb is None:
        return
    if getattr(_local, "bars", None) is None:
        fn = getattr(_local, "bars_fn", None)
        _local.bars = fn() if fn else 1
    done = min(getattr(_local, "bars_done", 0), _local.bars - 1)
    cb(max(0.0, min(1.0, (done + fraction) / _local.bars)))


def _bar_finished() -> None:
    _local.bars_done = getattr(_local, "bars_done", 0) + 1


def _make_hooked_tqdm():
    from tqdm import tqdm

    class HookedTqdm(tqdm):
        def __iter__(self):
            total = self.total
            for i, item in enumerate(super().__iter__(), start=1):
                yield item
                if total:
                    _report(i / total)
            _bar_finished()

        def update(self, n=1):
            result = super().update(n)
            if self.total:
                _report(self.n / self.total)
            return result

    return HookedTqdm


_patched = False


def _patch_tqdm() -> None:
    global _patched
    if _patched:
        return
    hooked = _make_hooked_tqdm()
    for modname in (
        "audio_separator.separator.architectures.mdxc_separator",
        "audio_separator.separator.architectures.mdx_separator",
        "audio_separator.separator.architectures.vr_separator",
        "audio_separator.separator.architectures.demucs_separator",
        "audio_separator.separator.uvr_lib_v5.demucs.apply",
        "demucs.apply",
    ):
        try:
            mod = __import__(modname, fromlist=["tqdm"])
        except Exception:
            continue
        current = getattr(mod, "tqdm", None)
        if current is None:
            continue
        if hasattr(current, "tqdm"):
            current.tqdm = hooked
        else:
            setattr(mod, "tqdm", hooked)
    _patched = True


def _stem_from_filename(path: str, known: list[str]) -> Optional[str]:
    """'x_(Vocals)_modelo.wav' -> 'vocals'."""
    name = Path(path).stem.lower()
    for stem in known:
        if f"({stem})" in name or name == stem or name.endswith(f"_{stem}"):
            return stem
    return None


def _guardar_modelos_demucs() -> None:
    """audio-separator vuelve a leer el modelo de Demucs del disco en cada audio y lo borra al terminar.
    Aquí se guarda el modelo ya cargado y se reutiliza mientras el contenedor siga encendido
    (Modal lo apaga a los 2 minutos sin trabajo, y el modelo se va con él: no cuesta más)."""
    try:
        from audio_separator.separator.architectures import demucs_separator as ds
    except ImportError:  # fuera de Modal no está instalado
        return
    if getattr(ds, "_splitter_modelos", None) is not None:
        return
    original = ds.get_demucs_model
    modelos: Dict[tuple, object] = {}

    def get_model(name, repo=None):
        clave = (name, str(repo))
        if clave not in modelos:
            log.info("Cargando modelo de Demucs %s (se queda en memoria)", name)
            modelos[clave] = original(name=name, repo=repo)
        return modelos[clave]

    ds.get_demucs_model = get_model
    ds._splitter_modelos = modelos


class RealEngine:
    """Corre dentro de Modal."""

    def __init__(self) -> None:
        # Cada modelo se carga una sola vez
        self._seps: Dict[str, object] = {}
        self.last_timings: Dict[str, float] = {}
        _guardar_modelos_demucs()

    def device_info(self) -> dict:
        info = {"engine": "real", "cuda": False, "device": "cpu"}
        try:
            import torch

            if torch.cuda.is_available():
                info.update(cuda=True, device=torch.cuda.get_device_name(0))
        except Exception:
            pass
        return info

    def _separator(self, model: str, out_dir: Path, autocast: bool = False, demucs: Optional[dict] = None):
        # Un mismo modelo con otras pasadas (calidad) es otro separador
        clave = f"{model}|{sorted((demucs or {}).items())}"
        sep = self._seps.get(clave)
        if sep is None:
            from audio_separator.separator import Separator

            config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
            sep = Separator(
                model_file_dir=str(config.MODEL_DIR),
                output_dir=str(out_dir),
                output_format="WAV",
                log_level=logging.INFO,
                use_autocast=autocast,
                mdxc_params={
                    "segment_size": 256,
                    "override_model_segment_size": False,
                    "batch_size": None,
                    "overlap": config.MDXC_OVERLAP,
                    "pitch_shift": 0,
                },
                demucs_params={"segment_size": "Default", "shifts": 2, "overlap": 0.25, "segments_enabled": True, **(demucs or {})},
            )
            log.info("Cargando modelo %s (autocast=%s, demucs=%s)", model, autocast, demucs)
            sep.load_model(model_filename=model)
            self._seps[clave] = sep
        sep.output_dir = str(out_dir)
        if getattr(sep, "model_instance", None) is not None:
            sep.model_instance.output_dir = str(out_dir)
        return sep

    @staticmethod
    def _expected_bars(sep) -> int:
        """Cuántas barras hará demucs."""
        inst = getattr(sep, "model_instance", None)
        demucs = getattr(inst, "demucs_model_instance", None)
        if demucs is None:
            return 1
        return max(1, len(getattr(demucs, "models", ()))) * max(1, getattr(inst, "shifts", 1))

    def _run_model(
        self, model: str, autocast: bool, input_path: Path, out_dir: Path,
        names: Dict[str, str], on_progress: ProgressCb, timings: Dict[str, float],
        demucs: Optional[dict] = None,
    ) -> Dict[str, Path]:
        """Separa y renombra las pistas según `names`."""
        t0 = time.perf_counter()
        sep = self._separator(model, out_dir, autocast, demucs)
        t1 = time.perf_counter()
        inst = sep.model_instance
        # El modelo se comparte: se cambia para este trabajo y se restaura
        inst.output_single_stem = next(iter(names)) if len(names) == 1 else None
        _local.cb, _local.bars_fn, _local.bars, _local.bars_done = on_progress, lambda: self._expected_bars(sep), None, 0
        try:
            produced = sep.separate(str(input_path), custom_output_names=names)
        finally:
            _local.cb = None
            inst.output_single_stem = None
        timings["load_seconds"] = timings.get("load_seconds", 0.0) + t1 - t0
        timings["separate_seconds"] = timings.get("separate_seconds", 0.0) + time.perf_counter() - t1

        result: Dict[str, Path] = {}
        for p in produced:
            path = Path(p)
            if not path.is_absolute():
                path = out_dir / path.name if not path.exists() else path
            stem = _stem_from_filename(str(path), list(names.values()))
            if stem and path.exists():
                result[stem] = path
        return result

    def separate(self, input_path: Path, out_dir: Path, preset: str, on_progress: ProgressCb) -> Dict[str, Path]:
        spec = config.PRESETS[preset]
        out_dir.mkdir(parents=True, exist_ok=True)
        _patch_tqdm()
        timings: Dict[str, float] = {}
        if "steps" in spec:
            result = self._separate_steps(spec, input_path, out_dir, on_progress, timings)
        else:
            names = {s: s for s in spec["stems"]}
            result = self._run_model(
                spec["model"], spec.get("autocast", False), input_path, out_dir, names, on_progress, timings,
                spec.get("demucs"),
            )
        self.last_timings = timings
        if not result:
            raise RuntimeError("El modelo no produjo ningún archivo de salida reconocible.")
        return result

    def _separate_steps(
        self, spec: dict, input_path: Path, out_dir: Path, on_progress: ProgressCb, timings: Dict[str, float]
    ) -> Dict[str, Path]:
        """Varios modelos seguidos; cada uno recibe una pista del anterior."""
        steps = spec["steps"]
        produced: Dict[str, Path] = {}
        for i, step in enumerate(steps):
            src = input_path if i == 0 else produced[step["input"]]

            def progress(f: float, i: int = i) -> None:
                on_progress((i + f) / len(steps))

            produced.update(self._run_model(
                step["model"], step.get("autocast", False), src, out_dir, step["stems"], progress, timings
            ))

        result = {s: produced[s] for s in spec["stems"] if s in produced}
        for name, path in produced.items():
            if name not in result:
                path.unlink(missing_ok=True)
        return result


def gpu_seconds_del_hilo() -> Optional[float]:
    """Segundos de GPU del último trabajo."""
    return getattr(_local, "gpu_seconds", None)


class SeparationError(RuntimeError):
    """Error con un mensaje que se puede mostrar al usuario."""


def _friendly_modal_error(exc: BaseException) -> str:
    import modal.exception as me

    text = str(exc).lower()
    if isinstance(exc, me.ResourceExhaustedError) or any(
        w in text for w in ("billing", "spend limit", "credit", "quota")
    ):
        return "El servicio de separación llegó a su límite de uso. Intenta de nuevo más tarde."
    if isinstance(exc, (me.TimeoutError, TimeoutError)):
        return "El audio tardó demasiado en procesarse. Prueba con un archivo más corto."
    if isinstance(exc, me.RequestSizeError):
        return "El archivo es demasiado grande para el servicio de separación. Prueba con uno más pequeño."
    if isinstance(exc, (me.NotFoundError, me.AuthError, me.PermissionDeniedError)):
        return "El servicio de separación no está disponible en este momento."
    if isinstance(exc, (me.ConnectionError, me.ServiceError, me.InternalError, me.InternalFailure, ConnectionError)):
        return "No se pudo conectar con el servicio de separación. Intenta de nuevo en unos minutos."
    return "No se pudo procesar el audio. Si el archivo se reproduce bien, intenta de nuevo más tarde."


class ModalEngine:
    """Separa en la GPU de Modal."""

    SEPARATION_SHARE = 0.7  # el resto de la barra es la descarga
    parallel_jobs = config.PARALLEL_JOBS
    waits_for_gpu = True

    def __init__(self, app_name: Optional[str] = None, app_pro: Optional[str] = None) -> None:
        import modal

        self.app_name = app_name or config.MODAL_APP
        self.app_pro = config.MODAL_APP_PRO if app_pro is None else app_pro
        self._cls = modal.Cls.from_name(self.app_name, "Separator")
        self._cls_pro = (
            modal.Cls.from_name(self.app_pro, "Separator") if self.app_pro and self.app_pro != self.app_name else None
        )

    def device_info(self) -> dict:
        gpu = self.app_name.rsplit("-", 1)[-1].upper() if self.app_name.startswith("splitter-gpu-") else "GPU"
        return {"engine": "modal", "cuda": True, "device": f"NVIDIA {gpu} (Modal: {self.app_name})"}

    def _wait(self, call, progress, app_name: str, preset: str, on_progress: ProgressCb) -> dict:
        """Espera el resultado. Si la GPU no llega a tiempo, cancela."""
        limit = config.MODAL_START_MINUTES * 60  # 0 = sin límite
        deadline = time.monotonic() + limit
        started = False
        while True:
            try:
                return call.get(timeout=1)
            except TimeoutError:
                pass
            while (item := progress.get(block=False)) is not None:
                started = True
                on_progress(item["value"] * self.SEPARATION_SHARE)
            if not started and limit and time.monotonic() > deadline:
                call.cancel()
                log.error("Modal %s (%s): sin GPU tras %s min; llamada cancelada", app_name, preset,
                          config.MODAL_START_MINUTES)
                raise SeparationError("No hay GPU disponible en este momento. Intenta de nuevo en unos minutos.")

    def separate(
        self, input_path: Path, out_dir: Path, preset: str, on_progress: ProgressCb, prioritario: bool = False
    ) -> Dict[str, Path]:
        """prioritario: Pro y admin, que van a la GPU rápida (MODAL_APP_PRO)."""
        import subprocess

        import modal

        _local.gpu_seconds = None
        out_dir.mkdir(parents=True, exist_ok=True)
        result: Dict[str, Path] = {}
        n_stems = len(config.PRESETS[preset]["stems"])
        audio = input_path.read_bytes()
        started = time.perf_counter()
        try:
            with modal.Queue.ephemeral() as progress:
                app_name, cls = self.app_name, self._cls
                if prioritario and self._cls_pro is not None:
                    app_name, cls = self.app_pro, self._cls_pro
                try:
                    call = cls().separate.spawn(audio, input_path.name, preset, progress.object_id)
                except modal.exception.NotFoundError:
                    if cls is self._cls:
                        raise
                    log.warning("Modal %s no está desplegada; se usa %s", app_name, self.app_name)
                    app_name = self.app_name
                    call = self._cls().separate.spawn(audio, input_path.name, preset, progress.object_id)
                output = self._wait(call, progress, app_name, preset, on_progress)
            for stem, data in output["stems"].items():
                flac = out_dir / f"{stem}.flac"
                flac.write_bytes(data)
                # Llegan en FLAC y se pasan a WAV
                wav = out_dir / f"{stem}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", str(flac), "-c:a", "pcm_s16le", str(wav)],
                    check=True,
                )
                flac.unlink()
                result[stem] = wav
                on_progress(self.SEPARATION_SHARE + (1 - self.SEPARATION_SHARE) * len(result) / n_stems)
        except SeparationError:
            raise
        except Exception as exc:
            raise SeparationError(_friendly_modal_error(exc)) from exc
        if not result:
            log.error("Modal %s (%s) terminó sin devolver pistas", app_name, preset)
            raise SeparationError(_friendly_modal_error(RuntimeError("sin pistas")))
        stats = dict(output.get("stats", {}))
        stats.update(
            wall_seconds=time.perf_counter() - started,
            bytes_sent=len(audio),
            bytes_received=sum(len(d) for d in output["stems"].values()),
        )
        log.info("Modal %s (%s): %s", app_name, preset, stats)
        _local.gpu_seconds = stats.get("gpu_seconds")
        return result


class FakeEngine:
    """Simula la separación con tonos."""

    parallel_jobs = config.PARALLEL_JOBS

    def device_info(self) -> dict:
        return {"engine": "fake", "cuda": False, "device": "simulado"}

    def separate(
        self, input_path: Path, out_dir: Path, preset: str, on_progress: ProgressCb, prioritario: bool = False
    ) -> Dict[str, Path]:
        spec = config.PRESETS[preset]
        out_dir.mkdir(parents=True, exist_ok=True)
        steps = 20
        for i in range(1, steps + 1):
            time.sleep(0.1)
            on_progress(i / steps)
        result: Dict[str, Path] = {}
        for idx, stem in enumerate(spec["stems"]):
            path = out_dir / f"{stem}.wav"
            freq = 220 * (idx + 1)
            rate, seconds = 22050, 2
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                frames = b"".join(
                    struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * n / rate)))
                    for n in range(rate * seconds)
                )
                w.writeframes(frames)
            result[stem] = path
        return result


def build_engine():
    if config.ENGINE == "fake":
        return FakeEngine()
    if config.ENGINE == "modal":
        return ModalEngine()
    raise ValueError(f"SPLITTER_ENGINE debe ser 'modal' o 'fake', no {config.ENGINE!r}")
