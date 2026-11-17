"""Cabeceras de seguridad para todas las respuestas.

La Content-Security-Policy solo deja correr scripts de esta página, del CDN de
`motion` y los <script> en línea que ya están en los HTML (por su hash, que se
calcula al arrancar). Un script que alguien lograra inyectar no correría.
"""
import base64
import hashlib
import re
from pathlib import Path
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from . import config

_SCRIPT_EN_LINEA = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def hashes_de_scripts(carpeta: Path) -> list:
    hashes = set()
    for html in carpeta.glob("*.html"):
        for codigo in _SCRIPT_EN_LINEA.findall(html.read_text(encoding="utf-8")):
            digest = base64.b64encode(hashlib.sha256(codigo.encode()).digest()).decode()
            hashes.add(f"'sha256-{digest}'")
    return sorted(hashes)


def politica(hashes: Iterable[str]) -> str:
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' https://cdn.jsdelivr.net {' '.join(hashes)}".strip(),
        # El front pone estilos desde JS (style="..."): por eso 'unsafe-inline' solo en estilos
        "style-src 'self' 'unsafe-inline' https://api.fontshare.com",
        "font-src 'self' https://cdn.fontshare.com",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "connect-src 'self' https://cdn.jsdelivr.net",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


class CabecerasSeguridad(BaseHTTPMiddleware):
    def __init__(self, app, carpeta_front: Path) -> None:
        super().__init__(app)
        self.csp = politica(hashes_de_scripts(carpeta_front)) if carpeta_front.is_dir() else politica([])
        self.https = config.PUBLIC_URL.startswith("https://")

    async def dispatch(self, request: Request, call_next):
        respuesta = await call_next(request)
        h = respuesta.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Content-Security-Policy", self.csp)
        if self.https or request.url.scheme == "https":
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # Las respuestas con datos de la cuenta no se guardan en caché compartida
        if request.url.path.startswith(("/auth", "/suscripcion", "/trabajos", "/admin")) and "cache-control" not in h:
            h["Cache-Control"] = "no-store"
        # Las páginas se revisan en cada visita (así un cambio se ve sin recargar a la fuerza);
        # CSS y JS llevan ?v= y sí se guardan.
        elif (request.url.path.endswith(".html") or request.url.path.endswith("/")) and "cache-control" not in h:
            h["Cache-Control"] = "no-cache"
        return respuesta
