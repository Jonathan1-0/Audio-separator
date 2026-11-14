# Configurar Google, Facebook y el correo de recuperación

Todo esto es opcional. Cada parte se activa escribiendo sus claves en `splitter/.env` y reiniciando el
servidor. Las claves son secretas: el `.env` nunca se sube a GitHub.

Abre la página siempre con la misma dirección que registres aquí. En esta guía se usa
`http://localhost:8000` (Facebook no acepta `127.0.0.1`).

## 1. Entrar con Google

1. Entra a <https://console.cloud.google.com/> y crea un proyecto (por ejemplo «Splitter»).
2. En **APIs y servicios → Pantalla de consentimiento de OAuth**, elige tipo **Externo**, pon el nombre
   de la app y tu correo. Mientras esté en modo de prueba, agrega en **Usuarios de prueba** los correos
   que van a entrar (el tuyo, el de Jonathan y el del profesor).
3. En **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**, elige
   **Aplicación web**.
4. En **URI de redireccionamiento autorizados** agrega exactamente:

   ```
   http://localhost:8000/auth/social/google/regreso
   ```

5. Copia el ID de cliente y el secreto al `.env`:

   ```
   SPLITTER_GOOGLE_CLIENT_ID=...
   SPLITTER_GOOGLE_CLIENT_SECRET=...
   ```

## 2. Entrar con Facebook

1. Entra a <https://developers.facebook.com/>, crea una app y agrégale el producto
   **Inicio de sesión con Facebook**.
2. En los permisos de la app, activa `email` además de `public_profile`.
3. Mientras la app esté en modo de desarrollo, solo pueden entrar las personas con un rol en la app
   (agrégalas en **Roles de la app**). En ese modo, `http://localhost` se acepta sin registrarlo.
4. Copia el identificador y la clave secreta de la app (en **Configuración → Básica**) al `.env`:

   ```
   SPLITTER_FACEBOOK_APP_ID=...
   SPLITTER_FACEBOOK_APP_SECRET=...
   ```

Si la cuenta de Facebook no tiene correo, Splitter no puede crear la cuenta y pide usar correo y
contraseña.

## 3. Correo para recuperar la contraseña (Gmail)

1. En la cuenta de Gmail que enviará los correos, activa la verificación en dos pasos.
2. Crea una **contraseña de aplicación** en <https://myaccount.google.com/apppasswords>.
3. Escribe en el `.env`:

   ```
   SPLITTER_SMTP_USER=tucorreo@gmail.com
   SPLITTER_SMTP_PASSWORD=la contraseña de aplicación
   SPLITTER_SECRET_KEY=un texto largo y secreto
   ```

Sin `SPLITTER_SMTP_USER` no se envía nada: el enlace aparece en la terminal donde corre el servidor,
que sirve para probar.

## Al publicar la página

Pon `SPLITTER_PUBLIC_URL=https://tu-dominio` en el `.env` y registra en Google y Facebook la misma
dirección de regreso, con ese dominio:

```
https://tu-dominio/auth/social/google/regreso
https://tu-dominio/auth/social/facebook/regreso
```

## Cómo funciona por dentro

- **Recuperación:** el enlace lleva un código firmado con vencimiento (30 minutos). No se guarda en la
  base; deja de servir en cuanto la contraseña cambia, y al cambiarla se cierran todas las sesiones.
- **Acceso social:** el servidor manda a Google o Facebook, recibe el correo y el nombre, y busca la
  cuenta con ese correo. Si no existe, la crea con el plan Gratis. Después abre la sesión igual que el
  login normal. No se agregaron tablas: se siguen usando las 8 de siempre.
