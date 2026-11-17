"""Pruebas en un navegador real (Playwright).

Levanta su propio servidor con una base SQLite temporal y el motor simulado, así que
no toca ninguna base real. Para correrlas:

    .venv/bin/pytest e2e            (usa Chrome si está instalado; si no, el Chromium de Playwright)
    .venv/bin/playwright install chromium   (solo si no tienes Chrome)
"""
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
ADMIN = ("admin@e2e.test", "admin-e2e-clave-1")


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def servidor():
    tmp = Path(tempfile.mkdtemp(prefix="splitter_e2e_"))
    puerto = _puerto_libre()
    entorno = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp / 'e2e.db'}",
        "SPLITTER_DATA_DIR": str(tmp / "data"),
        "SPLITTER_ENGINE": "fake",
        "SPLITTER_SMTP_USER": "",  # los correos salen en el log
        "SPLITTER_SECRET_KEY": "e2e-no-es-secreto",
        "SPLITTER_ADMIN_EMAIL": ADMIN[0],
        "SPLITTER_ADMIN_PASSWORD": ADMIN[1],
        "SPLITTER_PUBLIC_URL": "",
        "SPLITTER_SMTP_PASSWORD": "",
        "SPLITTER_GOOGLE_CLIENT_ID": "",
        "SPLITTER_GOOGLE_CLIENT_SECRET": "",
        "SPLITTER_FACEBOOK_APP_ID": "",
        "SPLITTER_FACEBOOK_APP_SECRET": "",
        "SPLITTER_LOGIN_POR_IP": "1000",
        "SPLITTER_REGISTROS_POR_IP": "1000",
        "SPLITTER_CORREOS_POR_CUENTA": "1000",
        "DB_SSL_CA": "",
    }
    log = open(tmp / "servidor.log", "w")
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(puerto)],
        cwd=RAIZ, env=entorno, stdout=log, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{puerto}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    else:
        proceso.kill()
        raise RuntimeError((tmp / "servidor.log").read_text())
    yield {"url": url, "log": tmp / "servidor.log", "tmp": tmp}
    proceso.terminate()
    proceso.wait(10)
    log.close()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def navegador():
    with sync_playwright() as p:
        chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
        if chrome and not os.environ.get("CI"):
            nav = p.chromium.launch(executable_path=chrome, headless=True)
        else:
            nav = p.chromium.launch(headless=True)
        yield nav
        nav.close()


@pytest.fixture
def pagina(navegador, servidor):
    """Pestaña nueva y limpia. Falla la prueba si la página tuvo errores de JavaScript o de CSP."""
    contexto = navegador.new_context(base_url=servidor["url"], accept_downloads=True, locale="es-MX")
    pag = contexto.new_page()
    pag.servidor = servidor  # para leer los correos del log
    errores = []
    pag.on("pageerror", lambda e: errores.append(f"JS: {e}"))
    pag.on("console", lambda m: errores.append(f"consola: {m.text}") if m.type == "error" and "Content Security Policy" in m.text else None)
    yield pag
    contexto.close()
    assert not errores, errores


@pytest.fixture(scope="session")
def audio_wav(servidor) -> Path:
    ruta = servidor["tmp"] / "tono.wav"
    with wave.open(str(ruta), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(22050)
        f.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(i * 0.05))) for i in range(22050 * 2)))
    return ruta
