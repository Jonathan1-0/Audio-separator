// Sesion compartida por index.html y planes.html: estado unico conectado al backend, barra superior
// (solo index), menu de perfil, muro de cuenta, pago (simulado) del plan Pro, cancelacion y "Mis audios".
(() => {
  'use strict';

  const NOMBRE_PLAN = { gratis: 'Gratis', pro: 'Pro', admin: 'Admin' };

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

  // ---------- Contratar Pro (pago simulado) ----------
  // Dos metodos: tarjeta (formulario completo) o PayPal (redireccion). El plan se renueva automaticamente.
  // POST /suscripcion/pro  body { marca, ultimos4, renovacion_automatica: true }.
  // El numero completo, el nombre, el vencimiento y el CVC solo existen en los campos del formulario para
  // validarlos en el navegador: nunca se envian, ni se guardan (ni en localStorage ni en variables). Al backend
  // solo llegan la marca y los ultimos 4 digitos.
  // POST /suscripcion/paypal  body { renovacion_automatica: true } -> { url } (la ruta aun no existe en el backend).
  // Es una simulacion: la validacion REAL de la tarjeta (largo, algoritmo, vencimiento, CVC) la hara el backend.
  // Aqui solo se pide que los campos no esten vacios y tengan forma de tarjeta, para no rechazar tarjetas de prueba.
  const MARCAS = {
    amex: { nombre: 'American Express', largo: 19, cvc: 4, grupos: [4, 6, 5] },
    visa: { nombre: 'Visa', largo: 19, cvc: 4, grupos: [4, 4, 4, 4, 3] },
    mastercard: { nombre: 'Mastercard', largo: 19, cvc: 4, grupos: [4, 4, 4, 4, 3] },
    otra: { nombre: 'Otra', largo: 19, cvc: 4, grupos: [4, 4, 4, 4, 3] },
  };
  function detectarMarca(digitos) {
    const dos = Number(digitos.slice(0, 2));
    const cuatro = Number(digitos.slice(0, 4));
    if (digitos[0] === '4') return 'visa';
    if (dos === 34 || dos === 37) return 'amex';
    if ((dos >= 51 && dos <= 55) || (digitos.length >= 4 && cuatro >= 2221 && cuatro <= 2720)) return 'mastercard';
    return 'otra';
  }
  const soloDigitos = (v) => v.replace(/\D/g, '');
  function agrupar(digitos, grupos) {
    const partes = [];
    let i = 0;
    for (const g of grupos) { if (i >= digitos.length) break; partes.push(digitos.slice(i, i + g)); i += g; }
    return partes.join(' ');
  }

  const campoPago = (id, etiqueta, atributos) => `<div class="pay-field">
            <label class="field" for="${id}"><span>${etiqueta}</span><input id="${id}" ${atributos} aria-describedby="${id}-error"></label>
            <p class="pay-error" id="${id}-error" hidden></p></div>`;

  let pago = null;
  function contratarPro() {
    if (!sesion) { pedirCuenta('Para contratar Pro necesitas una cuenta. Crea una o inicia sesión y vuelve aquí.'); return; }
    if (sesion.plan === 'pro' || sesion.plan === 'admin') return;
    if (!pago) {
      pago = crearDialogo('wall-form');
      pago.setAttribute('aria-labelledby', 'pago-title');
      pago.innerHTML = `<form method="dialog" class="login-fields" novalidate>
          <h2 id="pago-title">Contratar Pro</h2>
          <p id="pago-text"></p>
          <div class="pay-methods" role="radiogroup" aria-label="Método de pago">
            <button type="button" role="radio" aria-checked="true" data-metodo="tarjeta">Tarjeta</button>
            <button type="button" role="radio" aria-checked="false" tabindex="-1" data-metodo="paypal">PayPal</button>
          </div>
          <div id="pago-tarjeta" class="login-fields">
            <div class="pay-field">
              <label class="field" for="pago-numero"><span class="pay-label-row">Número de tarjeta <em id="pago-marca" class="pay-brand"></em></span>
                <input id="pago-numero" type="text" inputmode="numeric" autocomplete="cc-number" placeholder="0000 0000 0000 0000" aria-describedby="pago-numero-error"></label>
              <p class="pay-error" id="pago-numero-error" hidden></p></div>
            ${campoPago('pago-nombre', 'Nombre del titular', 'type="text" autocomplete="cc-name" placeholder="Como aparece en la tarjeta"')}
            <div class="pay-row">
              ${campoPago('pago-vence', 'Vencimiento', 'type="text" inputmode="numeric" autocomplete="cc-exp" placeholder="MM/AA" maxlength="5"')}
              ${campoPago('pago-cvc', 'CVC', 'type="text" inputmode="numeric" autocomplete="cc-csc" placeholder="123" maxlength="4"')}
            </div>
          </div>
          <div id="pago-paypal" class="login-fields" hidden>
            <p class="wall-note">Te llevaremos a PayPal para confirmar el pago.</p>
          </div>
          <p id="pago-error" class="login-message" role="alert" hidden></p>
          <div class="wall-actions">
            <button id="pago-submit" type="submit" class="primary-button">Pagar</button>
            <button type="button" class="wall-close" data-cerrar>Ahora no</button>
          </div>
          <p id="pago-nota" class="wall-note">Pago de prueba: no se cobra nada. Solo se envían la marca y los últimos 4 dígitos.</p>
        </form>`;
      const form = pago.querySelector('form');
      const error = pago.querySelector('#pago-error');
      const boton = pago.querySelector('#pago-submit');
      const numero = $('pago-numero'), nombre = $('pago-nombre'), vence = $('pago-vence'), cvc = $('pago-cvc');
      const campos = [numero, nombre, vence, cvc];
      let metodo = 'tarjeta';
      let intentado = false;

      const mostrarError = (campo, texto) => {
        const el = $(`${campo.id}-error`);
        el.textContent = texto;
        el.hidden = !texto;
        campo.setAttribute('aria-invalid', texto ? 'true' : 'false');
        return texto;
      };
      const marcaActual = () => MARCAS[detectarMarca(soloDigitos(numero.value))];

      const validadores = new Map([
        [numero, () => {
          const d = soloDigitos(numero.value);
          const m = marcaActual();
          if (!d) return 'Escribe el número de tu tarjeta.';
          return d.length >= 8 ? '' : 'Escribe el número completo de tu tarjeta.';   // el backend valida el resto
        }],
        [nombre, () => (nombre.value.trim().length >= 1 ? '' : 'Escribe el nombre como aparece en la tarjeta.')],
        [vence, () => {
          const m = /^(\d{2})\/(\d{2})$/.exec(vence.value);
          if (!m) return 'Escribe el vencimiento como MM/AA.';
          const mes = Number(m[1]);
          return mes >= 1 && mes <= 12 ? '' : 'El mes debe estar entre 01 y 12.';   // el backend revisa si esta vencida
        }],
        [cvc, () => {
          const n = soloDigitos(cvc.value).length;
          return n >= 3 && n <= 4 ? '' : 'El CVC tiene 3 o 4 dígitos.';
        }],
      ]);
      const validar = (campo) => mostrarError(campo, validadores.get(campo)());

      numero.addEventListener('input', () => {
        const m = marcaActual();
        numero.value = agrupar(soloDigitos(numero.value).slice(0, m.largo), m.grupos);
        $('pago-marca').textContent = soloDigitos(numero.value) ? m.nombre : '';
        cvc.maxLength = m.cvc;
        if (soloDigitos(cvc.value).length > m.cvc) cvc.value = soloDigitos(cvc.value).slice(0, m.cvc);
      });
      vence.addEventListener('input', (event) => {
        let d = soloDigitos(vence.value).slice(0, 4);
        if (d.length && Number(d[0]) > 1) d = `0${d}`.slice(0, 4);   // "3" -> "03"
        const borrando = event.inputType?.startsWith('delete');
        vence.value = d.length > 2 || (d.length === 2 && !borrando) ? `${d.slice(0, 2)}/${d.slice(2)}` : d;
      });
      cvc.addEventListener('input', () => { cvc.value = soloDigitos(cvc.value).slice(0, marcaActual().cvc); });
      for (const campo of campos) {
        campo.addEventListener('blur', () => { if (intentado) validar(campo); });
        campo.addEventListener('input', () => { if (intentado) validar(campo); });
      }

      // Selector Tarjeta / PayPal (radiogroup con flechas).
      const opciones = [...pago.querySelectorAll('[data-metodo]')];
      function elegirMetodo(nuevo, { enfocar = false } = {}) {
        metodo = nuevo;
        for (const op of opciones) {
          const activa = op.dataset.metodo === nuevo;
          op.setAttribute('aria-checked', String(activa));
          op.tabIndex = activa ? 0 : -1;
          if (activa && enfocar) op.focus();
        }
        $('pago-tarjeta').hidden = nuevo !== 'tarjeta';
        $('pago-paypal').hidden = nuevo !== 'paypal';
        $('pago-nota').hidden = nuevo !== 'tarjeta';
        boton.textContent = nuevo === 'tarjeta' ? 'Pagar' : 'Continuar con PayPal';
        error.hidden = true;
      }
      for (const op of opciones) {
        op.addEventListener('click', () => elegirMetodo(op.dataset.metodo));
        op.addEventListener('keydown', (event) => {
          if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
          event.preventDefault();
          elegirMetodo(metodo === 'tarjeta' ? 'paypal' : 'tarjeta', { enfocar: true });
        });
      }

      pago.reiniciar = () => {
        form.reset();
        intentado = false;
        for (const campo of campos) mostrarError(campo, '');
        $('pago-marca').textContent = '';
        cvc.maxLength = 4;
        elegirMetodo('tarjeta');
      };

      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        error.hidden = true;
        let ruta, body;
        if (metodo === 'tarjeta') {
          intentado = true;
          const invalido = campos.filter((campo) => validar(campo));
          if (invalido.length) { invalido[0].focus(); return; }
          ruta = '/suscripcion/pro';
          body = { marca: marcaActual().nombre, ultimos4: soloDigitos(numero.value).slice(-4), renovacion_automatica: true };
        } else {
          ruta = '/suscripcion/paypal';
          body = { renovacion_automatica: true };
        }
        boton.disabled = true;
        try {
          const r = await api(ruta, { method: 'POST', body });
          if (metodo === 'paypal') {
            if (typeof r?.url === 'string' && r.url) { location.href = r.url; return; }
            throw new Error('No se pudo iniciar el pago con PayPal. Intenta de nuevo.');
          }
          form.reset();   // los datos de la tarjeta no se conservan
          await refrescarCuenta();
          pago.close();
          avisarProActivo(r?.fin_periodo);
        } catch (err) {
          error.textContent = [404, 405, 501].includes(err.status) && metodo === 'paypal'
            ? 'Pagar con PayPal todavía no está disponible. Por ahora usa tarjeta.'
            : err.message;
          error.hidden = false;
          if (err.status === 409) {
            refrescarCuenta();
            avisar('No se pudo contratar', err.message);
          }
        } finally {
          boton.disabled = false;
        }
      });
    }
    const pro = sesion.cuenta?.pro;
    const precio = pro ? Number(pro.precio_mensual) : 99;
    const dias = pro ? pro.dias_periodo : 30;
    $('pago-text').textContent = `$${precio} MXN cada ${dias} días. Se renueva automáticamente; cancela cuando quieras.`;
    pago.reiniciar();
    pago.showModal();
    $('pago-numero').focus();
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

  // POST /suscripcion/cancelar: pasa al plan gratis desde ahora (el pago simulado no se devuelve).
  async function cancelarPro() {
    if (sesion?.plan !== 'pro') return;
    const guardado = await guardadoGratis();
    const frase = guardado ? `tus próximos audios se guardan ${guardado}` : 'tus próximos audios se guardan por menos tiempo';
    avisar('¿Cancelar el plan Pro?',
      `Al cancelar, ya no se renovará y pasas al plan Gratis desde ahora: dejas de tener tus audios guardados una semana, ${frase} y vuelves a los límites gratis. Los trabajos que ya usaste en este periodo siguen contando. No se devuelve lo que pagaste.`,
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
      if (err.status === 403) {
        // El servidor aun no lista el historial de este plan (hoy solo Pro/admin): se dice claro, sin simular nada.
        lista.replaceChildren(Object.assign(document.createElement('li'), { className: 'history-empty',
          textContent: sesion.plan === 'gratis'
            ? `Mis audios todavía no está disponible en el plan Gratis. Tu audio sigue en la pantalla de resultados durante ${guardado}.`
            : err.message }));
        refrescarCuenta();
        return;
      }
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
          : `Plan ${NOMBRE_PLAN[sesion.plan]}`;
        // Plan de pago: estado segun el fin del periodo. Plan gratis: cuanto le queda del periodo.
        const estado = $('menu-state');
        const uso = $('menu-usage');
        const vigente = c?.fin_periodo ? new Date(c.fin_periodo) > new Date() : null;
        estado.hidden = admin || !(pro && vigente !== null);
        estado.dataset.activo = String(vigente === true);
        estado.textContent = vigente ? 'Activo' : 'Vencido';
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
    recuperarPassword,
    restablecerPassword,
    proveedoresSociales,
    refrescarCuenta,
    contratarPro,
    cancelarPro,
  });

  // Regreso de PayPal: el servidor vuelve a "/#pago=paypal-ok" o "/#pago=paypal-cancelado".
  if (location.hash === '#pago=paypal-ok' || location.hash === '#pago=paypal-cancelado') {
    const ok = location.hash === '#pago=paypal-ok';
    history.replaceState(null, '', location.pathname + location.search);
    if (ok) {
      refrescarCuenta().then(() => {
        if (sesion?.plan === 'pro' || sesion?.plan === 'admin') avisarProActivo(sesion?.cuenta?.fin_periodo);
        else avisar('Confirmando tu pago', 'Todavía no vemos el cambio a Pro. Si se hizo el cargo, tu plan se actualizará en unos minutos.');
      });
    }
    else avisar('Pago cancelado', 'No se hizo ningún cargo. Puedes intentarlo de nuevo cuando quieras.');
  }

  // Regreso de Google/Facebook: el servidor vuelve a "/#sesion=TOKEN" o "/#error=MENSAJE".
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
