"""Límite de trabajos por clave en una ventana de tiempo."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, Optional

log = logging.getLogger("splitter.ratelimit")


class RateLimiter:
    def __init__(self, max_events: int, window_seconds: float, path: Optional[Path] = None) -> None:
        self.max_events = max_events  # 0 = sin límite
        self.window = window_seconds
        # Si se da, la cuenta se guarda ahí y sobrevive a un reinicio del servidor.
        self.path = path
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._load()

    def acquire(self, key: str) -> float:
        """Devuelve 0 si hay lugar (y lo reserva) o los segundos que faltan para que se libere uno.
        Se reserva antes de subir para que dos subidas a la vez no pasen las dos."""
        if self.max_events <= 0:
            return 0.0
        # Hora real y no monotonic: tiene que seguir valiendo después de reiniciar.
        now = time.time()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.max_events:
                return min(self.window, self.window - (now - events[0]))
            events.append(now)
            self._save()
            return 0.0

    def release(self, key: str) -> None:
        """Deshace la última reserva: una subida rechazada no cuenta."""
        if self.max_events <= 0:
            return
        with self._lock:
            events = self._events.get(key)
            if events:
                events.pop()
            if not events:
                self._events.pop(key, None)
            self._save()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            now = time.time()
            for key, stamps in data.items():
                kept = sorted(float(t) for t in stamps if now - float(t) < self.window)
                if kept:
                    self._events[key] = deque(kept)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            log.warning("No se pudo leer %s, los límites empiezan de cero: %s", self.path, exc)

    def _save(self) -> None:
        """Se llama con el lock tomado."""
        if self.path is None:
            return
        now = time.time()
        # Las claves sin eventos vigentes no se guardan, para que el archivo no crezca con cada IP.
        data = {k: list(v) for k, v in self._events.items() if v and now - v[-1] < self.window}
        tmp = self.path.with_name(self.path.name + ".part")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("No se pudo guardar %s: %s", self.path, exc)
