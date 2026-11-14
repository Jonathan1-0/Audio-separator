"""Límites de quien usa Splitter sin cuenta, por IP."""
from fastapi import HTTPException, Request

from .. import config
from ..ratelimit import RateLimiter

_por_ip = RateLimiter(config.INVITADO_TRABAJOS_POR_DIA, 24 * 3600, config.DATA_DIR / "limite_invitados.json")


def ip_de(request: Request) -> str:
    if config.BEHIND_PROXY:
        # El proxy pone la IP real al final
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip(" ,"):
            return forwarded.rstrip(" ,").rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "desconocido"


def verificar_preset(preset: str) -> None:
    """Sin cuenta no hay mejor calidad."""
    if config.PRESETS.get(preset, {}).get("mejor_calidad"):
        raise HTTPException(403, "La mejor calidad de separación es del plan Pro. Usa la calidad rápida o inicia sesión.")


def reservar(ip: str) -> None:
    """Aparta un trabajo del día para esa IP."""
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
    """Un archivo rechazado no cuenta."""
    _por_ip.release(ip)


def verificar_audio(segundos: float) -> None:
    limite = config.INVITADO_MINUTOS_AUDIO
    if segundos > limite * 60:
        raise HTTPException(
            413,
            f"El audio dura {int(segundos // 60)}:{int(segundos % 60):02d} y sin cuenta el máximo es "
            f"{limite} min. Inicia sesión para usar el límite de tu plan.",
        )
