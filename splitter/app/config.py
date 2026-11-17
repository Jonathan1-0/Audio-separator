"""Configuración. Cada valor se puede cambiar con su variable de entorno."""
import os
from pathlib import Path

from dotenv import load_dotenv


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Subidas y resultados
DATA_DIR = Path(os.getenv("SPLITTER_DATA_DIR", BASE_DIR / "data")).resolve()
# Modelos de IA (solo en Modal)
MODEL_DIR = Path(os.getenv("SPLITTER_MODEL_DIR", BASE_DIR / "models")).resolve()

MAX_UPLOAD_MB = _int("SPLITTER_MAX_UPLOAD_MB", 100)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Tope de trabajos al día entre todos. 0 = sin límite
MAX_JOBS_PER_DAY = _int("SPLITTER_MAX_JOBS_PER_DAY", 100)

# Límites para quien no inicia sesión (por IP)
INVITADO_TRABAJOS_POR_DIA = _int("SPLITTER_INVITADO_TRABAJOS_POR_DIA", 5)
INVITADO_MINUTOS_AUDIO = _int("SPLITTER_INVITADO_MINUTOS_AUDIO", 5)
# 1 = el servidor está detrás de un proxy
BEHIND_PROXY = os.getenv("SPLITTER_BEHIND_PROXY", "0") == "1"

# Días que dura una sesión y un periodo del plan
DIAS_SESION = _int("SPLITTER_DIAS_SESION", 7)
DIAS_PERIODO = _int("SPLITTER_DIAS_PERIODO", 30)

# Minutos que se guardan los archivos de un trabajo
JOB_TTL_MINUTES = _int("SPLITTER_JOB_TTL_MINUTES", 60)
MINUTOS_GUARDADO_PLAN = {
    "gratis": _int("SPLITTER_MINUTOS_GUARDADO_GRATIS", 60),
    "pro": _int("SPLITTER_MINUTOS_GUARDADO_PRO", 7 * 24 * 60),
    "admin": _int("SPLITTER_MINUTOS_GUARDADO_PRO", 7 * 24 * 60),
}
# Pago simulado de Pro (sin cobrar). Solo para pruebas: apagado, nadie puede activar Pro gratis.
PAGOS_SIMULADOS = os.getenv("SPLITTER_PAGOS_SIMULADOS", "0") == "1"

# Planes con "Mis audios" (cada uno ve lo que guarda su plan)
PLANES_CON_HISTORIAL = {"gratis", "pro", "admin"}

# Los periodos se renuevan a esta hora (hora local de esta zona) del día de renovación
ZONA_HORARIA = os.getenv("SPLITTER_ZONA_HORARIA", "America/Mexico_City")
HORA_RENOVACION = _int("SPLITTER_HORA_RENOVACION", 1)

# Foto de perfil
MAX_FOTO_BYTES = 2 * 1024 * 1024

# El panel de administración pide tener activa la verificación en dos pasos
ADMIN_REQUIERE_DOS_PASOS = os.getenv("SPLITTER_ADMIN_REQUIERE_DOS_PASOS", "1") == "1"

# Cuenta de administrador (opcional, solo en .env)
ADMIN_EMAIL = os.getenv("SPLITTER_ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("SPLITTER_ADMIN_PASSWORD", "")
ADMIN_NOMBRE = os.getenv("SPLITTER_ADMIN_NOMBRE", "Administrador").strip() or "Administrador"
# Trabajos a la vez. Igual que SPLITTER_MAX_CONTAINERS en modal_app.py
PARALLEL_JOBS = _int("SPLITTER_PARALLEL_JOBS", 3)

MAX_QUEUE = _int("SPLITTER_MAX_QUEUE", 20)

# "modal" o "fake" (tonos de prueba)
ENGINE = os.getenv("SPLITTER_ENGINE", "modal").lower()
MODAL_APP = os.getenv("SPLITTER_MODAL_APP", "splitter-gpu-l4")
# Minutos que se espera una GPU. 0 = sin límite
MODAL_START_MINUTES = _int("SPLITTER_MODAL_START_MINUTES", 5)

# Quién puede llamar a la API desde otra página. Vacío = solo la misma página (lo normal,
# porque la API sirve el front). Ejemplo: https://splitter.mx,https://www.splitter.mx
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("SPLITTER_ALLOWED_ORIGINS", "").split(",") if o.strip()]

# Límites contra quien prueba contraseñas o crea cuentas en masa
LOGIN_POR_IP = _int("SPLITTER_LOGIN_POR_IP", 30)  # intentos cada 15 min por IP
LOGIN_FALLOS_POR_CUENTA = _int("SPLITTER_LOGIN_FALLOS_POR_CUENTA", 8)  # fallos cada 15 min por correo
REGISTROS_POR_IP = _int("SPLITTER_REGISTROS_POR_IP", 10)  # cuentas nuevas por hora por IP
CORREOS_POR_CUENTA = _int("SPLITTER_CORREOS_POR_CUENTA", 5)  # correos de verificación por hora

