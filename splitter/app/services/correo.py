"""Envío de correos. Sin SMTP en .env, el texto sale en la terminal.

Cada correo va en texto plano y en HTML (mismo contenido), con el estilo de la página.
"""
import html
import logging
import smtplib
from email.message import EmailMessage
from typing import List, Optional

from .. import config

log = logging.getLogger("splitter.correo")


def enviar(destino: str, asunto: str, texto: str, cuerpo_html: Optional[str] = None) -> None:
    if not config.SMTP_USER:
        log.info("Correo de prueba (no se envió, falta SPLITTER_SMTP_USER)\nPara: %s\nAsunto: %s\n%s", destino, asunto, texto)
        return
    mensaje = EmailMessage()
    mensaje["From"] = f"{config.SMTP_NOMBRE} <{config.SMTP_FROM or config.SMTP_USER}>"
    if config.CONTACTO_EMAIL:
        mensaje["Reply-To"] = config.CONTACTO_EMAIL  # las respuestas llegan al correo de contacto
    mensaje["To"] = destino
    mensaje["Subject"] = asunto
    mensaje.set_content(texto)
    if cuerpo_html:
        mensaje.add_alternative(cuerpo_html, subtype="html")
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as servidor:
        servidor.starttls()
        servidor.login(config.SMTP_USER, config.SMTP_PASSWORD)
        servidor.send_message(mensaje)


def enviar_aviso(
    destino: str,
    asunto: str,
    saludo: str,
    parrafos: List[str],
    boton: Optional[str] = None,
    enlace: Optional[str] = None,
    pie: Optional[str] = None,
) -> None:
    """Arma el correo (texto y HTML) y lo envía. Un fallo se registra y no rompe la petición."""
    texto = "\n\n".join([saludo, *parrafos] + ([f"{boton}: {enlace}"] if enlace else []) + ([pie] if pie else []))
    texto += "\n\n— Splitter"
    try:
        enviar(destino, asunto, texto, plantilla(asunto, saludo, parrafos, boton, enlace, pie))
    except Exception:
        log.exception("No se pudo enviar el correo «%s»", asunto)


def plantilla(
    titulo: str,
    saludo: str,
    parrafos: List[str],
    boton: Optional[str] = None,
    enlace: Optional[str] = None,
    pie: Optional[str] = None,
) -> str:
    """HTML con tablas y estilos en línea: es lo único que respetan todos los clientes de correo."""
    e = html.escape
    cuerpo = "".join(
        f'<p style="margin:0 0 16px;font-size:16px;line-height:1.55;color:#d4d4d4">{e(p)}</p>' for p in parrafos
    )
    if boton and enlace:
        cuerpo += (
            '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 24px"><tr>'
            f'<td style="border-radius:999px;background:#0a84ff"><a href="{e(enlace)}" '
            'style="display:inline-block;padding:12px 26px;font-size:16px;font-weight:600;color:#ffffff;'
            f'text-decoration:none;border-radius:999px">{e(boton)}</a></td></tr></table>'
            '<p style="margin:0 0 16px;font-size:13px;line-height:1.5;color:#8a8a8a">Si el botón no funciona, copia este enlace:<br>'
            f'<a href="{e(enlace)}" style="color:#5aa9ff;word-break:break-all">{e(enlace)}</a></p>'
        )
    if pie:
        cuerpo += f'<p style="margin:0;font-size:13px;line-height:1.5;color:#8a8a8a">{e(pie)}</p>'
    contacto = (
        f' · <a href="mailto:{e(config.CONTACTO_EMAIL)}" style="color:#8a8a8a">{e(config.CONTACTO_EMAIL)}</a>'
        if config.CONTACTO_EMAIL else ""
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="dark"><title>{e(titulo)}</title></head>
<body style="margin:0;padding:0;background:#0a0a0a">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a"><tr><td align="center" style="padding:32px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<tr><td style="padding:0 0 20px;font-size:20px;font-weight:700;letter-spacing:-.01em;color:#ffffff">Splitter</td></tr>
<tr><td style="background:#161616;border:1px solid #262626;border-radius:16px;padding:32px 28px">
<h1 style="margin:0 0 16px;font-size:22px;line-height:1.3;color:#ffffff">{e(saludo)}</h1>
{cuerpo}
</td></tr>
<tr><td style="padding:20px 4px 0;font-size:12px;line-height:1.5;color:#6b6b6b">
Recibes este correo porque tienes una cuenta en Splitter{contacto}.
</td></tr>
</table></td></tr></table></body></html>"""
