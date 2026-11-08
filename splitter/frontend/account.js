// Sesion compartida por index.html y planes.html: estado unico conectado al backend, barra superior
// (solo index), menu de perfil, muro de cuenta, pago (simulado) del plan Pro, cancelacion y "Mis audios".
(() => {
  'use strict';

  const NOMBRE_PLAN = { gratis: 'Gratis', pro: 'Pro' };

  // =====================================================================================
  // ESTADO DE SESION (unico, compartido por las dos paginas).
  //   Sin sesion: null
  //   Con sesion: { token, nombre, email, plan: 'gratis' | 'pro', cuenta }
  //     cuenta = respuesta de GET /suscripcion (limites, consumo del periodo, historial, fin_periodo...).
  // El token se guarda en localStorage para que la sesion siga al recargar y al pasar entre paginas.
  // =====================================================================================
  const CLAVE = 'splitter.sesion';
  let sesion = null;
  try { sesion = JSON.parse(localStorage.getItem(CLAVE)) || null; } catch { sesion = null; }
  if (sesion && (!sesion.token || !NOMBRE_PLAN[sesion.plan])) sesion = null;

  const $ = (id) => document.getElementById(id);
  const listeners = new Set();   // otras partes de la pagina (index.js, plans.js) se enteran de los cambios

  const authHeaders = () => (sesion ? { Authorization: `Bearer ${sesion.token}` } : {});
  const fecha = (iso) => (iso ? new Date(iso).toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric' }) : '');
  const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

  // ---------- Llamadas al backend ----------
  async function api(url, { method = 'GET', body, token } = {}) {
    const headers = token ? { Authorization: `Bearer ${token}` } : authHeaders();
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let res;
    try {
      res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new Error('No hay conexión con el servidor. Revisa tu internet e intenta de nuevo.');
    }
    let data = null;
    try { data = await res.json(); } catch { /* sin cuerpo JSON (204) */ }
    if (res.ok) return data;
    // Token vencido o borrado: la sesion se termina aqui para todas las paginas.
    if (res.status === 401 && !token && sesion) setSesion(null);
    const error = new Error(typeof data?.detail === 'string' ? data.detail
      : res.status >= 500 ? 'El servidor tuvo un problema. Intenta de nuevo en unos minutos.'
        : 'No se pudo completar la acción. Intenta de nuevo.');
    error.status = res.status;
    throw error;
  }

  const desdeCuenta = (token, cuenta) => ({ token, nombre: cuenta.nombre, email: cuenta.email, plan: cuenta.plan, cuenta });

  // GET /suscripcion: plan vigente y consumo. Se llama al cargar y despues de cada cambio de plan o trabajo.
  async function refrescarCuenta() {
    if (!sesion) return null;
    const token = sesion.token;
    try {
      const cuenta = await api('/suscripcion');
      if (sesion && sesion.token === token) setSesion(desdeCuenta(token, cuenta));
    } catch { /* sin conexion: se queda lo ultimo que se supo; 401 ya cerro la sesion */ }
    return sesion;
  }

  async function iniciarSesion(email, password) {
    const { token } = await api('/auth/login', { method: 'POST', body: { email, password } });
    const cuenta = await api('/suscripcion', { token });
    setSesion(desdeCuenta(token, cuenta));
  }

  async function registrarse(email, nombre, password) {
    await api('/auth/registro', { method: 'POST', body: { email, nombre, password } });
    await iniciarSesion(email, password);
  }

  async function cerrarSesion() {
    try { await api('/auth/logout', { method: 'POST' }); } catch { /* la sesion local se cierra igual */ }
    setSesion(null);
  }

  // ---------- Dialogos (mismo estilo que el muro de cuenta) ----------
  function crearDialogo(clase = '') {
    const dialog = document.createElement('dialog');
    dialog.className = `wall ${clase}`.trim();
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog || event.target.closest('[data-cerrar]')) dialog.close();   // clic en el fondo = cerrar
    });
    document.body.append(dialog);
    return dialog;
  }

  // ---------- Muro de cuenta ----------
  // Se exige cuenta solo para "Contratar Pro". Separar no la pide: sin cuenta se usan los limites de
  // invitado (por IP, en config.py), parecidos al plan gratis.
  let wall = null;
  function abrirLogin(modo) {
    const boton = $('nav-register') ? (modo === 'registro' ? $('nav-register') : document.querySelector('.nav-login')) : null;
    if (boton) boton.click();                                                          // index: dialogo de login existente
    else location.href = `index.html#${modo === 'registro' ? 'registro' : 'login'}`;   // planes: se abre alla
  }
  function pedirCuenta(motivo) {
    if (!wall) {
      wall = crearDialogo();
      wall.setAttribute('aria-labelledby', 'wall-title');
      wall.innerHTML = `<h2 id="wall-title">Necesitas una cuenta</h2>
        <p id="wall-text"></p>
        <div class="wall-actions">
          <button type="button" class="primary-button" data-wall="login">Iniciar sesión</button>
          <button type="button" class="secondary-button" data-wall="registro">Crear cuenta</button>
        </div>
        <button type="button" class="wall-close" data-cerrar>Ahora no</button>`;
      wall.addEventListener('click', (event) => {
        const action = event.target.closest('[data-wall]')?.dataset.wall;
        if (!action) return;
        wall.close();
        abrirLogin(action);
      });
    }
    wall.querySelector('#wall-text').textContent = motivo;
    if (!wall.open) wall.showModal();
  }

  // ---------- Contratar Pro (pago simulado) ----------
  // POST /suscripcion/pro  body { marca, ultimos4 }. El pago real queda pendiente: nunca se pide ni se manda
  // el numero completo de la tarjeta, solo la marca y los ultimos 4 digitos.
  let pago = null;
  function contratarPro() {
    if (!sesion) { pedirCuenta('Para contratar Pro necesitas una cuenta. Crea una o inicia sesión y vuelve aquí.'); return; }
    if (sesion.plan === 'pro') return;
    if (!pago) {
      pago = crearDialogo('wall-form');
      pago.setAttribute('aria-labelledby', 'pago-title');
      pago.innerHTML = `<form method="dialog" class="login-fields" novalidate>
          <h2 id="pago-title">Contratar Pro</h2>
          <p id="pago-text"></p>
          <label class="field" for="pago-marca"><span>Tarjeta</span>
            <select id="pago-marca" class="select" required>
              <option value="Visa">Visa</option><option value="Mastercard">Mastercard</option><option value="American Express">American Express</option>
            </select></label>
          <label class="field" for="pago-ultimos4"><span>Últimos 4 dígitos</span>
            <input id="pago-ultimos4" inputmode="numeric" autocomplete="off" maxlength="4" pattern="[0-9]{4}" required></label>
          <p class="wall-note">Pago de prueba: no se cobra nada y no se pide el número completo de la tarjeta.</p>
          <p id="pago-error" class="login-message" role="alert" hidden></p>
          <div class="wall-actions">
            <button id="pago-submit" type="submit" class="primary-button">Pagar</button>
            <button type="button" class="wall-close" data-cerrar>Ahora no</button>
          </div>
        </form>`;
      const form = pago.querySelector('form');
      const error = pago.querySelector('#pago-error');
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const ultimos4 = $('pago-ultimos4').value.trim();
        if (!/^\d{4}$/.test(ultimos4)) { error.textContent = 'Escribe los últimos 4 dígitos de tu tarjeta.'; error.hidden = false; return; }
        const boton = $('pago-submit');
        boton.disabled = true;
        error.hidden = true;
        try {
          const r = await api('/suscripcion/pro', { method: 'POST', body: { marca: $('pago-marca').value, ultimos4 } });
          await refrescarCuenta();
          pago.close();
          avisar('¡Ya tienes Pro!', `Tu plan Pro está activo hasta el ${fecha(r.fin_periodo)}. Tus próximos audios se guardan en «Mis audios».`);
        } catch (err) {
          error.textContent = err.message;
          error.hidden = false;
          if (err.status === 409) refrescarCuenta();
        } finally {
          boton.disabled = false;
        }
      });
    }
    const pro = sesion.cuenta?.pro;
    $('pago-text').textContent = pro
      ? `$${Number(pro.precio_mensual)} MXN por ${plural(pro.dias_periodo, 'día', 'días')}. No se renueva solo.`
      : 'Pago único por el periodo. No se renueva solo.';
    pago.querySelector('form').reset();
    pago.querySelector('#pago-error').hidden = true;
    pago.showModal();
    $('pago-ultimos4').focus();
  }

  // ---------- Avisos y confirmaciones ----------
  let aviso = null;
  function avisar(titulo, texto, { confirmar = '', onConfirm = null } = {}) {
    if (!aviso) aviso = crearDialogo();
    aviso.innerHTML = `<h2></h2><p></p><p class="login-message" role="alert" hidden></p><div class="wall-actions"></div>`;
    aviso.querySelector('h2').textContent = titulo;
    aviso.querySelector('p').textContent = texto;
    const acciones = aviso.querySelector('.wall-actions');
    if (confirmar) {
      const si = document.createElement('button');
      si.type = 'button';
      si.className = 'primary-button';
      si.textContent = confirmar;
      si.addEventListener('click', async () => {
        si.disabled = true;
        try { await onConfirm(); aviso.close(); } catch (err) {
          const error = aviso.querySelector('[role="alert"]');
          error.textContent = err.message;
          error.hidden = false;
        } finally { si.disabled = false; }
      });
      acciones.append(si);
    }
    const cerrar = document.createElement('button');
    cerrar.type = 'button';
    cerrar.className = confirmar ? 'wall-close' : 'primary-button';
    cerrar.dataset.cerrar = '';
    cerrar.textContent = confirmar ? 'Ahora no' : 'Entendido';
    acciones.append(cerrar);
    if (!aviso.open) aviso.showModal();
  }

  // POST /suscripcion/cancelar: pasa al plan gratis desde ahora (el pago simulado no se devuelve).
  function cancelarPro() {
    if (sesion?.plan !== 'pro') return;
    avisar('¿Cancelar el plan Pro?',
      'Pasas al plan Gratis desde ahora: dejas de ver «Mis audios», tus próximos audios se guardan 1 hora y vuelves a los límites gratis. Los trabajos que ya usaste en este periodo siguen contando. No se devuelve lo que pagaste.',
      {
        confirmar: 'Cancelar Pro',
        onConfirm: async () => { await api('/suscripcion/cancelar', { method: 'POST' }); await refrescarCuenta(); },
      });
  }

  // ---------- Mis audios (solo Pro) ----------
  // GET /trabajos. "Abrir" carga el trabajo en el reproductor de index.js (window.abrirTrabajo).
  const NOMBRE_PRESET = { '2stem': 'Voz y música', '4stem': 'Instrumentos (mejor calidad)', '4stem_fast': 'Instrumentos (rápida)', denoise: 'Limpiar ruido' };
  function estadoTrabajo(t) {
    if (t.estado === 'en_cola' || t.estado === 'procesando') return 'En proceso…';
    if (t.estado === 'error') return t.mensaje_error === 'Cancelado por el usuario' ? 'Cancelado' : 'No se pudo procesar';
    return t.disponible && t.expira_en ? `Disponible hasta el ${fecha(t.expira_en)}` : 'Ya no está disponible';
  }
  let audios = null;
  async function misAudios() {
    if (sesion?.plan !== 'pro') { location.href = 'planes.html'; return; }
    if (!audios) {
      audios = crearDialogo('wall-wide');
      audios.setAttribute('aria-labelledby', 'audios-title');
      audios.innerHTML = `<h2 id="audios-title">Mis audios</h2><p id="audios-note"></p>
        <ul id="audios-list" class="history-list"></ul>
        <button type="button" class="wall-close" data-cerrar>Cerrar</button>`;
    }
    const lista = audios.querySelector('#audios-list');
    const nota = audios.querySelector('#audios-note');
    const dias = Math.round((sesion.cuenta?.minutos_guardado || 0) / 1440);
    nota.textContent = `Con Pro tus audios se guardan ${plural(dias, 'día', 'días')}. Plan Pro hasta el ${fecha(sesion.cuenta?.fin_periodo)}.`;
    lista.replaceChildren(Object.assign(document.createElement('li'), { className: 'history-empty', textContent: 'Cargando…' }));
    if (!audios.open) audios.showModal();
    let items;
    try {
      items = await api('/trabajos');
    } catch (err) {
      if (err.status === 403) { audios.close(); refrescarCuenta(); return; }   // el plan Pro vencio
      lista.replaceChildren(Object.assign(document.createElement('li'), { className: 'history-empty', textContent: err.message }));
      return;
    }
    lista.replaceChildren();
    if (!items.length) {
      lista.append(Object.assign(document.createElement('li'), { className: 'history-empty', textContent: 'Todavía no tienes audios. Aquí aparecerán los que proceses.' }));
      return;
    }
    for (const t of items) {
      const fila = document.createElement('li');
      fila.className = 'history-item';
      const texto = document.createElement('div');
      const nombre = document.createElement('strong');
      nombre.textContent = t.nombre_original;
      const detalle = document.createElement('span');
      detalle.textContent = [NOMBRE_PRESET[t.preset] || t.preset, fecha(t.creado_en), estadoTrabajo(t)].filter(Boolean).join(' · ');
      texto.append(nombre, detalle);
      fila.append(texto);
      if (t.estado === 'completado' && t.disponible && window.abrirTrabajo) {
        const abrir = document.createElement('button');
        abrir.type = 'button';
        abrir.className = 'secondary-button';
        abrir.textContent = 'Abrir';
        abrir.addEventListener('click', async () => {
          abrir.disabled = true;
          const ok = await window.abrirTrabajo(t.id);
          abrir.disabled = false;
          if (ok) audios.close(); else detalle.textContent = 'Este audio ya no está disponible.';
        });
        fila.append(abrir);
      }
      lista.append(fila);
    }
  }

  // ---------- Barra (solo index.html) ----------
  const header = document.querySelector('.site-header');
  if (header) {
    const loginLink = document.querySelector('.nav-login');
    const registerButton = $('nav-register');
    const profileBox = $('profile');
    const planesLink = $('nav-planes-link');
    const planPill = $('nav-plan');
    const profileButton = $('profile-button');
    const profileMenu = $('profile-menu');
    const profileInitial = $('profile-initial');
    const profileIcon = profileButton.querySelector('.profile-icon');
    const compact = matchMedia('(max-width: 640px)');

    // Sin sesion el icono solo existe en movil, donde guarda los enlaces colapsados.
    const menuHasItems = () => Boolean(sesion) || compact.matches;

    function renderBar() {
      const logged = Boolean(sesion);
      const pro = sesion?.plan === 'pro';
      header.dataset.sesion = logged ? sesion.plan : 'none';
      loginLink.hidden = logged;
      registerButton.hidden = logged;
      planesLink.hidden = logged;
      planPill.hidden = !logged;
      profileBox.hidden = !logged && !compact.matches;
      planPill.textContent = pro ? NOMBRE_PLAN.pro : 'Planes';
      planPill.setAttribute('aria-label', logged ? `Plan actual: ${NOMBRE_PLAN[sesion.plan]}. Ver planes` : 'Ver planes');
      profileInitial.hidden = !logged;
      profileIcon.style.display = logged ? 'none' : '';   // en un <svg> la propiedad .hidden no existe
      if (logged) {
        const c = sesion.cuenta;
        profileInitial.textContent = (sesion.nombre || sesion.email || '?').trim().charAt(0).toUpperCase();
        $('menu-name').textContent = sesion.nombre || '';
        $('menu-email').textContent = sesion.email || '';
        $('menu-plan').textContent = c
          ? `Plan ${NOMBRE_PLAN[sesion.plan]} · ${c.trabajos_usados} de ${c.trabajos_por_mes} trabajos usados`
          : `Plan ${NOMBRE_PLAN[sesion.plan]}`;
      }
      for (const el of profileMenu.querySelectorAll('.menu-session')) el.hidden = !logged;
      for (const el of profileMenu.querySelectorAll('.menu-guest')) el.hidden = logged;
      for (const el of profileMenu.querySelectorAll('.menu-pro')) el.hidden = !pro;
      for (const el of profileMenu.querySelectorAll('.menu-free')) el.hidden = !logged || pro;
      profileButton.setAttribute('aria-label', logged ? `Cuenta de ${sesion.nombre || sesion.email}` : 'Cuenta');
      if (!menuHasItems()) closeMenu();
    }
    listeners.add(renderBar);

    // ---------- Menu del perfil ----------
    const focusables = () => [...profileMenu.querySelectorAll('a[href], button')].filter((el) => !el.hidden && el.offsetParent !== null);
    function openMenu(focusFirst = false) {
      profileMenu.hidden = false;
      profileButton.setAttribute('aria-expanded', 'true');
      if (focusFirst) focusables()[0]?.focus();
    }
    function closeMenu({ returnFocus = false } = {}) {
      if (profileMenu.hidden) return;
      profileMenu.hidden = true;
      profileButton.setAttribute('aria-expanded', 'false');
      if (returnFocus) profileButton.focus();
    }
    profileButton.addEventListener('click', () => {
      if (!menuHasItems()) { loginLink.click(); return; }
      if (profileMenu.hidden) { openMenu(); refrescarCuenta(); } else closeMenu();
    });
    profileButton.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown' && menuHasItems()) { event.preventDefault(); openMenu(true); }
    });
    profileMenu.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
      const items = focusables();
      const index = items.indexOf(document.activeElement);
      event.preventDefault();
      items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !profileMenu.hidden) closeMenu({ returnFocus: true });
    });
    document.addEventListener('pointerdown', (event) => {
      if (!profileMenu.hidden && !event.target.closest('.profile')) closeMenu();
    });
    document.addEventListener('focusin', (event) => {
      if (!profileMenu.hidden && !event.target.closest('.profile')) closeMenu();
    });
    profileMenu.addEventListener('click', (event) => { if (event.target.closest('a, button')) closeMenu(); });
    compact.addEventListener('change', renderBar);

    // "Registrate" abre el dialogo existente (login.js) y lo pasa a su modo "Crear cuenta".
    registerButton.addEventListener('click', () => {
      setTimeout(() => { const s = $('switch-link'); if (s?.dataset.modeTarget === 'register') s.click(); }, 0);
    });

    // Llegada desde planes.html (#login / #registro): abre el dialogo ya existente.
    addEventListener('load', () => {
      const destino = location.hash;
      if (destino !== '#login' && destino !== '#registro') return;
      history.replaceState(null, '', location.pathname + location.search);
      if (!sesion) (destino === '#registro' ? registerButton : loginLink).click();
    });

    $('menu-audios').addEventListener('click', () => { misAudios(); });
    $('menu-cancel').addEventListener('click', () => { cancelarPro(); });
    $('menu-logout').addEventListener('click', () => { cerrarSesion(); });
  }

  // ---------- Punto unico de cambio de estado ----------
  function setSesion(next) {
    if (next && (!next.token || !NOMBRE_PLAN[next.plan])) { console.warn('Sesión inválida', next); return; }
    sesion = next || null;
    try { if (sesion) localStorage.setItem(CLAVE, JSON.stringify(sesion)); else localStorage.removeItem(CLAVE); } catch { /* sin almacenamiento */ }
    listeners.forEach((fn) => fn());
  }
  // Cambios hechos en la otra pestana/pagina.
  addEventListener('storage', (event) => {
    if (event.key !== CLAVE) return;
    try { sesion = JSON.parse(event.newValue) || null; } catch { sesion = null; }
    listeners.forEach((fn) => fn());
  });

  Object.assign(window, {
    getSesion: () => sesion,
    authHeaders,
    onSesion: (fn) => { listeners.add(fn); fn(); },
    setSesion,
    pedirCuenta,
    iniciarSesion,
    registrarse,
    refrescarCuenta,
    contratarPro,
    cancelarPro,
  });

  listeners.forEach((fn) => fn());
  refrescarCuenta();   // el plan pudo cambiar (vencer, cancelarse) desde la ultima visita
})();
