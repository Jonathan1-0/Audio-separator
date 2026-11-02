"""Límites de quien usa Splitter sin iniciar sesión.

Con cuenta, los límites salen del plan (services/cuotas.py). Sin cuenta no hay plan ni base:
se cuenta por IP, con valores parecidos a los del plan gratis.
"""
from fastapi import HTTPException, Request

from .. import config
from ..ratelimit import RateLimiter

# La cuenta se guarda en disco para que reiniciar el servidor no la borre.
_por_ip = RateLimiter(config.INVITADO_TRABAJOS_POR_DIA, 24 * 3600, config.DATA_DIR / "limite_invitados.json")


def ip_de(request: Request) -> str:
    """IP de quien hace la petición."""
    if config.BEHIND_PROXY:
        # El proxy agrega la IP real al final; lo anterior lo puede escribir el usuario.
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip(" ,"):
            return forwarded.rstrip(" ,").rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "desconocido"


def reservar(ip: str) -> None:
    """Aparta un trabajo de los del día para esa IP, o rechaza con 429."""
    wait = _por_ip.acquire(ip)
    if wait:
        horas = max(1, round(wait / 3600))
        raise HTTPException(
            429,
            f"Sin cuenta puedes separar {config.INVITADO_TRABAJOS_POR_DIA} audios por día. "
            f"Inicia sesión para usar tu plan o intenta de nuevo en {horas} h.",
            headers={"Retry-After": str(int(wait) + 1)},
        )


def liberar(ip: str) -> None:
    """Devuelve el trabajo apartado: un archivo rechazado no cuenta."""
    _por_ip.release(ip)


def verificar_audio(segundos: float) -> None:
    limite = config.INVITADO_MINUTOS_AUDIO
    if segundos > limite * 60:
        raise HTTPException(
            413,
            f"El audio dura {int(segundos // 60)}:{int(segundos % 60):02d} y sin cuenta el máximo es "
            f"{limite} min. Inicia sesión para usar el límite de tu plan.",
        )
