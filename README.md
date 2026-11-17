# Splitter

**Tu audio, a tu manera.** Splitter separa la voz del instrumental, separa voz, batería, bajo y otros instrumentos en pistas distintas, o limpia el ruido de una grabación de voz. Escuchas cada pista en la página y la descargas en WAV, MP3, FLAC, OGG o M4A.

![Pruebas](https://github.com/Jonathan1-0/python-audio-separator/actions/workflows/pruebas.yml/badge.svg)

## Cómo funciona

```
Navegador ──► FastAPI (app/)  ──► Cola de trabajos ──► GPU en Modal (modal_app.py)
                 │                                       audio-separator: BS-RoFormer, Demucs
                 ├─► MySQL en Aiven (cuentas, planes, trabajos, pagos)
                 └─► Disco (data/): audios y pistas, se borran solos
```

- **`splitter/app/`**: API en FastAPI. Sirve también la página (`frontend/`).
  - `routes/`: las rutas HTTP. `services/`: la lógica. `repositories/`: las consultas a la base. `models/`: las tablas.
  - `jobs.py`: cola de trabajos en paralelo. `engine.py`: llama a la GPU en Modal (o a un motor simulado para pruebas).
- **`splitter/frontend/`**: HTML, CSS y JavaScript sin framework ni compilación.
- **`splitter/migraciones/`**: cambios a la base con Alembic. Se aplican solos al arrancar.
- **`splitter/modal_app.py`**: la parte que corre en la GPU de Modal.

### Planes

|                            | Sin cuenta | Gratis | Pro            |
|----------------------------|-----------:|-------:|---------------:|
| Audios                    | 5 al día   | 15 cada 30 días | Ilimitados     |
| Duración máxima del audio  | 5 min      | 5 min  | 20 min         |
| Mejor calidad (4 modelos)  | —          | —      | ✓              |
| Las pistas se guardan      | 1 hora     | 1 hora | 1 semana       |
| Precio                     | —          | $0     | $99 MXN        |

Los periodos se renuevan a la 1:00 a. m. (hora del centro de México). Al cancelar Pro se conserva hasta el fin del periodo pagado y después pasa solo a Gratis. Los límites y precios están en `app/seed.py` y se actualizan en la base al arrancar.

## Correr en tu máquina

Necesitas Python 3.12 o más nuevo y `ffmpeg`.

```bash
cd splitter
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env           # y llena los valores
.venv/bin/uvicorn app.main:app --reload
```

Abre http://127.0.0.1:8000. Sin `DATABASE_URL` usa un archivo SQLite local; con `SPLITTER_ENGINE=fake` no necesitas GPU (genera tonos de prueba).

Con Docker: `docker compose up --build` (ver `docker-compose.yml`).

### Desplegar la GPU

```bash
modal token new                              # una vez
SPLITTER_GPU=L4 modal deploy modal_app.py    # crea splitter-gpu-l4
```

## Variables de entorno (`splitter/.env`)

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | Base de datos. Ej. `mysql+pymysql://usuario:clave@host:puerto/base`. Vacía = SQLite local. |
| `DB_SSL_CA` | Certificado de Aiven (ruta al `ca.pem`). |
| `SPLITTER_SECRET_KEY` | **Obligatoria en producción.** Firma los enlaces de correo y de descarga. Genera una con `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `SPLITTER_PUBLIC_URL` | Dirección pública, ej. `https://splitter.mx`. Se usa en los enlaces de los correos y activa HSTS. |
| `SPLITTER_ADMIN_EMAIL`, `SPLITTER_ADMIN_PASSWORD`, `SPLITTER_ADMIN_NOMBRE` | Cuenta de administrador (ve `/admin.html`). |
| `SPLITTER_SMTP_USER`, `SPLITTER_SMTP_PASSWORD`, `SPLITTER_SMTP_HOST`, `SPLITTER_SMTP_PORT` | Envío de correos. Sin ellas los correos salen en la terminal. |
| `SPLITTER_CONTACTO_EMAIL` | Correo de contacto que aparece en los correos. |
| `SPLITTER_GOOGLE_CLIENT_ID`, `SPLITTER_GOOGLE_CLIENT_SECRET` | Entrar con Google. |
| `SPLITTER_FACEBOOK_APP_ID`, `SPLITTER_FACEBOOK_APP_SECRET` | Entrar con Facebook. |
| `SPLITTER_ALLOWED_ORIGINS` | Otras páginas que pueden llamar a la API (CORS). Vacía = solo la misma página. |
| `SPLITTER_BEHIND_PROXY` | `1` si hay un proxy (Nginx, Cloudflare) delante; así se usa la IP real. |
| `SPLITTER_ENGINE` | `modal` (GPU) o `fake` (pruebas). |
| `SPLITTER_SENTRY_DSN` | Manda los errores a Sentry (opcional). |
| `SPLITTER_LOGS_JSON` | `1` para logs en JSON (una línea por evento). |
| `SPLITTER_LOGIN_POR_IP`, `SPLITTER_LOGIN_FALLOS_POR_CUENTA`, `SPLITTER_REGISTROS_POR_IP` | Límites contra ataques (por defecto 30 intentos / 15 min por IP, 8 fallos / 15 min por cuenta, 10 registros / hora por IP). |

Todas las demás opciones están comentadas en `app/config.py`.

## Seguridad

- **Sesión en cookie `HttpOnly` + `SameSite=Lax`**: el JavaScript de la página no puede leer el token. Los cambios (POST, PATCH, DELETE) deben venir de la misma página (se revisa `Origin`).
- **Content-Security-Policy** estricta: solo corren los scripts propios, el CDN de `motion` y los scripts en línea de los HTML (por su hash, calculado al arrancar).
- **Límites** de intentos de inicio de sesión, registros y correos.
- **Descargas firmadas**: las pistas de una cuenta solo se escuchan o descargan con la sesión del dueño o con el enlace firmado que la API le da a él.
- **Correo confirmado** antes de contratar Pro, y para cambiar el correo de la cuenta.
- Avisos por correo al cambiar la contraseña o el correo, cerrar sesión en todos los dispositivos y borrar la cuenta.
- Facebook no confirma los correos: solo puede entrar a cuentas que se crearon con Facebook.
- **Google se conecta de forma explícita**: una cuenta creada con contraseña no se abre con Google solo porque el correo coincida; hay que entrar con la contraseña y conectar Google desde el perfil. Las cuentas se reconocen por el identificador de Google, no por el correo.
- **Verificación en dos pasos por correo**: al iniciar sesión (con contraseña o con Google) se envía un código de 6 dígitos que vence en 10 minutos; sirve una sola vez y hay límite de intentos y de envíos. El panel de administración la exige (`SPLITTER_ADMIN_REQUIERE_DOS_PASOS=0` para quitarlo).
- Los límites de intentos se guardan en `data/` y no se reinician al reiniciar el servidor.

## Base de datos

Las migraciones están en `splitter/migraciones/versions/` y se aplican solas al arrancar. Para crear una nueva:

```bash
cd splitter
.venv/bin/alembic revision -m "qué cambia"   # y escribe upgrade() / downgrade()
```

Cada hora se borran solas las sesiones vencidas y los trabajos de más de 90 días (`SPLITTER_DIAS_HISTORIAL_TRABAJOS`); sus audios ya se habían borrado.

Cuentas que existían antes de pedir confirmar el correo:

```bash
.venv/bin/python -m scripts.confirmar_correos                    # lista (no envía nada)
.venv/bin/python -m scripts.confirmar_correos --enviar           # les manda el correo (pide SMTP y SPLITTER_PUBLIC_URL)
.venv/bin/python -m scripts.confirmar_correos --marcar a@b.com   # marca cuentas de confianza como confirmadas
```

Respaldo propio (además de los de Aiven):

```bash
.venv/bin/python -m scripts.respaldo guardar --dias 30     # respaldos/splitter-AAAAMMDD-HHMM.json.gz
.venv/bin/python -m scripts.respaldo restaurar ARCHIVO      # solo en una base vacía
```

## Pruebas

```bash
cd splitter
.venv/bin/pytest -q                 # backend (rápidas)
.venv/bin/pytest e2e                # en un navegador real con Playwright: registro, separación, dos pasos…
.venv/bin/ruff check app migraciones scripts tests e2e --select F,E9
```

Las de navegador levantan su propio servidor con una base temporal; usan Chrome si está instalado (si no: `.venv/bin/playwright install chromium`).

GitHub Actions corre todo en cada push (`.github/workflows/pruebas.yml`), junto con la revisión de sintaxis del JavaScript y la construcción de la imagen de Docker.

## Antes de publicar

- [ ] Poner `SPLITTER_SECRET_KEY` y `SPLITTER_PUBLIC_URL` en el servidor.
- [ ] Agregar la política de reembolsos e IVA en `frontend/terminos.html` cuando estén definidos, y el procesador de pagos en `frontend/privacidad.html`.
- [ ] Cambiar `og:image` en los HTML por la dirección completa (`https://tudominio/og.png`): WhatsApp y Facebook no aceptan rutas relativas.
- [ ] Conectar un procesador de pagos real (hoy el pago de Pro es simulado).
