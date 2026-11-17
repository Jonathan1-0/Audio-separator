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
# Las pruebas crean muchas cuentas desde la misma IP; los límites se prueban aparte
for _limite in ("LOGIN_POR_IP", "LOGIN_FALLOS_POR_CUENTA", "REGISTROS_POR_IP", "CORREOS_POR_CUENTA"):
    os.environ[f"SPLITTER_{_limite}"] = "100000"
# Vacía (no borrada): si se borra, load_dotenv la vuelve a tomar de .env y las pruebas mandarían correos reales
os.environ["SPLITTER_SMTP_USER"] = ""
os.environ["SPLITTER_SMTP_PASSWORD"] = ""
# Igual con las claves de Google y Facebook de .env: las pruebas usan las suyas
for _clave in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET", "CONTACTO_EMAIL", "PUBLIC_URL"):
    os.environ[f"SPLITTER_{_clave}"] = ""
os.environ.pop("SPLITTER_SENTRY_DSN", None)
# Cuenta de administrador de prueba (no la de .env)
os.environ["SPLITTER_ADMIN_EMAIL"] = "admin@pruebas.com"
os.environ["SPLITTER_ADMIN_PASSWORD"] = "admin-pruebas-1"
# Las pruebas usan el pago simulado para probar Pro
os.environ["SPLITTER_PAGOS_SIMULADOS"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


class _Cliente(TestClient):
    """No guarda la cookie de sesión entre peticiones: cada prueba dice con qué cuenta entra
    (Authorization o la cookie a mano). Las demás cookies (estado de Google) sí se guardan."""

    def request(self, *args, **kwargs):
        self.cookies.delete("splitter_sesion")
        return super().request(*args, **kwargs)


@pytest.fixture(scope="session")
def cliente():
    """Cliente de pruebas; al entrar arranca la app."""
    with _Cliente(app) as c:
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


def registrar(cliente, json):
    """Crea una cuenta como lo hace una persona: registro y luego el código que llega al correo.
    Devuelve la respuesta del registro (o la de error, si el registro falló)."""
    import re
    from unittest import mock

    capturado = {}

    def guardar(destino, asunto, *args, **kwargs):
        encontrado = re.search(r"Tu código de Splitter: (\d{6})", asunto)
        if encontrado:
            capturado["codigo"] = encontrado.group(1)

    with mock.patch("app.services.codigos.correo.enviar_aviso", side_effect=guardar):
        res = cliente.post("/auth/registro", json=json)
    if res.status_code == 201:
        confirmada = cliente.post("/auth/registro/confirmar", json={"pendiente": res.json()["pendiente"], "codigo": capturado["codigo"]})
        assert confirmada.status_code == 200, confirmada.text
    return res
