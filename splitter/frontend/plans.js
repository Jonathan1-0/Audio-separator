// planes.html: tarjetas de los planes (salen de la base: GET /suscripcion/planes) y fondo animado ligero.
(() => {
  'use strict';

  // Los precios y limites viven SOLO en la base (seed.py los crea). Aqui solo van los textos.
  const NOMBRE = { gratis: 'Gratis', pro: 'Pro' };
  const PLAN_DESTACADO = 'pro';

  const $ = (id) => document.getElementById(id);
  const plansGrid = $('plans-grid');
  const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
  const fecha = (iso) => (iso ? new Date(iso).toLocaleDateString('es-MX', { day: 'numeric', month: 'long', year: 'numeric' }) : '');

  let planes = null;       // [{ nombre, precio_mensual, trabajos_por_mes, minutos_max_audio, mejor_calidad, minutos_guardado, historial }]
  let diasPeriodo = 30;

  function guardado(minutos) {
    if (minutos >= 1440) return plural(Math.round(minutos / 1440), 'día', 'días');
    if (minutos >= 60) return plural(Math.round(minutos / 60), 'hora', 'horas');
    return plural(minutos, 'minuto', 'minutos');
  }

  const caracteristicas = (plan) => [
    `${plan.trabajos_por_mes} trabajos cada ${diasPeriodo} días`,
    `Hasta ${plan.minutos_max_audio} minutos por audio`,
    plan.mejor_calidad ? 'Mejor calidad de separación' : 'Separación en calidad rápida',
    plan.historial ? `Tus audios se guardan ${guardado(plan.minutos_guardado)} en «Mis audios»` : `Tus audios se guardan ${guardado(plan.minutos_guardado)}`,
  ];

  function mensaje(texto) {
    const p = document.createElement('p');
    p.className = 'plans-lead';
    p.textContent = texto;
    plansGrid.replaceChildren(p);
  }

  // Se vuelve a pintar cuando cambia la sesion (account.js avisa al cargar y en cada cambio).
  function renderPlans() {
    if (!planes) return;
    const sesion = window.getSesion();
    const planActual = sesion ? sesion.plan : null;
    plansGrid.replaceChildren();
    for (const plan of planes) {
      const id = plan.nombre;
      const precio = Number(plan.precio_mensual);
      const card = document.createElement('article');
      card.className = 'plan-card';
      card.dataset.plan = id;
      if (id === PLAN_DESTACADO) {
        card.classList.add('is-featured');
        const badge = document.createElement('span');
        badge.className = 'plan-badge';
        badge.textContent = 'Recomendado';
        card.append(badge);
      }
      const name = document.createElement('h3');
      name.className = 'plan-name';
      name.textContent = NOMBRE[id] || id;
      const price = document.createElement('p');
      price.className = 'plan-price';
      price.append(document.createTextNode(`$${precio}`));
      if (precio > 0) {
        const unidad = document.createElement('span');
        unidad.textContent = ` MXN / ${diasPeriodo} días`;
        price.append(unidad);
      }
      const note = document.createElement('p');
      note.className = 'plan-note';
      note.textContent = id === 'pro' && planActual === 'pro' && sesion.cuenta?.fin_periodo
        ? `Activo hasta el ${fecha(sesion.cuenta.fin_periodo)}`
        : precio > 0 ? 'Pago único por periodo, sin renovación automática' : '';
      const list = document.createElement('ul');
      list.className = 'plan-features';
      for (const text of caracteristicas(plan)) {
        const item = document.createElement('li');
        item.textContent = text;
        list.append(item);
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.className = id === PLAN_DESTACADO ? 'primary-button plan-button' : 'secondary-button plan-button';
      // Sin sesion se cuenta como plan gratis (el invitado tiene los mismos limites).
      const isCurrent = id === 'gratis' ? planActual !== 'pro' : planActual === id;
      if (isCurrent) {
        button.textContent = 'Tu plan actual';
        button.disabled = true;
      } else if (id === 'pro') {
        button.textContent = 'Contratar Pro';
        button.addEventListener('click', () => window.contratarPro());   // sin sesion, account.js muestra el muro
      } else {
        button.textContent = 'Volver a Gratis';
        button.addEventListener('click', () => window.cancelarPro());
      }
      card.append(name, price, note, list, button);
      plansGrid.append(card);
    }
  }

  async function cargarPlanes() {
    mensaje('Cargando planes…');
    try {
      const res = await fetch('/suscripcion/planes');
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      planes = data.planes;
      diasPeriodo = data.dias_periodo;
    } catch {
      mensaje('No se pudieron cargar los planes. Recarga la página.');
      return;
    }
    renderPlans();
  }

  window.onSesion(renderPlans);
  cargarPlanes();

  // =====================================================================================
  // FONDO ANIMADO (ligero)
  // El efecto de referencia (21st.dev "jelly-animated-hero") es un VIDEO pregrabado, no un shader. Para
  // que no trabe, el video NO se muestra directamente (con blur/blend CSS a pantalla completa): se dibuja
  // en un canvas diminuto y se escala por CSS.
  //   - Resolucion reducida: 320x180 (nunca devicePixelRatio completo); baja a 160x90 si va justo.
  //   - Maximo 30 fps, con control de tiempo sobre requestAnimationFrame.
  //   - Pausa con la pestana oculta (document.hidden) y con el canvas fuera de pantalla.
  //   - Degradacion automatica: se mide el tiempo entre cuadros; si no llega, baja resolucion y, si aun
  //     asi no llega, cae al fondo estatico y deja de decodificar el video.
  //   - Estatico directo en movil, con prefers-reduced-motion, ahorro de datos, poca memoria o sin canvas.
  // El tinte gris --smoke-silver (el del humo del hero) se aplica dentro del canvas (mezcla "color"): el video violeta queda gris.
  // TODO: el video se pide a su URL original; si se quiere depender de uno mismo, alojar una copia propia.
  // =====================================================================================
  const FONDO_VIDEO = 'https://ease-one.vercel.app/bg/something.mp4';
  const MAX_FPS = 30, INTERVALO = 1000 / MAX_FPS;
  const NIVELES = [[320, 180], [160, 90]];
  const UMBRAL_MS = 50;      // promedio entre cuadros por encima de esto (< 20 fps) = no llega
  const VENTANA = 45;        // cuadros por medicion

  const section = $('planes');
  const bg = section.querySelector('.plans-bg');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const movil = matchMedia('(max-width: 640px)');
  const modesto = () => movil.matches || reduced.matches || navigator.connection?.saveData || (navigator.deviceMemory && navigator.deviceMemory <= 2);

  let canvas = null, ctx = null, video = null;
  let nivel = 0, raf = 0, ultimo = 0, visible = false, estatico = false;
  let muestras = [], tinte = 'rgb(137,150,154)';

  function estaticoYa(motivo) {
    estatico = true;
    cancelAnimationFrame(raf); raf = 0;
    if (video) { video.pause(); video.removeAttribute('src'); video.load(); video.remove(); video = null; }
    canvas?.remove(); canvas = ctx = null;
    bg.classList.remove('is-ready');
    bg.dataset.estado = 'estatico';
    bg.dataset.motivo = motivo;
  }

  function ajustarCanvas() {
    [canvas.width, canvas.height] = NIVELES[nivel];
  }

  function montar() {
    if (canvas || estatico) return;
    if (modesto()) { estaticoYa(movil.matches ? 'movil' : 'ahorro'); return; }
    canvas = document.createElement('canvas');
    ctx = canvas.getContext('2d', { alpha: false });
    if (!ctx) { estaticoYa('sin-canvas'); return; }
    const plata = getComputedStyle(document.documentElement).getPropertyValue('--smoke-silver').trim();   // mismo gris del humo del hero
    if (plata) tinte = `rgb(${plata.split(/\s+/).join(',')})`;
    ajustarCanvas();
    bg.prepend(canvas);
    video = document.createElement('video');
    video.muted = true; video.loop = true; video.playsInline = true; video.preload = 'auto';
    video.setAttribute('aria-hidden', 'true');
    video.style.cssText = 'position:absolute;width:1px;height:1px;opacity:0;pointer-events:none';
    video.addEventListener('error', () => estaticoYa('video'));
    video.addEventListener('loadeddata', () => { bg.classList.add('is-ready'); bg.dataset.estado = 'animado'; sincronizar(); }, { once: true });
    video.src = FONDO_VIDEO;
    bg.append(video);
  }

  function pintar(ahora) {
    raf = requestAnimationFrame(pintar);
    const dt = ahora - ultimo;
    if (dt < INTERVALO - 2) return;          // tope de 30 fps: no se dibuja entre medias
    ultimo = ahora;
    if (!video || video.readyState < 2) return;
    const [w, h] = NIVELES[nivel];
    ctx.drawImage(video, 0, 0, w, h);
    ctx.globalCompositeOperation = 'color';  // tinte gris del humo: el video (violeta) queda gris
    ctx.fillStyle = tinte;
    ctx.fillRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'source-over';
    // Degradacion: se mide el tiempo real entre cuadros dibujados.
    muestras.push(dt);
    if (muestras.length >= VENTANA) {
      const medio = muestras.slice(5).reduce((a, b) => a + b, 0) / (muestras.length - 5);   // sin el arranque
      bg.dataset.fps = String(Math.round(1000 / medio));
      muestras = [];
      if (medio > UMBRAL_MS) {
        if (nivel < NIVELES.length - 1) { nivel += 1; ajustarCanvas(); bg.dataset.nivel = String(nivel); }
        else estaticoYa('lento');
      }
    }
  }

  function sincronizar() {
    if (estatico || !video) return;
    const correr = visible && !document.hidden && video.readyState >= 2;
    if (correr && !raf) {
      muestras = []; ultimo = 0;
      video.play().catch(() => {});
      raf = requestAnimationFrame(pintar);
    } else if (!correr && raf) {
      cancelAnimationFrame(raf); raf = 0;
      video.pause();
    }
  }

  if ('IntersectionObserver' in window) {
    new IntersectionObserver((entries) => {
      visible = entries.some((e) => e.isIntersecting);
      if (visible) montar();
      sincronizar();
    }, { rootMargin: '200px 0px' }).observe(section);
  } else {
    estaticoYa('sin-observer');
  }
  document.addEventListener('visibilitychange', sincronizar);
  reduced.addEventListener('change', () => { if (reduced.matches) estaticoYa('reduced-motion'); });
})();
