// planes.html: configuracion de planes, selector Mensual/Anual, tarjetas y fondo animado ligero.
(() => {
  'use strict';

  // =====================================================================================
  // CONFIGURACION DE PLANES — editar SOLO aqui para cambiar precios o limites.
  // Hoy estos valores salen de seed.py del backend; en el futuro vendran de la API.
  //   trabajosAlMes / minutosPorAudio: numeros. calidad: clave de CALIDAD_TEXTO.
  //   precio.mensual = lo que se paga cada mes. precio.anual = lo que se paga una vez al anio. 0 = gratis.
  //   Para cambiar un precio basta editar el numero de su linea; los "meses gratis" se calculan solos.
  //
  // TODO (backend): el precio anual todavia NO existe en seed.py (solo hay precio mensual). El valor de
  // `anual` es la propuesta de producto (2 meses gratis) y hay que agregarlo al backend.
  // =====================================================================================
  const PLANES = {
    gratis: { nombre: 'Gratis', precio: { mensual: 0, anual: 0 }, moneda: 'MXN', trabajosAlMes: 5, minutosPorAudio: 5, calidad: 'rapida' },
    pro: { nombre: 'Pro', precio: { mensual: 99, anual: 990 }, moneda: 'MXN', trabajosAlMes: 100, minutosPorAudio: 20, calidad: 'mejor' },
  };
  const CALIDAD_TEXTO = { rapida: 'Separación en calidad rápida', mejor: 'Mejor calidad de separación' };
  const PLAN_DESTACADO = 'pro';

  const $ = (id) => document.getElementById(id);
  const plansGrid = $('plans-grid');
  const billing = document.querySelector('.billing');

  // ---------- Tarjetas ----------
  let facturacion = 'mensual';   // 'mensual' | 'anual'
  const UNIDAD = { mensual: 'mes', anual: 'año' };
  const mesesGratis = (plan) => Math.round(12 - plan.precio.anual / plan.precio.mensual);
  const nota = (plan) => (facturacion === 'anual' && plan.precio.mensual > 0 && mesesGratis(plan) > 0
    ? `Equivale a ${mesesGratis(plan)} meses gratis` : '');
  const caracteristicas = (plan) => [
    `${plan.trabajosAlMes} trabajos al mes`,
    `Hasta ${plan.minutosPorAudio} minutos por audio`,
    CALIDAD_TEXTO[plan.calidad],
  ];

  function pintarPrecio(card, plan) {
    const price = card.querySelector('.plan-price');
    price.firstChild.textContent = `$${plan.precio[facturacion]}`;
    price.querySelector('span').textContent = plan.precio.mensual > 0 ? ` ${plan.moneda} / ${UNIDAD[facturacion]}` : '';
    card.querySelector('.plan-note').textContent = nota(plan);
  }

  // Se vuelve a pintar cuando cambia la sesion (account.js llama a esta funcion al cargar y en cada cambio).
  function renderPlans() {
    const sesion = window.getSesion();
    const plan_actual = sesion ? sesion.plan : null;
    plansGrid.replaceChildren();
    for (const [id, plan] of Object.entries(PLANES)) {
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
      name.textContent = plan.nombre;
      const price = document.createElement('p');
      price.className = 'plan-price';
      price.append(document.createTextNode(''), document.createElement('span'));
      const note = document.createElement('p');
      note.className = 'plan-note';
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
      const isCurrent = id === 'gratis' ? plan_actual !== 'pro' : plan_actual === 'pro';
      if (isCurrent) {
        button.textContent = 'Tu plan actual';
        button.disabled = true;
      } else if (id === 'pro') {
        button.textContent = 'Contratar Pro';
        button.addEventListener('click', () => {
          // Muro de cuenta: sin sesion NO se ejecuta la accion.
          if (!window.getSesion()) { window.pedirCuenta('Para contratar Pro necesitas una cuenta. Crea una o inicia sesión y vuelve aquí.'); return; }
          window.contratarPro();   // TODO: formulario de pago (marca + ultimos 4); POST /suscripcion/pro
        });
      } else {
        button.textContent = 'Plan gratis';
        button.disabled = true;
      }
      card.append(name, price, note, list, button);
      pintarPrecio(card, plan);
      plansGrid.append(card);
    }
  }

  // ---------- Selector Mensual / Anual ----------
  // Cambia solo los textos del precio (la altura no se mueve: la nota siempre ocupa su linea) y desliza
  // el indicador con transform.
  function setFacturacion(next, focus = false) {
    facturacion = next;
    billing.dataset.billing = next;
    for (const option of billing.querySelectorAll('.billing-option')) {
      const on = option.dataset.billing === next;
      option.setAttribute('aria-checked', String(on));
      option.tabIndex = on ? 0 : -1;
      if (on && focus) option.focus();
    }
    for (const card of plansGrid.children) pintarPrecio(card, PLANES[card.dataset.plan]);
  }
  billing.addEventListener('click', (event) => {
    const option = event.target.closest('.billing-option');
    if (option) setFacturacion(option.dataset.billing);
  });
  billing.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    setFacturacion(facturacion === 'mensual' ? 'anual' : 'mensual', true);
  });
  const ahorro = mesesGratis(PLANES[PLAN_DESTACADO]);
  $('billing-save').textContent = ahorro > 0 ? `${ahorro} meses gratis` : '';

  window.onSesion(() => { renderPlans(); setFacturacion(facturacion); });

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
