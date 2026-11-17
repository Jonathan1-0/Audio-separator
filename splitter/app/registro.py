"""Logs y errores. En producción: SPLITTER_LOGS_JSON=1 y, si se quiere, SPLITTER_SENTRY_DSN."""
import json
import logging

from . import config


class _FormatoJSON(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        datos = {
            "hora": self.formatTime(registro, "%Y-%m-%dT%H:%M:%S"),
            "nivel": registro.levelname,
            "origen": registro.name,
            "mensaje": registro.getMessage(),
        }
        if registro.exc_info:
            datos["error"] = self.formatException(registro.exc_info)
        return json.dumps(datos, ensure_ascii=False)


def preparar_registro() -> None:
    raiz = logging.getLogger()
    if not raiz.handlers:
        manejador = logging.StreamHandler()
        manejador.setFormatter(
            _FormatoJSON() if config.LOGS_JSON else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        raiz.addHandler(manejador)
    raiz.setLevel(logging.INFO)

    if config.SENTRY_DSN:
        try:
            import sentry_sdk
        except ImportError:
            logging.getLogger("splitter").warning("SPLITTER_SENTRY_DSN está puesto pero falta instalar sentry-sdk")
            return
        # send_default_pii=False: no manda correos, IPs ni cookies a Sentry
        sentry_sdk.init(dsn=config.SENTRY_DSN, traces_sample_rate=0.0, send_default_pii=False)
