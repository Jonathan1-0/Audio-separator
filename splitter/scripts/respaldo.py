"""Respaldo de la base en un archivo JSON comprimido (sirve para MySQL y SQLite).

    .venv/bin/python -m scripts.respaldo guardar                 -> respaldos/splitter-AAAAMMDD-HHMM.json.gz
    .venv/bin/python -m scripts.respaldo guardar --dias 30       además borra los de más de 30 días
    .venv/bin/python -m scripts.respaldo restaurar ARCHIVO       solo en una base vacía (recién migrada)

Aiven también guarda respaldos automáticos; este es una copia propia, fuera de Aiven.
Los audios no se respaldan: duran horas o días y se pueden volver a generar.
Para hacerlo cada noche (cron, 3:00 a. m.):
    0 3 * * * cd /ruta/splitter && .venv/bin/python -m scripts.respaldo guardar --dias 30
"""
import argparse
import gzip
import json
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app import config
from app.database import Base, SessionLocal
from app.models import tablas  # noqa: F401  registra las tablas
from app.seed import migrar

CARPETA = config.BASE_DIR / "respaldos"
# En orden: primero las tablas de las que dependen las demás
TABLAS = ["usuarios", "planes", "sesiones", "suscripciones", "metodos_pago", "pagos", "trabajos", "resultados"]


def _a_json(valor):
    if isinstance(valor, (datetime, date)):
        return {"__fecha__": valor.isoformat()}
    if isinstance(valor, Decimal):
        return {"__decimal__": str(valor)}
    return valor


def _de_json(valor):
    if isinstance(valor, dict) and "__fecha__" in valor:
        return datetime.fromisoformat(valor["__fecha__"])
    if isinstance(valor, dict) and "__decimal__" in valor:
        return Decimal(valor["__decimal__"])
    return valor


def guardar(dias: int = 0) -> Path:
    CARPETA.mkdir(exist_ok=True)
    datos = {"creado": datetime.now().isoformat(timespec="seconds"), "tablas": {}}
    with SessionLocal() as db:
        for nombre in TABLAS:
            tabla = Base.metadata.tables[nombre]
            filas = db.execute(select(tabla)).mappings().all()
            datos["tablas"][nombre] = [{k: _a_json(v) for k, v in fila.items()} for fila in filas]
    destino = CARPETA / f"splitter-{datetime.now():%Y%m%d-%H%M}.json.gz"
    with gzip.open(destino, "wt", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)
    destino.chmod(0o600)  # tiene correos y hashes de contraseñas
    total = sum(len(v) for v in datos["tablas"].values())
    print(f"Respaldo guardado: {destino} ({total} filas)")
    if dias > 0:
        limite = time.time() - dias * 86400
        for viejo in CARPETA.glob("splitter-*.json.gz"):
            if viejo.stat().st_mtime < limite:
                viejo.unlink()
                print(f"Borrado por viejo: {viejo.name}")
    return destino


def restaurar(archivo: Path) -> None:
    migrar()
    with gzip.open(archivo, "rt", encoding="utf-8") as f:
        datos = json.load(f)
    with SessionLocal() as db:
        ocupadas = [n for n in TABLAS if n != "planes" and db.scalar(select(func.count()).select_from(Base.metadata.tables[n]))]
        if ocupadas:
            raise SystemExit(f"La base no está vacía ({', '.join(ocupadas)}). Restaura en una base nueva.")
        db.execute(Base.metadata.tables["planes"].delete())
        for nombre in TABLAS:
            filas = [{k: _de_json(v) for k, v in fila.items()} for fila in datos["tablas"].get(nombre, [])]
            if filas:
                db.execute(Base.metadata.tables[nombre].insert(), filas)
        db.commit()
    print(f"Restaurado desde {archivo}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="accion", required=True)
    g = sub.add_parser("guardar")
    g.add_argument("--dias", type=int, default=0, help="borrar respaldos de más de N días")
    r = sub.add_parser("restaurar")
    r.add_argument("archivo", type=Path)
    args = parser.parse_args()
    if args.accion == "guardar":
        guardar(args.dias)
    else:
        restaurar(args.archivo)
