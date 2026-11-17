// Sesion compartida por index.html y planes.html: estado unico conectado al backend, barra superior
// (solo index), menu de perfil, muro de cuenta, plan Pro ("Proximamente" mientras no haya pagos), cancelacion y "Mis audios".
(() => {
  'use strict';

  const NOMBRE_PLAN = { gratis: 'Gratis', pro: 'Pro', admin: 'Admin' };

  // =====================================================================================
  // ESTADO DE SESION (unico, compartido por las dos paginas).
  //   Sin sesion: null
  //   Con sesion: { token, nombre, email, plan: 'gratis' | 'pro', cuenta }
  //     cuenta = respuesta de GET /suscripcion (limites, consumo del periodo, historial, fin_periodo...).
  // La sesion real viaja en una cookie HttpOnly que pone el servidor: este JavaScript no la puede leer
  // (asi un script inyectado no la roba). "token" es solo un identificador de la sesion para esta pagina;
  // se guarda en localStorage para saber, al recargar, que habia una sesion abierta.
  // =====================================================================================
  const CLAVE = 'splitter.sesion';
  let sesion = null;
  try { sesion = JSON.parse(localStorage.getItem(CLAVE)) || null; } catch { sesion = null; }
  if (sesion && (!sesion.token || !NOMBRE_PLAN[sesion.plan])) sesion = null;
  // Sesiones de antes de la cookie guardaban el token real (64 hex): se borran y se vuelve a entrar.
  if (sesion && /^[0-9a-f]{64}$/.test(sesion.token)) { sesion = null; try { localStorage.removeItem(CLAVE); } catch { /* nada */ } }

  const $ = (id) => document.getElementById(id);
  const listeners = new Set();   // otras partes de la pagina (index.js, plans.js) se enteran de los cambios

  // La cookie de sesion va sola en cada fetch a esta misma pagina: no hace falta cabecera.
  // Se deja la funcion porque index.js y profile.js la usan.
  const authHeaders = () => ({});
  const fecha = (iso) => (iso ? new Date(iso).toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric' }) : '');
  const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

  // ---------- Llamadas al backend ----------
  // "token": la llamada es de esa sesion; un 401 no cierra la sesion guardada (se maneja donde se llamo).
  async function api(url, { method = 'GET', body, token } = {}) {
    const headers = authHeaders();
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
    // Cuenta registrada que aun no confirma su correo: el servidor envio un codigo y lo pide.
    error.confirmar = res.headers.get('X-Splitter-Confirmar') === 'requerido';
    error.pendiente = res.headers.get('X-Splitter-Pendiente') || '';
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

  // El servidor pone la cookie de sesion; aqui solo llega su identificador ("sesion").
  async function abrirConRespuesta(respuesta) {
    const token = respuesta.sesion || respuesta.token;
    const cuenta = await api('/suscripcion', { token });
    setSesion(desdeCuenta(token, cuenta));
  }
  async function iniciarSesion(email, password) {
    await abrirConRespuesta(await api('/auth/login', { method: 'POST', body: { email, password } }));
  }
  // Registro en dos pasos: se crea la cuenta y llega un codigo al correo; con el codigo se confirma y se entra.
  //   POST /auth/registro            -> { pendiente, correo, mensaje }
  //   POST /auth/registro/confirmar  { pendiente, codigo } -> sesion
  //   POST /auth/registro/reenviar   { email } -> { pendiente, mensaje }
  const registrarse = (email, nombre, password) => api('/auth/registro', { method: 'POST', body: { email, nombre, password } });
  async function confirmarRegistro(pendiente, codigo) {
    await abrirConRespuesta(await api('/auth/registro/confirmar', { method: 'POST', body: { pendiente, codigo } }));
  }
  const reenviarCodigo = (email) => api('/auth/registro/reenviar', { method: 'POST', body: { email } });

  // Recuperar contrasena: el backend siempre responde 200 con un mensaje (no revela si el correo existe).
  const recuperarPassword = (email) => api('/auth/recuperar', { method: 'POST', body: { email } });
  const restablecerPassword = (codigo, password) => api('/auth/restablecer', { method: 'POST', body: { codigo, password } });
  // Que proveedores sociales estan configurados en el servidor: { google: bool, facebook: bool }.
  const proveedoresSociales = () => api('/auth/social').catch(() => ({}));

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

  // ---------- Contratar Pro ----------
  // Los pagos todavia no estan abiertos: Pro se muestra como "Proximamente".
  function contratarPro() {
    if (!sesion) { pedirCuenta('Para contratar Pro necesitas una cuenta. Crea una o inicia sesión y vuelve aquí.'); return; }
    if (sesion.plan === 'pro' || sesion.plan === 'admin') return;
    avisar('Pro llega muy pronto', 'Estamos preparando los pagos. Mientras tanto tienes 15 audios gratis cada 30 días.');
  }

  function avisarProActivo(fin) {
    avisar('¡Ya tienes Pro!', `Se renovará automáticamente${fin ? ` el ${fecha(fin)}` : ''}. Puedes cancelar cuando quieras.`);
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

  // Tiempo de guardado del plan gratis (GET /suscripcion/planes, sin auth). Se cachea en memoria.
  let planesCache = null;
  // Minutos de guardado -> "N minutos", "1 hora", "N horas" o "N días".
  function guardadoTexto(min) {
    if (!(min > 0)) return 'por tiempo limitado';
    if (min % 1440 === 0) return plural(min / 1440, 'día', 'días');
    if (min % 60 === 0) return min === 60 ? '1 hora' : `${min / 60} horas`;
    return plural(min, 'minuto', 'minutos');
  }
  async function guardadoGratis() {
    try {
      planesCache ||= await api('/suscripcion/planes');
      const min = planesCache.planes.find((p) => p.nombre === 'gratis')?.minutos_guardado;
      return guardadoTexto(min);
    } catch { return ''; }
  }

  // POST /suscripcion/cancelar: ya no se renueva; Pro sigue hasta el fin del periodo pagado.
  // Cancelar no quita Pro de inmediato: sigue hasta el fin del periodo pagado y despues pasa a Gratis.
  async function cancelarPro() {
    if (sesion?.plan !== 'pro') return;
    if (sesion.cuenta?.cancelar_al_final) { reanudarPro(); return; }
    const guardado = await guardadoGratis();
    const frase = guardado ? `tus próximos audios se guardarán ${guardado}` : 'tus próximos audios se guardarán por menos tiempo';
    const hasta = fecha(sesion.cuenta?.fin_periodo);
    avisar('¿Cancelar el plan Pro?',
      `Ya no se renovará. Sigues con Pro hasta el ${hasta || 'fin de tu periodo'}, que ya pagaste. Después pasas al plan Gratis: ${frase} y vuelves a los límites gratis. Puedes cambiar de opinión antes de esa fecha.`,
      {
        confirmar: 'Cancelar Pro',
        onConfirm: async () => { await api('/suscripcion/cancelar', { method: 'POST' }); await refrescarCuenta(); },
      });
  }

  function reanudarPro() {
    avisar('¿Seguir con Pro?', `Tu plan Pro se renovará el ${fecha(sesion.cuenta?.fin_periodo)} como siempre.`, {
      confirmar: 'Seguir con Pro',
      onConfirm: async () => { await api('/suscripcion/reanudar', { method: 'POST' }); await refrescarCuenta(); },
    });
  }

  // ---------- Mis audios (solo Pro) ----------
  // GET /trabajos. "Abrir" carga el trabajo en el reproductor de index.js (window.abrirTrabajo).
  const NOMBRE_PRESET = { '2stem': 'Voz y música', '4stem': 'Instrumentos (mejor calidad)', '4stem_fast': 'Instrumentos (rápida)', denoise: 'Limpiar ruido' };
  function estadoTrabajo(t) {
    if (t.estado === 'en_cola' || t.estado === 'procesando') return 'En proceso…';
    if (t.estado === 'error') return t.mensaje_error === 'Cancelado por el usuario' ? 'Cancelado' : 'No se pudo procesar';
    if (!(t.disponible && t.expira_en)) return 'Ya no está disponible';
    // Si vence en menos de un dia (plan Gratis: 1 hora) se muestra la hora; si no, la fecha.
    const vence = new Date(t.expira_en);
    if (vence - Date.now() < 24 * 3600 * 1000) return `Disponible hasta las ${vence.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' })}`;
    return `Disponible hasta el ${fecha(t.expira_en)}`;
  }
  // Etiquetas de la ficha por tipo de trabajo (tipo · calidad).
  const PRESET_ETIQUETAS = { '2stem': ['Voz y música'], '4stem': ['Instrumentos', 'Mejor calidad'], '4stem_fast': ['Instrumentos', 'Rápida'], denoise: ['Limpiar ruido'] };
  const SVG = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${d}</svg>`;
  const ICONO_CALENDARIO = SVG('<rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M8 3v4M16 3v4M3.5 10h17"/>');
  const ICONO_RELOJ = SVG('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>');
  const ICONO_BASURA = SVG('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12.5a1.5 1.5 0 0 0 1.5 1.4h7a1.5 1.5 0 0 0 1.5-1.4L18 7M9 7V4.5h6V7"/>');
  // Onda de cinco barras, en blanco (color del texto).
  const ICONO_ONDA = '<svg viewBox="0 0 48 48" width="40" height="40" fill="currentColor" aria-hidden="true" focusable="false"><rect x="6" y="20" width="5" height="10" rx="2.5"/><rect x="14" y="13" width="5" height="24" rx="2.5"/><rect x="22" y="6" width="5" height="36" rx="2.5"/><rect x="30" y="14" width="5" height="22" rx="2.5"/><rect x="38" y="20" width="5" height="10" rx="2.5"/></svg>';
  // Debe coincidir con STEM_LABELS de index.js.
  const NOMBRE_PISTA = { vocals: 'Voz', instrumental: 'Música sin voz', drums: 'Batería', bass: 'Bajo', other: 'Otros instrumentos', voice: 'Voz' };
  const minSeg = (seg) => `${Math.floor(seg / 60)}:${String(Math.round(seg % 60)).padStart(2, '0')}`;
  // pistas_pedidas llega como texto separado por comas ("vocals,drums").
  const nombrePistas = (v) => (Array.isArray(v) ? v : String(v || '').split(',')).map((x) => x.trim()).filter(Boolean)
    .map((x) => NOMBRE_PISTA[x] || x).join(', ');
  let audios = null;
  async function misAudios() {
    if (!sesion) { location.href = 'planes.html'; return; }   // "Mis audios" es de cualquier cuenta; sin cuenta no hay audios
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
    const guardado = guardadoTexto(sesion.cuenta?.minutos_guardado);
    nota.textContent = sesion.plan === 'pro'
      ? `Con Pro tus audios se guardan ${plural(dias, 'día', 'días')}. Se renueva el ${fecha(sesion.cuenta?.fin_periodo)}.`
      : sesion.plan === 'admin' ? `Tus audios se guardan ${plural(dias, 'día', 'días')}.`
      : `Tus audios se guardan ${guardado}. Con Pro se guardan una semana.`;
    lista.replaceChildren(Object.assign(document.createElement('li'), { className: 'history-empty', textContent: 'Cargando…' }));
    if (!audios.open) audios.showModal();
    let items;
    try {
      items = await api('/trabajos');
    } catch (err) {
      lista.replaceChildren(Object.assign(document.createElement('li'), { className: 'history-empty', textContent: err.message }));
      return;
    }
    lista.replaceChildren();
    const vacio = () => Object.assign(document.createElement('li'), { className: 'history-empty', textContent: 'Todavía no tienes audios. Aquí aparecerán los que proceses.' });
    if (!items.length) { lista.append(vacio()); return; }
    for (const t of items) {
      const fila = document.createElement('li');
      fila.className = 'history-item';
      // Ficha: icono de onda (blanco), nombre, etiquetas (tipo · calidad · duracion), pistas y fechas.
      const icono = document.createElement('span');
      icono.className = 'history-icon';
      icono.setAttribute('aria-hidden', 'true');
      icono.innerHTML = ICONO_ONDA;
      const texto = document.createElement('div');
      texto.className = 'history-info';
      const nombre = document.createElement('strong');
      nombre.textContent = t.nombre_original;
      const etiquetas = document.createElement('span');
      etiquetas.className = 'history-tags';
      const tags = [...(PRESET_ETIQUETAS[t.preset] || [t.preset]), t.duracion_audio_seg != null ? minSeg(t.duracion_audio_seg) : ''].filter(Boolean);
      tags.forEach((tag, i) => {
        if (i) etiquetas.append(Object.assign(document.createElement('i'), { className: 'history-dot', textContent: '·' }));
        etiquetas.append(Object.assign(document.createElement('b'), { className: 'history-tag', textContent: tag }));
      });
      const pistas = document.createElement('span');
      pistas.className = 'history-stems';
      pistas.textContent = nombrePistas(t.pistas_pedidas);
      const detalle = document.createElement('span');
      detalle.className = 'history-meta';
      const fechaEl = document.createElement('em');
      fechaEl.innerHTML = ICONO_CALENDARIO;
      fechaEl.append(fecha(t.creado_en));
      const estadoEl = document.createElement('em');
      estadoEl.innerHTML = ICONO_RELOJ;
      estadoEl.append(estadoTrabajo(t));
      detalle.append(fechaEl, estadoEl);
      texto.append(nombre, etiquetas);
      if (pistas.textContent) texto.append(pistas);
      texto.append(detalle);
      fila.append(icono, texto);
      if (t.estado === 'completado' && t.disponible && window.abrirTrabajo) {
        const abrir = document.createElement('button');
        abrir.type = 'button';
        abrir.className = 'secondary-button';
        abrir.textContent = 'Abrir';
        abrir.addEventListener('click', async () => {
          abrir.disabled = true;
          const ok = await window.abrirTrabajo(t.id);
          abrir.disabled = false;
          if (ok) audios.close(); else estadoEl.replaceChildren(document.createRange().createContextualFragment(ICONO_RELOJ), 'Este audio ya no está disponible.');
        });
        fila.append(abrir);
      }
      // Borrar (o cancelar si sigue en proceso): DELETE /api/jobs/{id}, con confirmacion.
      const activo = t.estado === 'en_cola' || t.estado === 'procesando';
      const borrar = document.createElement('button');
      borrar.type = 'button';
      borrar.className = 'history-delete';
      borrar.innerHTML = ICONO_BASURA;
      borrar.setAttribute('aria-label', activo ? `Cancelar el trabajo «${t.nombre_original}»` : `Borrar «${t.nombre_original}»`);
      borrar.title = activo ? 'Cancelar' : 'Borrar';
      borrar.addEventListener('click', () => {
        avisar(activo ? '¿Cancelar este trabajo?' : '¿Borrar este audio?',
          activo ? 'Se detiene el proceso de «' + t.nombre_original + '».' : `«${t.nombre_original}» se eliminará y no se podrá recuperar.`,
          {
            confirmar: activo ? 'Cancelar trabajo' : 'Borrar',
            onConfirm: async () => {
              try {
                await api('/api/jobs/' + t.id, { method: 'DELETE' });
              } catch (err) {
                if (err.status === 404) { misAudios(); return; }   // ya no existe: se recarga la lista
                throw err;
              }
              window.olvidarTrabajo?.(t.id);
              fila.remove();
              if (!lista.querySelector('.history-item')) lista.append(vacio());
            },
          });
      });
      fila.append(borrar);
      lista.append(fila);
    }
  }

  // ---------- Barra (solo index.html) ----------
  const header = document.querySelector('.site-header');
  if (header) {
    const loginLink = document.querySelector('.nav-login');
    const registerButton = $('nav-register');
    const profileBox = $('profile');
    const planPill = $('nav-plan');
    const profileButton = $('profile-button');
    const profileMenu = $('profile-menu');
    const profileInitial = $('profile-initial');
    const profilePhoto = $('profile-photo');
    const profileIcon = profileButton.querySelector('.profile-icon');
    const compact = matchMedia('(max-width: 640px)');

    // Sin sesion el icono solo existe en movil, donde guarda los enlaces colapsados.
    const menuHasItems = () => Boolean(sesion) || compact.matches;

    function renderBar() {
      const logged = Boolean(sesion);
      const pro = sesion?.plan === 'pro';
      const admin = sesion?.plan === 'admin';
      header.dataset.sesion = logged ? sesion.plan : 'none';
      loginLink.hidden = logged;
      registerButton.hidden = logged;
      planPill.hidden = (!logged && compact.matches) || pro || admin;   // en movil sin sesion va dentro del menu; con Pro o admin no hay plan que ofrecer
      profileBox.hidden = !logged && !compact.matches;
      planPill.textContent = 'Planes';
      planPill.setAttribute('aria-label', logged ? `Plan actual: ${NOMBRE_PLAN[sesion.plan]}. Ver planes` : 'Ver planes');
      profileIcon.style.display = logged ? 'none' : '';   // en un <svg> la propiedad .hidden no existe
      if (logged) {
        const c = sesion.cuenta;
        // Foto si el servidor la entrega (cuenta.foto_url); si no, la inicial.
        const foto = c?.foto_url || '';
        profilePhoto.hidden = !foto;
        profileInitial.hidden = Boolean(foto);
        if (foto) profilePhoto.src = foto; else profilePhoto.removeAttribute('src');
        profileInitial.textContent = (sesion.nombre || sesion.email || '?').trim().charAt(0).toUpperCase();
        $('menu-name').textContent = sesion.nombre || '';
        $('menu-email').textContent = sesion.email || '';
        $('menu-plan').textContent = admin
          ? (c ? `Administrador · sin límite de trabajos (${c.trabajos_usados} en este periodo)` : 'Administrador · sin límite de trabajos')
          : `Plan ${NOMBRE_PLAN[sesion.plan]}${pro ? ' · audios ilimitados' : ''}`;
        // Plan de pago: estado segun el fin del periodo. Plan gratis: cuanto le queda del periodo.
        const estado = $('menu-state');
        const uso = $('menu-usage');
        const vigente = c?.fin_periodo ? new Date(c.fin_periodo) > new Date() : null;
        estado.hidden = admin || !(pro && vigente !== null);
        estado.dataset.activo = String(vigente === true);
        estado.textContent = !vigente ? 'Vencido' : c?.cancelar_al_final ? `Termina el ${fecha(c.fin_periodo)}` : 'Activo';
        $('menu-cancel').textContent = c?.cancelar_al_final ? 'Seguir con Pro' : 'Cancelar plan Pro';
        uso.hidden = pro || admin || !c || c.trabajos_por_mes == null;
        if (!uso.hidden) {
          const quedan = Math.max(c.trabajos_por_mes - c.trabajos_usados, 0);
          uso.textContent = `Te ${quedan === 1 ? 'queda' : 'quedan'} ${quedan} de ${plural(c.trabajos_por_mes, 'trabajo', 'trabajos')} este periodo`;
        }
      } else {
        profilePhoto.hidden = true;
        profileInitial.hidden = true;
      }
      for (const el of profileMenu.querySelectorAll('.menu-session')) el.hidden = !logged;
      for (const el of profileMenu.querySelectorAll('.menu-guest')) el.hidden = logged;
      for (const el of profileMenu.querySelectorAll('.menu-pro')) el.hidden = !pro;
      for (const el of profileMenu.querySelectorAll('.menu-free')) el.hidden = !logged || pro || admin;
      const panel = $('menu-admin');
      if (panel) panel.hidden = !admin;
      const verificar = $('menu-verificar');
      if (verificar) verificar.hidden = !logged || sesion.cuenta?.email_verificado !== false;
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

    $('menu-profile').addEventListener('click', () => { window.abrirPerfil?.(); });
    $('menu-audios').addEventListener('click', () => { misAudios(); });
    $('menu-cancel').addEventListener('click', () => { cancelarPro(); });
    $('menu-logout').addEventListener('click', () => { cerrarSesion(); });
    $('menu-verificar')?.addEventListener('click', async () => {
      try {
        const res = await api('/auth/verificar/reenviar', { method: 'POST' });
        avisar('Revisa tu correo', res?.mensaje || 'Te enviamos un enlace para confirmar tu correo.');
      } catch (err) { avisar('No se pudo enviar', err.message); }
    });
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
    apiCuenta: api,
    crearDialogoCuenta: crearDialogo,
    onSesion: (fn) => { listeners.add(fn); fn(); },
    setSesion,
    pedirCuenta,
    iniciarSesion,
    registrarse,
    confirmarRegistro,
    reenviarCodigo,
    recuperarPassword,
    restablecerPassword,
    proveedoresSociales,
    refrescarCuenta,
    contratarPro,
    cancelarPro,
  });

  // Enlace del correo: "/#verificar=CODIGO" confirma el correo o guarda el correo nuevo.
  // Tambien con la pagina ya abierta (hashchange): el enlace puede abrirse en la misma pestaña.
  function revisarVerificacion() {
    const verificar = /^#verificar=(.+)$/.exec(location.hash);
    if (!verificar) return;
    history.replaceState(null, '', location.pathname + location.search);
    api('/auth/verificar', { method: 'POST', body: { codigo: verificar[1] } })
      .then((res) => { avisar('Correo confirmado', res?.mensaje || 'Listo: tu correo quedó confirmado.'); refrescarCuenta(); })
      .catch((err) => avisar('No se pudo confirmar', err.message));
  }
  revisarVerificacion();
  addEventListener('hashchange', revisarVerificacion);

  function revisarRegresoSocial() {
    const conectado = /^#conectado=(google|facebook)$/.exec(location.hash);
    if (conectado) {
      history.replaceState(null, '', location.pathname + location.search);
      refrescarCuenta();
      const red = conectado[1] === 'google' ? 'Google' : 'Facebook';
      avisar(`${red} conectado`, `Desde ahora también puedes entrar con tu cuenta de ${red}.`);
    }
  }
  revisarRegresoSocial();
  addEventListener('hashchange', revisarRegresoSocial);

  // Regreso de Google/Facebook: el servidor pone la cookie y vuelve a "/#sesion=ID" o "/#error=MENSAJE".
  const regreso = /^#(sesion|error)=(.+)$/.exec(location.hash);
  if (regreso) {
    history.replaceState(null, '', location.pathname + location.search);
    const [, tipo, valor] = regreso;
    if (tipo === 'sesion') {
      const token = valor;
      api('/suscripcion', { token })
        .then((cuenta) => setSesion(desdeCuenta(token, cuenta)))
        .catch(() => avisar('No se pudo entrar', 'Intenta iniciar sesión de nuevo.'));
    } else {
      let texto = valor;
      try { texto = decodeURIComponent(valor); } catch { /* se muestra tal cual */ }
      avisar('No se pudo entrar', texto);
    }
  }

  listeners.forEach((fn) => fn());
  refrescarCuenta();   // el plan pudo cambiar (vencer, cancelarse) desde la ultima visita
})();
