"""Mantiene encendida la base gratis de Aiven.

Aiven apaga los servicios gratis que pasan un tiempo sin actividad. Este script:
  - si la base está apagada, la vuelve a encender (y espera a que acepte conexiones);
  - si está encendida, hace una consulta mínima para que cuente como actividad.

    .venv/bin/python -m scripts.aiven_encender            una revisión (para cron)
    .venv/bin/python -m scripts.aiven_encender --estado   solo dice cómo está

Necesita en .env:
    AIVEN_TOKEN=...        token de la API (Aiven Console > User information > Tokens)
    AIVEN_PROYECTO=...     nombre del proyecto en Aiven
    AIVEN_SERVICIO=...     nombre del servicio de PostgreSQL

Cada 10 minutos con cron (crontab -e):
    */10 * * * * cd /ruta/splitter && .venv/bin/python -m scripts.aiven_encender >> data/aiven_encender.log 2>&1
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError

from app import config

load_dotenv(config.BASE_DIR / ".env")

API = "https://api.aiven.io/v1"
ESPERA_MAX = 15 * 60  # encender una base gratis tarda unos minutos


def _log(mensaje: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {mensaje}", flush=True)


def _llamar(metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
    token = os.getenv("AIVEN_TOKEN", "")
    peticion = urllib.request.Request(
        f"{API}{ruta}",
        method=metodo,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        headers={"Authorization": f"aivenv1 {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        return json.load(respuesta)


def _ruta_servicio() -> str:
    faltan = [v for v in ("AIVEN_TOKEN", "AIVEN_PROYECTO", "AIVEN_SERVICIO") if not os.getenv(v)]
    if faltan:
        raise SystemExit(f"Faltan en .env: {', '.join(faltan)}")
    return f"/project/{os.environ['AIVEN_PROYECTO']}/service/{os.environ['AIVEN_SERVICIO']}"


def estado() -> str:
    """RUNNING, POWEROFF, REBUILDING o REBALANCING."""
    return _llamar("GET", _ruta_servicio())["service"]["state"]


def encender() -> None:
    _llamar("PUT", _ruta_servicio(), {"powered": True})


def _tocar_base() -> None:
    """Una consulta mínima: cuenta como actividad para Aiven."""
    from sqlalchemy import text

    from app.database import db_engine

    with db_engine.connect() as conexion:
        conexion.execute(text("SELECT 1"))


def revisar() -> int:
    actual = estado()
    if actual == "POWEROFF":
        _log("La base estaba apagada: encendiéndola")
        encender()
        limite = time.monotonic() + ESPERA_MAX
        while (actual := estado()) != "RUNNING":
            if time.monotonic() > limite:
                _log(f"Pasaron {ESPERA_MAX // 60} minutos y sigue en {actual}")
                return 1
            time.sleep(20)
        _log("La base ya está encendida")
    elif actual != "RUNNING":
        _log(f"La base está en {actual} (Aiven la está preparando); se revisa en la próxima vuelta")
        return 0
    try:
        _tocar_base()
    except OperationalError as error:  # recién encendida puede tardar un poco más en aceptar conexiones
        _log(f"La base está en RUNNING pero no respondió: {error}")
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--estado", action="store_true", help="solo mostrar el estado, sin cambiar nada")
    args = parser.parse_args()
    try:
        if args.estado:
            print(estado())
            sys.exit(0)
        sys.exit(revisar())
    except urllib.error.HTTPError as error:
        _log(f"Aiven respondió {error.code}: {error.read().decode(errors='replace')[:300]}")
        sys.exit(1)
    except urllib.error.URLError as error:
        _log(f"No se pudo hablar con Aiven: {error.reason}")
        sys.exit(1)