# Días que se guarda la fila de un trabajo (sin audio) antes de borrarla de la base
DIAS_HISTORIAL_TRABAJOS = _int("SPLITTER_DIAS_HISTORIAL_TRABAJOS", 90)

# Horas que sirve el enlace para confirmar el correo
HORAS_VERIFICACION = _int("SPLITTER_HORAS_VERIFICACION", 48)

ALLOWED_INPUT_EXT = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma", ".aiff", ".aif"}

# Formatos de descarga
OUTPUT_FORMATS = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
}
PREVIEW_BITRATE = "128k"

# Hace el modelo de voz más rápido
AUTOCAST_VOCALS = os.getenv("SPLITTER_AUTOCAST_2STEM", "1") == "1"

# Opciones de separación
PRESETS = {
    "2stem": {
        "label": "Voz e instrumental",
        "model": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        "stems": ["vocals", "instrumental"],
        "autocast": AUTOCAST_VOCALS,
    },
    "4stem": {
        "label": "Voz, batería, bajo y otros (lenta, mejor calidad)",
        "model": "htdemucs_ft.yaml",  # 4 modelos
        "stems": ["vocals", "drums", "bass", "other"],
        "mejor_calidad": True,  # solo plan pro
    },
    "4stem_fast": {
        "label": "Voz, batería, bajo y otros (rápida)",
        "model": "htdemucs.yaml",  # 1 modelo: más rápido
        "stems": ["vocals", "drums", "bass", "other"],
    },
    "denoise": {
        "label": "Limpiar ruido: deja solo la voz (quita música y ruido de fondo)",
        "stems": ["voice"],
        # Primero se separa la voz y después se limpia
        "steps": [
            {
                "model": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
                "autocast": AUTOCAST_VOCALS,
                "stems": {"vocals": "voz_tmp"},
            },
            {
                "input": "voz_tmp",
                "model": "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt",
                "stems": {"dry": "voice"},
            },
        ],
    },
}
DEFAULT_PRESET = "2stem"

# Con 2 tarda la mitad, con un poco menos de calidad
MDXC_OVERLAP = _int("SPLITTER_MDXC_OVERLAP", 4)

# Recuperar contraseña y entrar con Google o Facebook
# Dirección de la página. Vacía = la misma con la que se abrió
PUBLIC_URL = os.getenv("SPLITTER_PUBLIC_URL", "").rstrip("/")
# Clave para firmar enlaces (recuperación, verificación y descargas). Debe estar en .env:
# sin ella se inventa una al arrancar y los enlaces dejan de servir al reiniciar.
SECRET_KEY = os.getenv("SPLITTER_SECRET_KEY", "")

# Errores a Sentry (opcional): la dirección DSN del proyecto
SENTRY_DSN = os.getenv("SPLITTER_SENTRY_DSN", "").strip()
# Logs en JSON (una línea por evento), útil en producción
LOGS_JSON = os.getenv("SPLITTER_LOGS_JSON", "0") == "1"
# Contacto que aparece en las páginas legales y en los correos
CONTACTO_EMAIL = os.getenv("SPLITTER_CONTACTO_EMAIL", "").strip()
MINUTOS_RECUPERACION = _int("SPLITTER_MINUTOS_RECUPERACION", 30)

# Correo de salida. Sin SMTP_USER el enlace sale en la terminal
SMTP_HOST = os.getenv("SPLITTER_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SPLITTER_SMTP_PORT", 587)
SMTP_USER = os.getenv("SPLITTER_SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SPLITTER_SMTP_PASSWORD", "")
# Desde qué dirección y con qué nombre salen los correos. Vacío = SMTP_USER.
# Con dominio propio, por ejemplo: no-responder@splitter.mx (en Resend el usuario SMTP es "resend")
SMTP_FROM = os.getenv("SPLITTER_SMTP_FROM", "").strip()
SMTP_NOMBRE = os.getenv("SPLITTER_SMTP_NOMBRE", "Splitter").strip() or "Splitter"

# Claves de Google y Facebook
GOOGLE_CLIENT_ID = os.getenv("SPLITTER_GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("SPLITTER_GOOGLE_CLIENT_SECRET", "").strip()
FACEBOOK_APP_ID = os.getenv("SPLITTER_FACEBOOK_APP_ID", "").strip()
FACEBOOK_APP_SECRET = os.getenv("SPLITTER_FACEBOOK_APP_SECRET", "").strip()
