// Ventana de Perfil (se abre desde el menu de la cuenta) y vista de edicion de un solo dato.
//
// Datos: salen de la sesion de account.js (GET /suscripcion: nombre, email y, si el servidor los entrega,
// telefono y foto_url). Nada de esto se da por guardado hasta que el servidor responde 2xx.
//
// Contrato que el backend debe ofrecer para que Guardar funcione (hoy NO existe; ver README del cambio):
//   PATCH /auth/perfil        body JSON { nombre? | email? | telefono? } -> 200 con los campos actualizados
//   PUT   /auth/perfil/foto   multipart, campo "foto" (png/jpg/webp, max 2 MB) -> 200 { foto_url }
//   GET   /suscripcion        debe incluir "telefono" y "foto_url" para mostrarlos al recargar
(() => {
  'use strict';
  if (!window.crearDialogoCuenta) return;   // planes.html no carga el menu ni este modulo

  const MAX_FOTO = 2 * 1024 * 1024;
  const TIPOS_FOTO = ['image/png', 'image/jpeg', 'image/webp'];
  const SIN_SOPORTE = 'Todavía no se puede guardar este dato: el servidor aún no tiene esa función.';

  // Los tres datos editables. "valida" devuelve el texto de error, o '' si el valor sirve.
  const CAMPOS = {
    nombre: {
      titulo: 'Nombre', tipo: 'text', autocomplete: 'name', max: 100, inputmode: 'text',
      valida: (v) => (v ? (v.length > 100 ? 'El nombre no puede pasar de 100 caracteres.' : '') : 'Escribe tu nombre.'),
    },
    email: {
      titulo: 'Correo electrónico', tipo: 'email', autocomplete: 'email', max: 255, inputmode: 'email',
      valida: (v) => (!v ? 'Escribe tu correo electrónico.'
        : !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v) ? 'Escribe un correo válido, como nombre@correo.com.' : ''),
    },
    telefono: {
      titulo: 'Número de teléfono', tipo: 'tel', autocomplete: 'tel', max: 20, inputmode: 'tel',
      valida: (v) => {
        if (!v) return '';   // el telefono es opcional: vacio lo borra
        if (!/^\+?[\d\s().-]+$/.test(v)) return 'Usa solo números, espacios y el signo + al inicio.';
        const digitos = v.replace(/\D/g, '').length;
        return digitos >= 7 && digitos <= 15 ? '' : 'El teléfono debe tener entre 7 y 15 dígitos.';
      },
    },
  };

  const PLUMA = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19z"/><path d="M14.5 6.5l3 3"/></svg>';
  const CAMARA = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M4 8.5A1.5 1.5 0 0 1 5.5 7H8l1.2-2h5.6L16 7h2.5A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z"/><circle cx="12" cy="12.5" r="3.2"/></svg>';
  const BORRAR = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true" focusable="false"><path d="M7 7l10 10M17 7L7 17"/></svg>';

  let dialogo = null;
  let campoActual = null;     // nombre | email | telefono mientras se edita
  let fotoPendiente = null;   // { archivo, url } elegida pero aun no confirmada por el servidor
  let ocupado = false;
  const $ = (selector) => dialogo.querySelector(selector);

  function construir() {
    dialogo = window.crearDialogoCuenta('profile-dialog');
    dialogo.innerHTML = `
      <section class="profile-view" data-vista="perfil" aria-labelledby="perfil-titulo">
        <div class="profile-bar">
          <button type="button" class="text-button" id="perfil-cancelar">Cancelar</button>
          <button type="button" class="text-button text-button-accent" id="perfil-guardar-foto" hidden>Guardar</button>
        </div>
        <h2 id="perfil-titulo" class="profile-title">Perfil</h2>
        <div class="profile-photo">
          <div class="profile-avatar" id="perfil-avatar">
            <img id="perfil-foto" alt="Tu foto de perfil" hidden>
            <span id="perfil-iniciales" aria-hidden="true"></span>
            <button type="button" class="avatar-camera" id="perfil-camara" aria-label="Elegir foto de perfil">${CAMARA}</button>
          </div>
          <button type="button" class="text-button text-button-accent" id="perfil-cambiar-foto">Cambiar foto</button>
          <input type="file" id="perfil-archivo" accept="image/png,image/jpeg,image/webp" hidden>
        </div>
        <p id="perfil-mensaje" class="profile-message" role="alert" hidden></p>
        <div class="profile-rows">
          ${Object.entries(CAMPOS).map(([id, c]) => `
          <div class="profile-row">
            <div class="profile-row-text">
              <span class="profile-label">${c.titulo}</span>
              <span class="profile-value" data-valor="${id}"></span>
            </div>
            <button type="button" class="icon-button" data-editar="${id}" aria-label="Editar ${c.titulo.toLowerCase()}">${PLUMA}</button>
          </div>`).join('')}
          <div class="profile-row">
            <div class="profile-row-text">
              <span class="profile-label">Contraseña</span>
              <span class="profile-value profile-dots" aria-label="Contraseña oculta">••••••••</span>
            </div>
            <button type="button" class="icon-button" id="editar-clave" aria-label="Cambiar contraseña">${PLUMA}</button>
          </div>
        </div>
      </section>
      <form class="profile-view" data-vista="clave" aria-labelledby="clave-titulo" novalidate hidden>
        <div class="profile-bar">
          <button type="button" class="text-button" id="clave-cancelar">Cancelar</button>
          <button type="submit" class="text-button text-button-accent" id="clave-guardar">Guardar</button>
        </div>
        <h2 id="clave-titulo" class="profile-title">Contraseña</h2>
        <input type="email" id="clave-usuario" autocomplete="username" hidden>
        <div class="profile-fields">
          <label class="profile-field" for="clave-actual"><span>Contraseña actual</span>
            <input id="clave-actual" type="password" autocomplete="current-password" maxlength="72" aria-describedby="clave-error"></label>
          <label class="profile-field" for="clave-nueva"><span>Nueva contraseña</span>
            <input id="clave-nueva" type="password" autocomplete="new-password" maxlength="72" aria-describedby="clave-ayuda clave-error"></label>
          <label class="profile-field" for="clave-confirmar"><span>Confirma la nueva contraseña</span>
            <input id="clave-confirmar" type="password" autocomplete="new-password" maxlength="72" aria-describedby="clave-error"></label>
        </div>
        <p id="clave-ayuda" class="profile-hint">Entre 8 y 72 caracteres.</p>
        <p id="clave-error" class="profile-message" role="alert" hidden></p>
      </form>
      <form class="profile-view" data-vista="editar" aria-labelledby="editar-titulo" novalidate hidden>
        <div class="profile-bar">
          <button type="button" class="text-button" id="editar-cancelar">Cancelar</button>
          <button type="submit" class="text-button text-button-accent" id="editar-guardar">Guardar</button>
        </div>
        <h2 id="editar-titulo" class="profile-title"></h2>
        <div class="profile-input">
          <input id="editar-input" aria-labelledby="editar-titulo" aria-describedby="editar-error">
          <button type="button" class="input-clear" id="editar-borrar" aria-label="Borrar el contenido">${BORRAR}</button>
        </div>
        <p id="editar-error" class="profile-message" role="alert" hidden></p>
      </form>`;

    // Cancelar en Perfil: cierra y descarta la foto que no se guardo.
    $('#perfil-cancelar').addEventListener('click', () => dialogo.close());
    $('#perfil-camara').addEventListener('click', () => $('#perfil-archivo').click());
    $('#perfil-cambiar-foto').addEventListener('click', () => $('#perfil-archivo').click());
    $('#perfil-archivo').addEventListener('change', elegirFoto);
    $('#perfil-guardar-foto').addEventListener('click', guardarFoto);
    for (const boton of dialogo.querySelectorAll('[data-editar]')) {
      boton.addEventListener('click', () => abrirEdicion(boton.dataset.editar));
    }
    $('#editar-cancelar').addEventListener('click', () => volverAPerfil());
    $('#editar-borrar').addEventListener('click', () => { $('#editar-input').value = ''; $('#editar-input').focus(); });
    dialogo.querySelector('[data-vista="editar"]').addEventListener('submit', (event) => { event.preventDefault(); guardarCampo(); });
    $('#editar-clave').addEventListener('click', abrirClave);
    $('#clave-cancelar').addEventListener('click', () => volverAPerfil());
    dialogo.querySelector('[data-vista="clave"]').addEventListener('submit', (event) => { event.preventDefault(); guardarClave(); });

    // Escape en la vista de edicion vuelve a Perfil (sin guardar) en lugar de cerrar la ventana.
    dialogo.addEventListener('cancel', (event) => {
      if (campoActual && !ocupado) { event.preventDefault(); volverAPerfil(); }
    });
    dialogo.addEventListener('close', () => { descartarFoto(); limpiarClave(); campoActual = null; mostrarVista('perfil'); });
    window.onSesion?.(() => { if (dialogo.open) { if (window.getSesion()) pintar(); else dialogo.close(); } });
  }

  const valorGuardado = (id) => {
    const s = window.getSesion();
    return (id === 'telefono' ? s?.cuenta?.telefono : id === 'email' ? s?.email : s?.nombre) || '';
  };

  function aviso(elemento, texto) {
    elemento.textContent = texto || '';
    elemento.hidden = !texto;
  }

  function mostrarVista(vista) {
    for (const v of dialogo.querySelectorAll('[data-vista]')) v.hidden = v.dataset.vista !== vista;
    dialogo.setAttribute('aria-labelledby', { editar: 'editar-titulo', clave: 'clave-titulo' }[vista] || 'perfil-titulo');
  }

  // ---------- Vista Perfil ----------
  function pintar() {
    const s = window.getSesion();
    if (!s) return;
    for (const id of Object.keys(CAMPOS)) {
      const celda = $(`[data-valor="${id}"]`);
      const valor = valorGuardado(id);
      celda.textContent = valor || 'Sin registrar';
      celda.classList.toggle('is-empty', !valor);
    }
    const url = fotoPendiente?.url || s.cuenta?.foto_url || '';
    const foto = $('#perfil-foto');
    foto.hidden = !url;
    if (url) foto.src = url; else foto.removeAttribute('src');
    $('#perfil-iniciales').hidden = Boolean(url);
    $('#perfil-iniciales').textContent = (s.nombre || s.email || '?').trim().charAt(0).toUpperCase();
    $('#perfil-cambiar-foto').textContent = url ? 'Cambiar foto' : 'Elegir foto';
    $('#perfil-guardar-foto').hidden = !fotoPendiente;
  }

  function abrirPerfil() {
    if (!window.getSesion()) return;
    if (!dialogo) construir();
    descartarFoto();
    campoActual = null;
    aviso($('#perfil-mensaje'), '');
    mostrarVista('perfil');
    pintar();
    if (!dialogo.open) dialogo.showModal();
  }

  // ---------- Foto ----------
  function descartarFoto() {
    if (fotoPendiente) URL.revokeObjectURL(fotoPendiente.url);
    fotoPendiente = null;
    if (dialogo) { const input = $('#perfil-archivo'); if (input) input.value = ''; }
  }

  function elegirFoto(event) {
    const archivo = event.target.files?.[0];
    aviso($('#perfil-mensaje'), '');
    if (!archivo) return;
    if (!TIPOS_FOTO.includes(archivo.type) || archivo.size > MAX_FOTO) {
      event.target.value = '';
      aviso($('#perfil-mensaje'), 'La foto debe ser PNG, JPG o WebP y pesar menos de 2 MB.');
      return;
    }
    descartarFoto();
    fotoPendiente = { archivo, url: URL.createObjectURL(archivo) };   // vista previa; aun no esta guardada
    pintar();
  }

  async function guardarFoto() {
    if (!fotoPendiente || ocupado) return;
    ocupado = true;
    const boton = $('#perfil-guardar-foto');
    boton.disabled = true;
    boton.textContent = 'Guardando…';
    aviso($('#perfil-mensaje'), '');
    try {
      const datos = new FormData();
      datos.append('foto', fotoPendiente.archivo);
      let res;
      try {
        res = await fetch('/auth/perfil/foto', { method: 'PUT', headers: window.authHeaders(), body: datos });
      } catch {
        throw new Error('No hay conexión con el servidor. Revisa tu internet e intenta de nuevo.');
      }
      if (res.status === 404 || res.status === 405) throw new Error('Todavía no se puede guardar la foto: el servidor aún no tiene esa función.');
      if (!res.ok) {
        let detalle = null;
        try { detalle = (await res.json())?.detail; } catch { /* sin cuerpo */ }
        throw new Error(typeof detalle === 'string' ? detalle : 'No se pudo guardar la foto. Intenta de nuevo.');
      }
      descartarFoto();
      await window.refrescarCuenta();   // la foto confirmada viene del servidor (cuenta.foto_url)
      pintar();
    } catch (err) {
      aviso($('#perfil-mensaje'), err.message);   // la vista previa se queda, pero NO se muestra como guardada
    } finally {
      ocupado = false;
      boton.disabled = false;
      boton.textContent = 'Guardar';
    }
  }

  // ---------- Vista de edicion de un dato ----------
  function abrirEdicion(id) {
    const c = CAMPOS[id];
    campoActual = id;
    $('#editar-titulo').textContent = c.titulo;
    const input = $('#editar-input');
    input.type = c.tipo;
    input.autocomplete = c.autocomplete;
    input.inputMode = c.inputmode;
    input.maxLength = c.max;
    input.value = valorGuardado(id);
    aviso($('#editar-error'), '');
    input.removeAttribute('aria-invalid');
    mostrarVista('editar');
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  function volverAPerfil() {
    const id = campoActual;
    campoActual = null;
    limpiarClave();
    mostrarVista('perfil');
    pintar();
    (id === 'clave' ? $('#editar-clave') : $(`[data-editar="${id}"]`))?.focus();
  }

  // ---------- Cambiar la contraseña ----------
  // Contrato propuesto (hoy NO existe en el backend):
  //   POST /auth/password  body { actual, nueva }  -> 204/200; contraseña actual incorrecta -> 403
  // Mismas reglas que el registro: entre 8 y 72 caracteres (bcrypt no acepta mas de 72 bytes).
  const camposClave = () => ['#clave-actual', '#clave-nueva', '#clave-confirmar'].map((s) => $(s));
  function limpiarClave() {
    if (!dialogo) return;
    for (const input of camposClave()) { input.value = ''; input.removeAttribute('aria-invalid'); }   // nunca se quedan en la pagina
    aviso($('#clave-error'), '');
  }
  function abrirClave() {
    campoActual = 'clave';
    limpiarClave();
    aviso($('#perfil-mensaje'), '');
    $('#clave-usuario').value = window.getSesion()?.email || '';   // para que el gestor de contraseñas sepa de que cuenta es
    mostrarVista('clave');
    $('#clave-actual').focus();
  }
  async function guardarClave() {
    if (ocupado) return;
    const [actual, nueva, confirmar] = camposClave();
    const error = $('#clave-error');
    for (const input of camposClave()) input.removeAttribute('aria-invalid');
    const falla = (input, texto) => { aviso(error, texto); input.setAttribute('aria-invalid', 'true'); input.focus(); };
    if (!actual.value) { falla(actual, 'Escribe tu contraseña actual.'); return; }
    if (nueva.value.length < 8 || new TextEncoder().encode(nueva.value).length > 72) { falla(nueva, 'La nueva contraseña debe tener entre 8 y 72 caracteres.'); return; }
    if (nueva.value === actual.value) { falla(nueva, 'La nueva contraseña debe ser distinta de la actual.'); return; }
    if (confirmar.value !== nueva.value) { falla(confirmar, 'Las contraseñas no coinciden.'); return; }

    ocupado = true;
    const boton = $('#clave-guardar');
    boton.disabled = true;
    boton.textContent = 'Guardando…';
    aviso(error, '');
    try {
      // Se pasa el token: asi un 401 por contraseña equivocada no cierra la sesion (api() la cierra si no se pasa).
      await window.apiCuenta('/auth/password', { method: 'POST', body: { actual: actual.value, nueva: nueva.value }, token: window.getSesion()?.token });
      ocupado = false;
      volverAPerfil();
      aviso($('#perfil-mensaje'), 'Tu contraseña se cambió.');   // solo tras la confirmacion del servidor
    } catch (err) {
      if (err.status === 404 || err.status === 405) aviso(error, 'Todavía no se puede cambiar la contraseña: el servidor aún no tiene esa función.');
      else if (err.status === 401 || err.status === 403) falla(actual, 'La contraseña actual no es correcta.');
      else aviso(error, err.message);
    } finally {
      ocupado = false;
      boton.disabled = false;
      boton.textContent = 'Guardar';
    }
  }

  async function guardarCampo() {
    if (!campoActual || ocupado) return;
    const id = campoActual;
    const input = $('#editar-input');
    const error = $('#editar-error');
    const valor = input.value.trim();
    const problema = CAMPOS[id].valida(valor);
    if (problema) { aviso(error, problema); input.setAttribute('aria-invalid', 'true'); input.focus(); return; }
    if (valor === valorGuardado(id)) { aviso(error, 'No hay cambios que guardar.'); return; }

    ocupado = true;
    const boton = $('#editar-guardar');
    boton.disabled = true;
    boton.textContent = 'Guardando…';
    aviso(error, '');
    input.removeAttribute('aria-invalid');
    try {
      await window.apiCuenta('/auth/perfil', { method: 'PATCH', body: { [id]: valor } });   // 2xx = el servidor lo confirmo
      await window.refrescarCuenta();
      ocupado = false;
      volverAPerfil();
    } catch (err) {
      aviso(error, err.status === 404 || err.status === 405 ? SIN_SOPORTE : err.message);
      input.setAttribute('aria-invalid', 'true');
    } finally {
      ocupado = false;
      boton.disabled = false;
      boton.textContent = 'Guardar';
    }
  }

  window.abrirPerfil = abrirPerfil;
})();
