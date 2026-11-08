// Vidrio (liquidGL) en las opciones elegibles.
//  A) Tarjetas de modo y conmutador de calidad: UNA lente por grupo que viaja a la opcion
//     seleccionada, o a la que tiene el cursor encima, y regresa al salir.
//  B) Pastillas de descarga (seleccion multiple): una lente por pastilla, montadas desde load;
//     nunca se crean ni se destruyen, solo se muestran y cambia su tinte.
// Los <input> siguen siendo la fuente de verdad; aqui solo se refleja cual esta marcado.
(() => {
  'use strict';
  const form = document.getElementById('splitter-form');
  const root = document.documentElement;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  if (!form) return;

  const EASE = 'cubic-bezier(0.22, 1, 0.36, 1)';
  const TRAVEL_MS = 460;
  const STRETCH_SQUASH = 0.94;   // el eje transversal se afina mientras la lente se alarga
  const STRETCH_PEAK = 0.38;     // punto del viaje en que la lente esta mas alargada
  const TINT_FULL = 'rgba(234, 234, 236, 0.24)';
  const TINT_HALF = 'rgba(234, 234, 236, 0.12)';
  // Con snapshot '.studio-flow' (o '.workspace') la lente muestrea mal y sale emborronada; con 'body' sale limpia.
  // Para no exceder la textura de la GPU en una pagina larga, la resolucion se limita a 4096px de lado.
  const page = Math.max(document.documentElement.scrollHeight, document.documentElement.scrollWidth, 1);
  // La captura se hace a la densidad real de la pantalla (1 en pantallas normales, hasta 2): mas no se ve y cuesta el doble.
  // Tope 1: la textura es un velo de refraccion (0.016), no hace falta mas densidad. En pantallas de 1.25-2x
  // la textura pesaba 1.5-4 veces mas (memoria, captura y muestreo) sin que se notara.
  const RESOLUTION = Math.min(1, 4096 / page);
  const OPTIONS = {
    snapshot: 'body',
    resolution: RESOLUTION,
    zIndex: 1,
    refraction: 0.016,
    aberration: 0,
    bevelDepth: 0.014,
    bevelWidth: 0.071,
    frost: 0,
    shadow: false,
    specular: true,
    reveal: 'none',
    tilt: false,
    draggable: false,
    interaction: 'fluid',
    interactionStrength: 0.5,
    interactionRadius: 3,
    interactionViscosity: 0.25,
    magnify: 1.05,
    tint: TINT_FULL,
  };
  // Elementos pequenos: mas refraccion y bisel para que el vidrio se note con poco fondo detras.
  const SMALL = { ...OPTIONS, refraction: 0.03, bevelDepth: 0.03, bevelWidth: 0.12, magnify: 1.08 };
  // ---- Ritmo de dibujo ----
  // liquidGL repinta cada frame mientras haya una lente visible, solo por el brillo especular, que se
  // mueve muy despacio. En reposo se dibuja a IDLE_FPS; con actividad (cursor, scroll, teclado, viaje de
  // la lente, cambios) vuelve a toda velocidad. La calidad por frame no cambia.
  const IDLE_FPS = 10;
  const ACTIVE_MS = 700;
  let activeUntil = 0;
  const poke = (ms = ACTIVE_MS) => { activeUntil = Math.max(activeUntil, performance.now() + ms); };
  for (const type of ['pointerdown', 'wheel', 'touchmove', 'keydown', 'scroll', 'resize']) {
    window.addEventListener(type, () => poke(), { passive: true, capture: true });
  }
  // El cursor solo mueve el vidrio cuando esta sobre una opcion: en el resto de la pagina no hace falta repintar a pleno ritmo.
  const GLASS_AREA = '.mode-grid, #quality-options, #track-options';
  window.addEventListener('pointermove', (event) => {
    if (event.target instanceof Element && event.target.closest(GLASS_AREA)) poke();
  }, { passive: true, capture: true });
  function throttleIdleRendering() {
    const renderer = window.__liquidGLRenderer__;
    if (!renderer || renderer.__throttled) return;
    renderer.__throttled = true;
    const draw = renderer.render;
    let lastDraw = 0;
    renderer.render = function throttledRender() {
      const now = performance.now();
      if (now > activeUntil && now - lastDraw < 1000 / IDLE_FPS) return undefined;
      lastDraw = now;
      return draw.call(this);
    };
  }
  const isChecked = (option) => Boolean(option.querySelector('input')?.checked);
  const isMouse = (event) => event.pointerType === 'mouse';
  const nextFrame = () => new Promise((resolve) => requestAnimationFrame(resolve));

  // ---- A) Una lente que viaja por grupo ----
  function createTravelingLens(container, optionSelector, lensEl, { follow = false } = {}) {
    let lens = null;
    let hovered = null;
    let shown = false;
    let animation = null;
    let tint = TINT_FULL;
    let boxW = 0;
    let boxH = 0;
    const options = () => [...container.querySelectorAll(optionSelector)];

    function setTint(value) {
      if (value === tint) return;
      tint = value;
      lens?.setTint?.(value);
    }

    // ---- Seguimiento del cursor (solo con follow): la lente acompana al raton frame a frame dentro del
    // contenedor, con un suavizado corto, y al salir regresa a la opcion elegida con el viaje de siempre.
    const FOLLOW_TAU_MS = 55;
    let cursor = null;   // posicion del cursor en coordenadas del contenedor
    let pos = null;      // posicion actual de la lente
    let raf = 0;
    let last = 0;
    const clamp = (value, max) => Math.min(Math.max(value, 0), Math.max(max, 0));
    // Geometria de las opciones medida UNA vez (no en cada frame): leer offsetLeft/offsetWidth de todas las
    // opciones 60 veces por segundo fuerza un layout tras cada escritura de transform. Se invalida al cambiar el tamano.
    let geo = null;
    function measure() {
      const all = options();
      const first = all[0];
      if (!first) return null;
      const w = first.offsetWidth;
      const h = first.offsetHeight;
      const rects = all.map((el) => ({ el, l: el.offsetLeft, t: el.offsetTop, r: el.offsetLeft + el.offsetWidth, b: el.offsetTop + el.offsetHeight }));
      // La lente no sale del area que ocupan las opciones (el contenedor puede tener relleno).
      return {
        w,
        h,
        rects,
        minX: Math.min(...rects.map((o) => o.l)),
        minY: Math.min(...rects.map((o) => o.t)),
        maxX: Math.max(...rects.map((o) => o.r)) - w,
        maxY: Math.max(...rects.map((o) => o.b)) - h,
      };
    }
    function followTick(now) {
      raf = 0;
      if (!cursor) return;
      geo ||= measure();
      if (!geo) return;
      const { w, h, minX, minY, maxX, maxY } = geo;
      const tx = Math.min(Math.max(cursor.x - w / 2, minX), Math.max(maxX, minX));
      const ty = Math.min(Math.max(cursor.y - h / 2, minY), Math.max(maxY, minY));
      const k = reduced.matches ? 1 : 1 - Math.exp(-Math.min(now - last, 64) / FOLLOW_TAU_MS);
      last = now;
      pos.x += (tx - pos.x) * k;
      pos.y += (ty - pos.y) * k;
      lensEl.style.transform = `translate(${pos.x}px, ${pos.y}px)`;
      const under = geo.rects.find((o) => cursor.x >= o.l && cursor.x <= o.r && cursor.y >= o.t && cursor.y <= o.b);
      setTint(under && isChecked(under.el) ? TINT_FULL : TINT_HALF);
      // Con el cursor quieto y la lente asentada se deja de animar; vuelve a arrancar al mover o al cambiar la seleccion.
      if (Math.abs(tx - pos.x) < 0.2 && Math.abs(ty - pos.y) < 0.2) return;
      poke(200);
      raf = requestAnimationFrame(followTick);
    }
    function followMove(event) {
      if (!isMouse(event)) return;
      const rect = container.getBoundingClientRect();
      cursor = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      if (raf) return;
      const first = options()[0];
      if (!first) return;
      clearTimeout(intent);
      hovered = null;
      if (!pos) {
        const from = shown ? new DOMMatrix(getComputedStyle(lensEl).transform) : null;
        animation?.cancel();
        pos = from ? { x: from.m41, y: from.m42 } : { x: cursor.x - first.offsetWidth / 2, y: cursor.y - first.offsetHeight / 2 };
        lensEl.style.width = `${first.offsetWidth}px`;
        lensEl.style.height = `${first.offsetHeight}px`;
        boxW = first.offsetWidth;
        boxH = first.offsetHeight;
        lensEl.hidden = false;
        shown = true;
      }
      last = performance.now();
      raf = requestAnimationFrame(followTick);
    }
    function followEnd() {
      cursor = null;
      pos = null;
      cancelAnimationFrame(raf);
      raf = 0;
      update();
    }

    function update() {
      geo = null;
      const selected = options().find(isChecked) || null;
      if (cursor) {   // siguiendo al cursor: followTick manda; solo se refresca el tinte
        if (!raf) { last = performance.now(); raf = requestAnimationFrame(followTick); }
        return;
      }
      const target = hovered && options().includes(hovered) ? hovered : selected;
      if (!target || container.getClientRects().length === 0) {
        animation?.cancel();
        lensEl.hidden = true;
        shown = false;
        return;
      }
      setTint(target === selected ? TINT_FULL : TINT_HALF);
      const x = target.offsetLeft;
      const y = target.offsetTop;
      const width = `${target.offsetWidth}px`;
      const height = `${target.offsetHeight}px`;
      if (lensEl.style.width !== width) lensEl.style.width = width;
      if (lensEl.style.height !== height) lensEl.style.height = height;
      const to = `translate(${x}px, ${y}px)`;
      if (!shown || reduced.matches) {
        animation?.cancel();
        lensEl.hidden = false;
        lensEl.style.transform = to;
        boxW = target.offsetWidth;
        boxH = target.offsetHeight;
        shown = true;
        return;
      }
      const from = new DOMMatrix(getComputedStyle(lensEl).transform);
      const w1 = target.offsetWidth;
      const h1 = target.offsetHeight;
      const w0 = from.a * boxW;
      const h0 = from.d * boxH;
      boxW = w1;
      boxH = h1;
      if (from.m41 === x && from.m42 === y && w0 === w1 && h0 === h1) return;
      animation?.cancel();
      poke(TRAVEL_MS + 200);
      lensEl.style.transform = to;
      // Estilo WhatsApp: la lente se estira hasta abarcar origen y destino y luego se recoge en el destino.
      const left = Math.min(from.m41, x);
      const top = Math.min(from.m42, y);
      const spanW = Math.max(from.m41 + w0, x + w1) - left;
      const spanH = Math.max(from.m42 + h0, y + h1) - top;
      const horizontal = Math.abs(x - from.m41) >= Math.abs(y - from.m42);
      const sx = horizontal ? spanW / w1 : (spanW / w1) * STRETCH_SQUASH;
      const sy = horizontal ? (spanH / h1) * STRETCH_SQUASH : spanH / h1;
      const ox = horizontal ? 0 : (spanW * (1 - STRETCH_SQUASH)) / 2;
      const oy = horizontal ? (spanH * (1 - STRETCH_SQUASH)) / 2 : 0;
      animation = lensEl.animate(
        [
          { transform: `translate(${from.m41}px, ${from.m42}px) scale(${w0 / w1}, ${h0 / h1})`, easing: 'cubic-bezier(0.45, 0, 0.55, 1)' },
          { transform: `translate(${left + ox}px, ${top + oy}px) scale(${sx}, ${sy})`, offset: STRETCH_PEAK, easing: EASE },
          { transform: to },
        ],
        { duration: TRAVEL_MS },
      );
    }

    // Intencion de hover: un roce o el hueco entre dos opciones no reinicia el viaje de la lente; solo cuenta
    // el cursor que se queda un instante. Evita arrancar y cancelar animaciones (y capturas de estado) en cadena.
    const HOVER_INTENT_MS = 55;
    let intent = 0;
    function hoverTo(option) {
      clearTimeout(intent);
      if (option === hovered) return;
      intent = setTimeout(() => { hovered = option; update(); }, HOVER_INTENT_MS);
    }
    if (follow) {
      container.addEventListener('pointermove', followMove, { passive: true });
      container.addEventListener('pointerleave', (event) => { if (isMouse(event)) followEnd(); });
    } else {
      container.addEventListener('pointerover', (event) => {
        if (!isMouse(event)) return;
        const option = event.target.closest(optionSelector);
        if (option) hoverTo(option);
      });
      container.addEventListener('pointerleave', () => hoverTo(null));
    }
    form.addEventListener('change', () => { poke(TRAVEL_MS + 400); requestAnimationFrame(update); });
    new ResizeObserver(update).observe(container);
    update();
    return { attach(instance) { lens = instance; lens.setTint?.(tint); }, update };
  }

  // ---- B) Una lente fija por pastilla ----
  function createChipLenses(chips) {
    let hovered = null;
    const lenses = new Map();
    function update() {
      for (const chip of chips) {
        const lensEl = chip.querySelector('.lente-pastilla');
        const selected = isChecked(chip);
        lensEl.hidden = !(selected || chip === hovered);
        lenses.get(lensEl)?.setTint?.(selected ? TINT_FULL : TINT_HALF);
      }
    }
    form.addEventListener('pointerover', (event) => {
      if (!isMouse(event)) return;
      const chip = event.target.closest('.track-chip');
      if (chip !== hovered) { hovered = chip; update(); }
    });
    form.addEventListener('pointerleave', () => { hovered = null; update(); });
    form.addEventListener('change', () => requestAnimationFrame(update));
    update();
    return { attach(instances) { for (const lens of instances) lenses.set(lens.el, lens); update(); } };
  }

  // ---- Captura: las secciones sin revelar cuentan como visibles mientras se captura ----
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  async function snapshotReady() {
    const started = performance.now();
    while (!window.__liquidGLRenderer__?.hasTexture && performance.now() - started < 5000) await sleep(50);
  }
  let recapturing = null;   // promesa de la captura en curso: quien llegue despues espera a la misma
  function recapture() {
    const renderer = window.__liquidGLRenderer__;
    if (!renderer?.captureSnapshot) return Promise.resolve();
    if (recapturing) return recapturing;
    recapturing = (async () => {
      root.classList.add('snap-ready');
      await nextFrame();
      try {
        await renderer.captureSnapshot.call(renderer, RAW);
      } finally {
        root.classList.remove('snap-ready');
        recapturing = null;
      }
    })();
    return recapturing;
  }
  // La libreria recaptura el body por su cuenta cada vez que cambia su tamano (y el gate de abajo lo hace
  // otra vez): dos capturas pesadas seguidas congelan la pagina. Todas las peticiones externas se funden
  // en una sola, que corre cuando el navegador esta libre y con las secciones sin revelar incluidas.
  const RAW = Symbol('raw');
  let recaptureTimer = 0;
  function scheduleRecapture(delay = 400) {
    clearTimeout(recaptureTimer);
    recaptureTimer = setTimeout(() => {
      if ('requestIdleCallback' in window) requestIdleCallback(recapture, { timeout: 2000 });
      else recapture();
    }, delay);
  }
  function coalesceSnapshots() {
    const renderer = window.__liquidGLRenderer__;
    if (!renderer?.captureSnapshot || renderer.__coalesced) return;
    renderer.__coalesced = true;
    const capture = renderer.captureSnapshot;
    renderer.captureSnapshot = function captureSnapshot(flag) {
      if (flag === RAW) return capture.call(this);
      scheduleRecapture();
      return Promise.resolve(true);
    };
  }

  const hasGpu = () => {
    if ('gpu' in navigator) return true;
    const probe = document.createElement('canvas');
    return Boolean(probe.getContext('webgl2') || probe.getContext('webgl'));
  };

  async function start() {
    if (typeof window.liquidGL !== 'function' || !hasGpu()) { root.classList.add('no-glass'); return; }

    const modeGrid = form.querySelector('.mode-grid');
    const qualityBox = document.getElementById('quality-options');
    const chips = [...form.querySelectorAll('.track-chip')];
    if (!modeGrid || !qualityBox || !chips.length) { root.classList.add('no-glass'); return; }

    const makeLens = (id, parent) => {
      const el = document.createElement('div');
      el.id = id;
      el.className = 'lente';
      el.hidden = true;
      el.setAttribute('aria-hidden', 'true');
      parent.append(el);
      return el;
    };
    const modes = createTravelingLens(modeGrid, '.mode-card', makeLens('lente-modos', modeGrid), { follow: true });
    const quality = createTravelingLens(qualityBox, '.quality-pill', makeLens('lente-calidad', qualityBox), { follow: true });
    for (const chip of chips) {
      const el = document.createElement('span');
      el.className = 'lente-pastilla';
      el.hidden = true;
      el.setAttribute('aria-hidden', 'true');
      chip.prepend(el);
    }
    const downloads = createChipLenses(chips);
    // Ninguna opcion entra en la captura: el vidrio no refracta los colores de sus vecinas.
    for (const option of form.querySelectorAll('.mode-card, .quality-pill, .track-chip')) option.setAttribute('data-liquid-ignore', '');

    root.classList.add('snap-ready');
    await nextFrame();
    const heightAtCapture = document.documentElement.scrollHeight;
    try {
      modes.attach(window.liquidGL({ ...OPTIONS, target: '#lente-modos' }));
      quality.attach(window.liquidGL({ ...SMALL, target: '#lente-calidad' }));
      const instances = window.liquidGL({ ...SMALL, target: '.lente-pastilla' });
      downloads.attach([].concat(instances));
      await snapshotReady();
    } catch (error) {
      root.classList.add('no-glass');
    } finally {
      root.classList.remove('snap-ready');
    }
    throttleIdleRendering();
    coalesceSnapshots();
    // Al cambiar de modo cambia la altura de la pagina (aparece o desaparece la calidad y las pistas) y la
    // textura capturada queda DESFASADA: las lentes de abajo muestrean otra zona (texto volteado y recortes).
    // Mientras dura ese desfase se ocultan las lentes que estan bajo el cambio (calidad y pastillas), se
    // recaptura en cuanto el layout se asienta (sin esperar al "idle") y entonces reaparecen.
    let capturedHeight = heightAtCapture;
    if (document.documentElement.scrollHeight !== capturedHeight) {   // la altura cambio durante la captura inicial
      capturedHeight = document.documentElement.scrollHeight;
      root.classList.add('glass-stale');
      recapture().finally(() => root.classList.remove('glass-stale'));
    }
    form.addEventListener('change', (event) => {
      if (event.target.name !== 'mode') return;
      root.classList.add('glass-stale');
      setTimeout(async () => {
        const height = document.documentElement.scrollHeight;
        try {
          if (height !== capturedHeight) {
            capturedHeight = height;
            clearTimeout(recaptureTimer);   // se anula la peticion diferida de la libreria: esta captura la sustituye
            await recapture();
          }
        } finally {
          root.classList.remove('glass-stale');
        }
      }, 600);
    });
  }

  // Arranque fuera del camino critico: tras load, con Satoshi ya cargada (si la fuente llega despues, la
  // pagina cambia de tamano y la libreria repetiria la captura entera) y cuando el navegador queda libre,
  // para no competir con la entrada del h1 ni con el primer pintado. Las lentes estan bajo el hero, asi
  // que no se ve el retraso; si el usuario baja antes, arranca en cuanto las opciones se acercan.
  let booted = false;
  function boot() {
    if (booted) return;
    booted = true;
    near?.disconnect();
    start();
  }
  const near = 'IntersectionObserver' in window
    ? new IntersectionObserver((entries) => { if (entries.some((entry) => entry.isIntersecting)) boot(); }, { rootMargin: '200px 0px' })
    : null;
  async function whenSettled() {
    if (document.readyState !== 'complete') await new Promise((resolve) => window.addEventListener('load', resolve, { once: true }));
    const grid = form.querySelector('.mode-grid');
    if (grid) near?.observe(grid);
    await Promise.race([document.fonts?.ready, sleep(3000)]);
    if ('requestIdleCallback' in window) requestIdleCallback(boot, { timeout: 1500 });
    else setTimeout(boot, 200);
  }
  whenSettled();
})();
