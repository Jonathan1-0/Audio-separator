"""Configuración de Splitter. Cada valor se puede cambiar con su variable de entorno."""
import os
from pathlib import Path

from dotenv import load_dotenv


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


BASE_DIR = Path(__file__).resolve().parent.parent
# Las variables de splitter/.env se cargan antes de leer cualquier valor (las que ya existen en el
# entorno no se pisan).
load_dotenv(BASE_DIR / ".env")

# Subidas y resultados.
DATA_DIR = Path(os.getenv("SPLITTER_DATA_DIR", BASE_DIR / "data")).resolve()
# Modelos de IA; solo se usa dentro del contenedor de Modal.
MODEL_DIR = Path(os.getenv("SPLITTER_MODEL_DIR", BASE_DIR / "models")).resolve()

MAX_UPLOAD_MB = _int("SPLITTER_MAX_UPLOAD_MB", 100)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Entre todas las personas, en 24 h: es el tope de gasto (~$0.03 por canción). 0 = sin límite.
MAX_JOBS_PER_DAY = _int("SPLITTER_MAX_JOBS_PER_DAY", 100)

# Quien usa la página sin iniciar sesión: límites como el plan gratis, pero por IP y por día.
INVITADO_TRABAJOS_POR_DIA = _int("SPLITTER_INVITADO_TRABAJOS_POR_DIA", 5)
INVITADO_MINUTOS_AUDIO = _int("SPLITTER_INVITADO_MINUTOS_AUDIO", 5)
# 1 = tomar la IP del usuario de X-Forwarded-For. Solo detrás de un proxy (nginx, Caddy, Modal):
# sin él, cualquiera podría inventar ese encabezado y saltarse el límite.
BEHIND_PROXY = os.getenv("SPLITTER_BEHIND_PROXY", "0") == "1"

# Duración de una sesión y de un periodo de suscripción.
DIAS_SESION = _int("SPLITTER_DIAS_SESION", 7)
DIAS_PERIODO = _int("SPLITTER_DIAS_PERIODO", 30)

# Cuánto se guardan los archivos de un trabajo terminado. Invitados: JOB_TTL_MINUTES.
JOB_TTL_MINUTES = _int("SPLITTER_JOB_TTL_MINUTES", 60)
# Con cuenta depende del plan: gratis 1 hora, pro una semana (y solo pro tiene historial).
MINUTOS_GUARDADO_PLAN = {
    "gratis": _int("SPLITTER_MINUTOS_GUARDADO_GRATIS", 60),
    "pro": _int("SPLITTER_MINUTOS_GUARDADO_PRO", 7 * 24 * 60),
    "admin": _int("SPLITTER_MINUTOS_GUARDADO_PRO", 7 * 24 * 60),
}
# Planes con historial ("Mis audios").
PLANES_CON_HISTORIAL = {"pro", "admin"}

# Cuenta de administrador para probar sin registrarse: se crea (o se actualiza) al arrancar con el
# plan "admin", que no se muestra en la página de planes. Sin estas dos variables no se crea.
# Van SOLO en .env: el repositorio es público.
ADMIN_EMAIL = os.getenv("SPLITTER_ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("SPLITTER_ADMIN_PASSWORD", "")
ADMIN_NOMBRE = os.getenv("SPLITTER_ADMIN_NOMBRE", "Administrador").strip() or "Administrador"
# Trabajos a la vez, uno por GPU. Debe coincidir con SPLITTER_MAX_CONTAINERS de modal_app.py.
PARALLEL_JOBS = _int("SPLITTER_PARALLEL_JOBS", 3)

MAX_QUEUE = _int("SPLITTER_MAX_QUEUE", 20)

# "modal" separa en Modal; "fake" devuelve tonos de prueba sin gastar crédito.
ENGINE = os.getenv("SPLITTER_ENGINE", "modal").lower()
# "splitter-gpu-l4" o "splitter-gpu-t4" (ver modal_app.py).
MODAL_APP = os.getenv("SPLITTER_MODAL_APP", "splitter-gpu-l4")
# Minutos que se espera a que Modal asigne una GPU antes de dar el trabajo por fallido. 0 = sin límite.
MODAL_START_MINUTES = _int("SPLITTER_MODAL_START_MINUTES", 5)

# CORS. En producción, el dominio de la página.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("SPLITTER_ALLOWED_ORIGINS", "*").split(",") if o.strip()]

ALLOWED_INPUT_EXT = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma", ".aiff", ".aif"}

# Las pistas se guardan en WAV y se convierten al descargar.
OUTPUT_FORMATS = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
}
PREVIEW_BITRATE = "128k"

