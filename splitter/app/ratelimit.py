"""Límite de eventos por clave en un periodo de tiempo."""
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
        # Archivo donde se guarda la cuenta (opcional)
        self.path = path
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._load()

    def acquire(self, key: str) -> float:
        """Devuelve 0 si hay lugar, o los segundos que faltan."""
        if self.max_events <= 0:
            return 0.0
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

    def espera(self, key: str) -> float:
        """Como acquire, pero sin contar un evento: 0 si hay lugar."""
        if self.max_events <= 0:
            return 0.0
        now = time.time()
        with self._lock:
            events = self._events.get(key)
            if not events:
                return 0.0
            while events and now - events[0] >= self.window:
                events.popleft()
            if len(events) >= self.max_events:
                return min(self.window, self.window - (now - events[0]))
            return 0.0

    def limpiar(self, key: str) -> None:
        """Olvida los eventos de esa clave."""
        with self._lock:
            if self._events.pop(key, None) is not None:
                self._save()

    def release(self, key: str) -> None:
        """Deshace la última reserva."""
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
        if self.path is None:
            return
        now = time.time()
        data = {k: list(v) for k, v in self._events.items() if v and now - v[-1] < self.window}
        tmp = self.path.with_name(self.path.name + ".part")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("No se pudo guardar %s: %s", self.path, exc)
