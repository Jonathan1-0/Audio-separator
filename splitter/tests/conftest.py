"""Preparación de las pruebas: motor simulado y base SQLite temporal."""
import math
import os
import struct
import tempfile
import wave
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="splitter_pruebas_"))
# Se ponen antes de importar la app
os.environ["SPLITTER_ENGINE"] = "fake"
os.environ["SPLITTER_DATA_DIR"] = str(_TMP / "data")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'pruebas.db'}"
os.environ.pop("DB_SSL_CA", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def cliente():
    """Cliente de pruebas; al entrar arranca la app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def audio_wav() -> bytes:
    """Tono de 2 segundos en WAV."""
    ruta = _TMP / "tono.wav"
    with wave.open(str(ruta), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(22050)
        f.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(i * 0.05))) for i in range(22050 * 2)))
    return ruta.read_bytes()
