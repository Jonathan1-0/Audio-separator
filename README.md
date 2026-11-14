# Splitter

Página web para separar audio: subes una canción y te devuelve la voz, la música o cada instrumento
por separado. También limpia el ruido de una grabación de voz.

Proyecto integradora de Diego Jampierd Cruz Contreras (backend) y Jonathan Gael Alonso López Arcos
(frontend). La separación la hace la librería
[python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) en una GPU de Modal.

## Qué hace

- Subir un audio arrastrándolo o eligiéndolo (MP3, WAV, FLAC, M4A, OGG, AAC, WMA, AIFF).
- Tres opciones: separar voz y música, separar instrumentos (voz, batería, bajo y otros) o limpiar ruido.
- Barra de progreso en tiempo real.
- Escuchar el resultado antes de descargar, con volumen por pista.
- Descargar cada pista o todas, en WAV, MP3, FLAC, OGG o M4A.
- Cuentas con plan Gratis y Pro, con límite de trabajos y de minutos por audio.
- Entrar con correo y contraseña, con Google o con Facebook.
- Recuperar la contraseña con un enlace enviado por correo.
- Sección de ayuda con preguntas frecuentes.

El pago del plan Pro es **simulado**: no se cobra nada. El cobro real queda pendiente.

## Cómo está organizado

```
splitter/
  app/
    main.py           Rutas de trabajos (subir, progreso, vista previa, descarga)
    routes/           Rutas de cuentas, acceso social, planes e historial (reciben la petición)
    services/         Reglas del negocio: login, recuperación, acceso social, cuotas, pagos
    repositories/     Consultas a la base de datos             (leen y guardan)
    models/tablas.py  Las 8 tablas
    engine.py         Motor de separación: Modal o simulado
    jobs.py           Cola de trabajos
    media.py          Conversión de formatos con ffmpeg
    config.py         Todos los valores que se pueden cambiar
  frontend/           La página (HTML, CSS y JavaScript, sin frameworks)
  modal_app.py        Lo que corre en la GPU de Modal
  tests/              Pruebas automáticas
docs/capturas/        Evidencias de las pruebas
```

El backend sigue un modelo por capas: **ruta → servicio → repositorio → tabla**. Cada archivo tiene
un solo trabajo.

Base de datos (8 tablas): `usuarios`, `sesiones`, `planes`, `suscripciones`, `metodos_pago`, `pagos`,
`trabajos` y `resultados`.

## Cómo correrlo en tu computadora

Necesitas Python 3.11 o más nuevo y ffmpeg instalado.

```bash
cd splitter
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # En Windows: copy .env.example .env
uvicorn app.main:app --reload
```

Abre <http://127.0.0.1:8000>. El mismo servidor entrega la página y la API.

Con `SPLITTER_ENGINE=fake` en el `.env` no se necesita Modal: el motor simulado devuelve tonos de
prueba, y sirve para revisar toda la página sin gastar crédito.

### Base de datos

- Sin `DATABASE_URL`, se crea un archivo `splitter.db` (SQLite) y funciona solo.
- Para usar MySQL en Aiven, pon en el `.env` la `DATABASE_URL` y en `DB_SSL_CA` la ruta del
  certificado `ca.pem`. Ni el `.env` ni el `.pem` se suben al repositorio.

Las tablas y los planes se crean solos al arrancar. Para ver la base: `python ver_base.py`.

### Separación real con Modal

```bash
pip install modal
modal setup                                    # una sola vez, inicia sesión en Modal
SPLITTER_GPU=L4 modal deploy modal_app.py      # sube el trabajador de GPU
```

Después pon `SPLITTER_ENGINE=modal` en el `.env` y vuelve a arrancar el servidor. Hay que volver a
desplegar cada vez que cambie `modal_app.py` o la carpeta `app/`.

### Google, Facebook y correo de recuperación

Son opcionales y se activan con claves en el `.env`. Los pasos están en
[docs/CONFIGURAR_ACCESOS.md](docs/CONFIGURAR_ACCESOS.md). Sin claves, los botones de Google y Facebook
no aparecen y el enlace para cambiar la contraseña sale en la terminal del servidor.

## Pruebas

```bash
cd splitter
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Las pruebas usan el motor simulado y una base SQLite temporal: no tocan Aiven ni Modal.

## Rutas principales de la API

| Método | Ruta | Para qué |
| --- | --- | --- |
| GET | `/api/config` | Límites, formatos y opciones de separación |
| POST | `/api/jobs` | Subir un audio y crear el trabajo |
| GET | `/api/jobs/{id}` | Estado del trabajo |
| GET | `/api/jobs/{id}/events` | Progreso en tiempo real (SSE) |
| GET | `/api/jobs/{id}/stems/{pista}/preview` | Escuchar una pista |
| GET | `/api/jobs/{id}/stems/{pista}/download` | Descargar una pista |
| GET | `/api/jobs/{id}/download` | Descargar todas en un ZIP |
| DELETE | `/api/jobs/{id}` | Borrar el trabajo |
| POST | `/auth/registro`, `/auth/login`, `/auth/logout` | Cuentas |
| POST | `/auth/recuperar` | Pedir el enlace para cambiar la contraseña |
| POST | `/auth/restablecer` | Guardar la contraseña nueva con el código del enlace |
| GET | `/auth/social` | Qué accesos sociales están configurados |
| GET | `/auth/social/{proveedor}` | Empezar el acceso con `google` o `facebook` |
| GET | `/suscripcion/planes` | Planes disponibles |
| GET | `/suscripcion` | Mi plan y cuánto llevo usado |
| POST | `/suscripcion/pro`, `/suscripcion/cancelar` | Contratar o cancelar Pro (pago simulado) |

La documentación interactiva está en <http://127.0.0.1:8000/docs>.

## Accesibilidad

La página se revisó con las 10 heurísticas de Nielsen y la lista WCAG 2.1 nivel AA: todo se puede usar
con teclado, el foco siempre se ve, los controles tienen nombre para lectores de pantalla, los mensajes
de progreso y error se anuncian solos, y el diseño se acomoda hasta 320 px de ancho.

## Pendiente

- Cobro real del plan Pro (hoy es simulado).
- Entrar con Apple (necesita una cuenta de desarrollador de pago).