# Precisión mixta en el modelo de voz: ~2× más rápido, casi sin diferencia de calidad.
AUTOCAST_VOCALS = os.getenv("SPLITTER_AUTOCAST_2STEM", "1") == "1"

# La clave es el "preset" que manda la página.
PRESETS = {
    "2stem": {
        "label": "Voz e instrumental",
        "model": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        "stems": ["vocals", "instrumental"],
        "autocast": AUTOCAST_VOCALS,
    },
    "4stem": {
        "label": "Voz, batería, bajo y otros (lenta, mejor calidad)",
        "model": "htdemucs_ft.yaml",  # 4 modelos combinados
        "stems": ["vocals", "drums", "bass", "other"],
        "mejor_calidad": True,  # solo para planes con mejor_calidad (pro); cuesta ~4× más GPU
    },
    "4stem_fast": {
        "label": "Voz, batería, bajo y otros (rápida)",
        "model": "htdemucs.yaml",  # 1 modelo en vez de 4: más rápido, algo menos de calidad
        "stems": ["vocals", "drums", "bass", "other"],
    },
    "denoise": {
        "label": "Limpiar ruido: deja solo la voz (quita música y ruido de fondo)",
        "stems": ["voice"],
        # Primero se separa la voz y luego se le quita el ruido: el modelo de ruido es para voces
        # solas, y sobre la mezcla completa se comía la música.
        "steps": [
            {
                "model": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
                "autocast": AUTOCAST_VOCALS,  # igual que en 2stem: comparten el modelo ya cargado
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

# Ventanas solapadas del modelo de voz. Con 2 tarda ~la mitad, con algo menos de calidad.
MDXC_OVERLAP = _int("SPLITTER_MDXC_OVERLAP", 4)

# --- Cuentas: recuperar contraseña y entrar con Google o Facebook ---
# Dirección pública de la página; con ella se arman los enlaces de los correos y el regreso de Google/Facebook.
# Vacía = se usa la misma dirección con la que se abrió la página (lo normal en local).
PUBLIC_URL = os.getenv("SPLITTER_PUBLIC_URL", "").rstrip("/")
# Clave para firmar los enlaces de recuperación. Sin ella se inventa una al arrancar
# (los enlaces enviados dejan de servir cuando se reinicia el servidor).
SECRET_KEY = os.getenv("SPLITTER_SECRET_KEY", "")
MINUTOS_RECUPERACION = _int("SPLITTER_MINUTOS_RECUPERACION", 30)

# Correo de salida (por ejemplo Gmail con una "contraseña de aplicación").
# Sin SMTP_USER el correo no se envía: el enlace sale en la terminal del servidor, para pruebas.
SMTP_HOST = os.getenv("SPLITTER_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SPLITTER_SMTP_PORT", 587)
SMTP_USER = os.getenv("SPLITTER_SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SPLITTER_SMTP_PASSWORD", "")

# Claves de las apps registradas en Google y Facebook. El botón de cada una solo aparece si tiene las dos.
GOOGLE_CLIENT_ID = os.getenv("SPLITTER_GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("SPLITTER_GOOGLE_CLIENT_SECRET", "").strip()
FACEBOOK_APP_ID = os.getenv("SPLITTER_FACEBOOK_APP_ID", "").strip()
FACEBOOK_APP_SECRET = os.getenv("SPLITTER_FACEBOOK_APP_SECRET", "").strip()
