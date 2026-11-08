// Franja de barras al pie del hero: una sola fila monocroma que sube y baja en su sitio, en bucle.
// Sin requestAnimationFrame propio: corre en el bucle unico (smoke.js); no dibuja fuera de pantalla y continua donde iba al volver.
(() => {
  'use strict';
  const canvas = document.getElementById('wave-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  const PITCH = 9;                 // separacion entre barras (px)
  const BAR = PITCH * 0.61;        // misma proporcion barra/hueco que el simbolo del logo (11:7)
  const PERIOD = 4;                // segundos por oscilacion completa
  const AMPLITUDE = 0.3;           // variacion de altura alrededor de la altura base
  const LEVEL_MIN = 0.14;
  const LEVEL_MAX = 0.95;
  const ALPHA_MIN = 0.25;
  const ALPHA_MAX = 0.7;
  const FPS = 30;                  // el movimiento es lento (4 s por ciclo): 30 fps se ven igual y cuestan la mitad
  const ALPHA_STEPS = 6;           // las barras se agrupan por opacidad: 6 trazos por cuadro en vez de uno por barra

  const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
  const color = getComputedStyle(document.documentElement).getPropertyValue('--text').trim();

  let width = 0;
  let height = 0;
  let count = 0;
  let offset = 0;
  let base = new Float32Array(0);
  let phase = new Float32Array(0);
  let needsResize = true;

  // Alturas base variadas y fase propia por barra: indice * (2π / total) mas una variacion pequena.
  function build() {
    let seed = 11;
    const random = () => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    base = new Float32Array(count);
    phase = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const wave = 0.5 + 0.5 * Math.sin(i * 0.21) * Math.sin(i * 0.053 + 1);
      base[i] = clamp(0.3 + 0.35 * wave + 0.2 * random(), LEVEL_MIN + AMPLITUDE / 2, LEVEL_MAX - AMPLITUDE / 2);
      phase[i] = i * (Math.PI * 2 / count) + (random() - 0.5) * 0.9;
    }
  }

  function resize() {
    needsResize = false;
    width = canvas.clientWidth;
    height = canvas.clientHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    count = Math.max(1, Math.floor(width / PITCH));
    offset = (width - count * PITCH) / 2;
    build();
  }

  function draw(seconds) {
    if (needsResize) resize();
    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = color;
    ctx.lineCap = 'round';
    ctx.lineWidth = BAR;
    const cy = height / 2;
    const w = (Math.PI * 2 * seconds) / PERIOD;
    // Un solo trazo por nivel de opacidad (en vez de uno por barra): menos llamadas y menos cambios de estado.
    for (let step = 0; step < ALPHA_STEPS; step++) {
      ctx.globalAlpha = ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN) * (step / (ALPHA_STEPS - 1));
      ctx.beginPath();
      for (let i = 0; i < count; i++) {
        const level = base[i] + AMPLITUDE * 0.5 * Math.sin(w + phase[i]);
        const t = clamp((level - LEVEL_MIN) / (LEVEL_MAX - LEVEL_MIN));
        if (Math.round(t * (ALPHA_STEPS - 1)) !== step) continue;
        const half = Math.max(0, (clamp(level, LEVEL_MIN, LEVEL_MAX) * height - BAR) / 2);
        const x = offset + PITCH * (i + 0.5);
        ctx.moveTo(x, cy - half);
        ctx.lineTo(x, cy + half);
      }
      ctx.stroke();
    }
  }

  // ---- Bucle: se suscribe al bucle unico (smoke.js); el tiempo solo avanza mientras dibuja ----
  let elapsed = 0;
  let inView = true;
  let running = false;

  function step(dt) {
    elapsed += dt;
    draw(elapsed);
  }
  // Solo esta suscrito al bucle mientras se ve: con la franja fuera de pantalla no queda ningun
  // requestAnimationFrame en la pagina (el humo vive en su Worker).
  function sync() {
    const should = inView && !reduced.matches && !document.hidden;
    if (should && !running) { window.SplitterLoop.add(step, FPS); running = true; }
    else if (!should && running) { window.SplitterLoop.remove(step); running = false; }
    if (reduced.matches) draw(0);
  }
  document.addEventListener('visibilitychange', sync);

  new ResizeObserver(() => { needsResize = true; if (!running) draw(elapsed); }).observe(canvas);
  new IntersectionObserver(([entry]) => { inView = entry.isIntersecting; sync(); }).observe(canvas);
  reduced.addEventListener('change', sync);
  sync();
})();
