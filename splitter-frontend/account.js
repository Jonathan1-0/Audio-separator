// Sesion compartida por index.html y planes.html: estado unico, barra superior (solo index), menu de perfil
// y muro de cuenta. Solo capa visual: ningun endpoint se llama todavia.
(() => {
  'use strict';

  const NOMBRE_PLAN = { gratis: 'Gratis', pro: 'Pro' };   // los limites y precios viven en plans.js

  // =====================================================================================
  // ESTADO DE SESION (unico, compartido por las dos paginas).
  //   Sin sesion: null
  //   Con sesion: { token, nombre, email, plan: 'gratis' | 'pro' }
  //
  // Se guarda en localStorage ('splitter.sesion') SOLO para que el estado sobreviva al navegar entre
  // index.html y planes.html mientras no haya backend conectado.
  // TODO (backend): cuando exista el login real, guardar el token con el mecanismo definitivo.
  //
  // TODO (backend): FALTA un endpoint tipo GET /auth/me que devuelva el plan actual y el consumo del
  // periodo. Hoy POST /auth/login solo regresa { token, expira_en, nombre }, asi que el plan no se
  // puede saber desde el frontend. Mientras no exista, `plan` se llena a mano.
  //
  // PARA VER TODOS LOS ESTADOS DESDE LA CONSOLA DEL NAVEGADOR (en cualquiera de las dos paginas):
  //   setSesion({ token: 'x', nombre: 'Ana Perez', email: 'ana@ejemplo.com', plan: 'gratis' })  // con sesion, gratis
  //   setSesion({ token: 'x', nombre: 'Ana Perez', email: 'ana@ejemplo.com', plan: 'pro' })     // con sesion, pro
  //   setSesion(null)                                                                           // sin sesion
  // =====================================================================================
  const CLAVE = 'splitter.sesion';
  let sesion = null;
  try { sesion = JSON.parse(localStorage.getItem(CLAVE)) || null; } catch { sesion = null; }
  if (sesion && !NOMBRE_PLAN[sesion.plan]) sesion = null;

  // ---------- Enganches al backend (vacios a proposito; endpoints que YA existen) ----------
  // POST /auth/login     body { email, password }            -> { token, expira_en, nombre }
  async function iniciarSesion(email, password) { /* TODO */ }
  // POST /auth/registro  body { email, nombre, password }
  async function registrarse(email, nombre, password) { /* TODO */ }
  // POST /auth/logout    header Authorization: Bearer <token>
  async function cerrarSesion() { /* TODO */ }
  // POST /suscripcion/pro  body { marca, ultimos4 }  (pago simulado: nunca la tarjeta completa)
  async function contratarPro(marca, ultimos4) { /* TODO */ }
  // GET /trabajos        header Authorization: Bearer <token>
  async function misAudios() { /* TODO */ }
  void iniciarSesion; void registrarse;

  const $ = (id) => document.getElementById(id);
  const listeners = new Set();   // otras partes de la pagina (plans.js) se enteran de los cambios

  // ---------- Muro de cuenta ----------
  // Se exige cuenta al pulsar "Separar" / "Limpiar audio" (index) y "Contratar Pro" (planes).
  // NOTA: el backend todavia permite invitados sin cuenta (limites por IP en config.py). Este muro es
  // solo del frontend por ahora.
  let wall = null;
  function abrirLogin(modo) {
    const boton = $('nav-register') ? (modo === 'registro' ? $('nav-register') : document.querySelector('.nav-login')) : null;
    if (boton) boton.click();                                                          // index: dialogo de login existente
    else location.href = `index.html#${modo === 'registro' ? 'registro' : 'login'}`;   // planes: se abre alla
  }
  function pedirCuenta(motivo) {
    if (!wall) {
      wall = document.createElement('dialog');
      wall.className = 'wall';
      wall.setAttribute('aria-labelledby', 'wall-title');
      wall.innerHTML = `<h2 id="wall-title">Necesitas una cuenta</h2>
        <p id="wall-text"></p>
        <div class="wall-actions">
          <button type="button" class="primary-button" data-wall="login">Iniciar sesión</button>
          <button type="button" class="secondary-button" data-wall="registro">Crear cuenta</button>
        </div>
        <button type="button" class="wall-close" data-wall="cerrar">Ahora no</button>`;
      wall.addEventListener('click', (event) => {
        const action = event.target.closest('[data-wall]')?.dataset.wall;
        if (event.target === wall || action === 'cerrar') { wall.close(); return; }   // clic en el fondo = cerrar
        if (!action) return;
        wall.close();
        abrirLogin(action);
      });
      document.body.append(wall);
    }
    wall.querySelector('#wall-text').textContent = motivo;
    if (!wall.open) wall.showModal();
  }
  window.pedirCuenta = pedirCuenta;
  window.getSesion = () => sesion;
  window.contratarPro = contratarPro;

  // Index: el muro va antes que la logica de separacion (captura el submit del formulario y lo detiene).
  document.addEventListener('submit', (event) => {
    if (sesion || !event.target.contains($('start-button'))) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    pedirCuenta('Para separar o limpiar tu audio necesitas una cuenta gratuita. Es rápido y puedes empezar al instante.');
  }, true);

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
      header.dataset.sesion = logged ? sesion.plan : 'none';
      loginLink.hidden = logged;
      registerButton.hidden = logged;
      planesLink.hidden = logged;
      planPill.hidden = !logged;
      profileBox.hidden = !logged && !compact.matches;
      planPill.textContent = sesion?.plan === 'pro' ? NOMBRE_PLAN.pro : 'Planes';
      planPill.setAttribute('aria-label', logged ? `Plan actual: ${NOMBRE_PLAN[sesion.plan]}. Ver planes` : 'Ver planes');
      profileInitial.hidden = !logged;
      profileIcon.hidden = logged;
      if (logged) {
        profileInitial.textContent = (sesion.nombre || sesion.email || '?').trim().charAt(0).toUpperCase();
        $('menu-name').textContent = sesion.nombre || '';
        $('menu-email').textContent = sesion.email || '';
        $('menu-plan').textContent = `Plan actual: ${NOMBRE_PLAN[sesion.plan]}`;
      }
      for (const el of profileMenu.querySelectorAll('.menu-session')) el.hidden = !logged;
      for (const el of profileMenu.querySelectorAll('.menu-guest')) el.hidden = logged;
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
      if (profileMenu.hidden) openMenu(); else closeMenu();
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
      (destino === '#registro' ? registerButton : loginLink).click();
    });

    $('menu-audios').addEventListener('click', () => { misAudios(); });
    $('menu-logout').addEventListener('click', async () => {
      await cerrarSesion();
      setSesion(null);   // simulado: con el backend conectado, esto se hara tras responder POST /auth/logout
    });
  }

  // ---------- Punto unico de cambio de estado (API de consola) ----------
  function setSesion(next) {
    if (next && !NOMBRE_PLAN[next.plan]) { console.warn(`Plan desconocido: "${next.plan}". Usa ${Object.keys(NOMBRE_PLAN).join(' | ')}.`); return; }
    sesion = next || null;
    try { if (sesion) localStorage.setItem(CLAVE, JSON.stringify(sesion)); else localStorage.removeItem(CLAVE); } catch { /* sin almacenamiento */ }
    listeners.forEach((fn) => fn());
  }
  window.setSesion = setSesion;
  window.onSesion = (fn) => { listeners.add(fn); fn(); };   // plans.js se suscribe aqui
  // Cambios hechos en la otra pestana/pagina.
  addEventListener('storage', (event) => {
    if (event.key !== CLAVE) return;
    try { sesion = JSON.parse(event.newValue) || null; } catch { sesion = null; }
    listeners.forEach((fn) => fn());
  });

  listeners.forEach((fn) => fn());
})();
