"""Envío de correos. Sin SMTP en .env, el texto sale en la terminal."""
import logging
import smtplib
from email.message import EmailMessage

from .. import config

log = logging.getLogger("splitter.correo")


def enviar(destino: str, asunto: str, texto: str) -> None:
    if not config.SMTP_USER:
        log.info("Correo de prueba (no se envió, falta SPLITTER_SMTP_USER)\nPara: %s\nAsunto: %s\n%s", destino, asunto, texto)
        return
    mensaje = EmailMessage()
    mensaje["From"] = f"Splitter <{config.SMTP_USER}>"
    mensaje["To"] = destino
    mensaje["Subject"] = asunto
    mensaje.set_content(texto)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as servidor:
        servidor.starttls()
        servidor.login(config.SMTP_USER, config.SMTP_PASSWORD)
        servidor.send_message(mensaje)
