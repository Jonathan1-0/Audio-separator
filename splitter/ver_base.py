"""Visor local de solo lectura de la base. Uso: python ver_base.py y abrir http://127.0.0.1:8770/"""
import html
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sqlalchemy import inspect, text

from app.database import ES_SQLITE, db_engine

TABLAS = ["usuarios", "sesiones", "planes", "suscripciones", "metodos_pago", "pagos", "trabajos", "resultados"]
OCULTAS = {"password_hash", "token", "token_pasarela"}
MAX_FILAS = 200

ESTILO = """
body { margin:0 auto; max-width:1100px; padding:20px 16px; background:#14161a; color:#e6e8eb; font:15px system-ui; }
h1 { font-size:24px; margin:0; } h2 { font-size:17px; }
h2 span, .nota { color:#9097a1; font-weight:400; font-size:13px; }
nav { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0; }
a { color:#5b9dff; text-decoration:none; border:1px solid #2e323a; border-radius:6px; padding:4px 10px; }
section { background:#1d2026; border:1px solid #2e323a; border-radius:10px; padding:4px 16px 14px; margin-top:14px; }
table { border-collapse:collapse; font-size:13px; }
th, td { border:1px solid #2e323a; padding:5px 8px; text-align:left; white-space:nowrap; }
th { background:#262a31; } .datos { overflow-x:auto; } summary { cursor:pointer; color:#9097a1; margin:8px 0; }
"""


def _celda(columna: str, valor) -> str:
    """Texto de una celda; los datos sensibles no se muestran."""
    if columna in OCULTAS:
        return "<td>••••</td>"
    return f"<td>{'' if valor is None else html.escape(str(valor))}</td>"


def _estructura(inspector, tabla: str) -> str:
    """Tabla con las columnas, sus tipos y sus llaves."""
    pk = inspector.get_pk_constraint(tabla)["constrained_columns"]
    fk = {
        c: f'{f["referred_table"]}.{f["referred_columns"][0]}'
        for f in inspector.get_foreign_keys(tabla)
        for c in f["constrained_columns"]
    }
    filas = ""
    for col in inspector.get_columns(tabla):
        nombre = col["name"]
        llave = "PK" if nombre in pk else f"→ {fk[nombre]}" if nombre in fk else ""
        filas += f'<tr><td>{nombre}</td><td>{col["type"]}</td><td>{llave}</td></tr>'
    return f"<table><tr><th>Columna</th><th>Tipo</th><th>Llave</th></tr>{filas}</table>"


def _seccion(conexion, inspector, tabla: str) -> tuple[str, int]:
    """Arma el bloque de una tabla y devuelve también su número de filas."""
    total = conexion.scalar(text(f"select count(*) from {tabla}"))
    columnas = [c["name"] for c in inspector.get_columns(tabla)]
    filas = conexion.execute(text(f"select * from {tabla} limit {MAX_FILAS}")).mappings().all()
    if filas:
        cabecera = "".join(f"<th>{c}</th>" for c in columnas)
        cuerpo = "".join("<tr>" + "".join(_celda(c, f[c]) for c in columnas) + "</tr>" for f in filas)
        datos = f'<div class="datos"><table><tr>{cabecera}</tr>{cuerpo}</table></div>'
    else:
        datos = '<p class="nota">Tabla vacía.</p>'
    bloque = (
        f'<section id="{tabla}"><h2>{tabla} <span>{total} fila(s)</span></h2>{datos}'
        f"<details><summary>Estructura</summary>{_estructura(inspector, tabla)}</details></section>"
    )
    return bloque, total


def _pagina() -> str:
    """Lee la base y arma la página completa."""
    inspector = inspect(db_engine)
    with db_engine.connect() as conexion:
        if not ES_SQLITE:
            conexion.execute(text("SET SESSION TRANSACTION READ ONLY"))
            conexion.rollback()
        partes = [(t, *_seccion(conexion, inspector, t)) for t in TABLAS]
    menu = "".join(f'<a href="#{t}">{t} ({n})</a>' for t, _, n in partes)
    hora = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    nota = f"{db_engine.dialect.name} · solo lectura · hasta {MAX_FILAS} filas por tabla · leído a las {hora}"
    return f'<h1>Base de datos de Splitter</h1><p class="nota">{nota}</p><nav>{menu}</nav>' + "".join(
        bloque for _, bloque, _ in partes
    )


class Visor(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        """No escribe cada petición en la terminal."""

    def do_GET(self) -> None:
        """Responde con la página; un error solo muestra su tipo, nunca la conexión."""
        try:
            cuerpo, codigo = _pagina(), 200
        except Exception as exc:  # noqa: BLE001
            cuerpo, codigo = f"<h1>No se pudo leer la base</h1><p>{type(exc).__name__}</p>", 500
        pagina = f'<!doctype html><meta charset="utf-8"><title>Base Splitter</title><style>{ESTILO}</style>{cuerpo}'
        datos = pagina.encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)


if __name__ == "__main__":
    print("Abre http://127.0.0.1:8770/ (Ctrl+C para cerrar)")
    ThreadingHTTPServer(("127.0.0.1", 8770), Visor).serve_forever()
