// Humo de cigarro de fondo y el UNICO requestAnimationFrame de la pagina (SplitterLoop).
//  - Canvas WebGL a baja resolucion (1/SCALE), escalado por CSS. Un shader con ruido de dominio deformado
//    dibuja hilos finos que suben y se retuercen sin parar; no hay particulas ni trabajo por pixel en CPU.
//  - El humo se dibuja en un Worker (OffscreenCanvas): compilar el shader y las esperas de la GPU no
//    bloquean la pagina. Sin soporte, se dibuja aqui mismo dentro de SplitterLoop.
//  - El canvas es fijo y queda fuera del snapshot de liquidGL, asi que el vidrio no lo toca.
(() => {
  'use strict';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  // ---- Bucle unico: wave.js y el humo se suscriben aqui; nadie mas pide su propio frame ----
  // Cada suscriptor puede pedir un tope de fps: el bucle le llama solo cuando toca, con el dt acumulado.
  const subscribers = [];
  let frame = 0;
  let last = null;
  function tick(now) {
    const dt = last === null ? 0 : Math.min((now - last) / 1000, 0.1);
    last = now;
    for (let i = 0; i < subscribers.length; i++) {
      const sub = subscribers[i];
      sub.acc += dt;
      if (sub.every && sub.acc * 1000 < sub.every - 2) continue;
      const elapsed = sub.acc;
      sub.acc = 0;
      sub.fn(elapsed);
    }
    frame = requestAnimationFrame(tick);
  }
  function run() {
    if (frame || !subscribers.length || document.hidden) return;
    last = null;
    frame = requestAnimationFrame(tick);
  }
  function halt() {
    cancelAnimationFrame(frame);
    frame = 0;
  }
  document.addEventListener('visibilitychange', () => { if (document.hidden) halt(); else run(); });
  window.SplitterLoop = {
    // fps = 0: cada frame. Sin suscriptores el bucle se detiene del todo (ni un requestAnimationFrame vacio).
    add(fn, fps = 0) {
      if (subscribers.some((sub) => sub.fn === fn)) return;
      subscribers.push({ fn, every: fps ? 1000 / fps : 0, acc: 0 });
      run();
    },
    remove(fn) {
      const i = subscribers.findIndex((sub) => sub.fn === fn);
      if (i >= 0) subscribers.splice(i, 1);
      if (!subscribers.length) halt();
    },
  };

  const canvas = document.getElementById('smoke-canvas');
  if (!canvas) return;

  const SCALE = 8;            // resolucion interna = 1/8 de la pantalla: el humo es difuso y no pierde detalle
  const FRAME_MS = 1000 / 30; // la deriva es lenta: 30 fps se ve igual y deja la GPU libre para el vidrio
  const FAR_MS = 1000 / 12;   // con el hero fuera de pantalla (formulario, vidrio): el humo es un velo muy tenue, 12 fps bastan y la GPU queda libre
  const SPEED = 1;            // multiplicador de la deriva
  const START = 40;           // arranca ya avanzado, para que la primera vista (y el modo sin movimiento) no salga vacia

  const style = getComputedStyle(document.documentElement);
  // Carbon -> gris humo -> plata -> perla -> blanco frio: de la sombra a la zona iluminada.
  const ramp = ['shadow', 'grey', 'silver', 'pearl', 'white']
    .flatMap((name) => style.getPropertyValue(`--smoke-${name}`).trim().split(/\s+/).map((v) => Number(v) / 255));
  const strength = parseFloat(style.getPropertyValue('--smoke-alpha')) || 0.4;
  const ceiling = parseFloat(style.getPropertyValue('--smoke-ceiling')) || 0.23; // tope de opacidad: mantiene el contraste AA del texto

  const VERTEX = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}';
  const FRAGMENT = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec2 res;
uniform float t;
uniform vec3 ramp[5];
uniform float strength;
uniform float ceiling;

float hash(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float noise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3. - 2. * f);
  return mix(mix(hash(i), hash(i + vec2(1., 0.)), f.x), mix(hash(i + vec2(0., 1.)), hash(i + vec2(1., 1.)), f.x), f.y);
}
float fbm(vec2 p){
  float a = .5, s = 0.;
  for (int i = 0; i < 4; i++) { s += a * noise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= .5; }
  return s;
}

void main(){
  vec2 uv = gl_FragCoord.xy / res.y;
  // Niebla que sube despacio: el campo baja y se deforma dos veces, de ahi salen los pliegues del humo.
  vec2 p = uv * vec2(1.15, 0.95);
  p.y -= t * 0.04;
  p.x += 0.1 * sin(t * 0.06 + uv.y * 1.2);
  vec2 q = vec2(fbm(p + vec2(0., t * 0.03)), fbm(p + vec2(5.2, 1.3) - t * 0.025));
  vec2 r = vec2(fbm(p + 3. * q + vec2(1.7, 9.2) + t * 0.035), fbm(p + 3. * q + vec2(8.3, 2.8) - t * 0.03));
  float f = fbm(p + 3. * r);
  float fold = pow(1. - abs(2. * f - 1.), 2.6);          // pliegues suaves, sin hilos duros
  float haze = smoothstep(.3, .8, fbm(p * .7 + r));      // velo difuso de fondo
  float body = smoothstep(.15, .7, fbm(p * .4 + vec2(3.1, t * -.02)));  // zonas con y sin humo
  float v = (fold * .55 + haze * .5) * body;
  // Se apaga hacia los bordes para que no haya cortes duros.
  vec2 s = gl_FragCoord.xy / res;
  v *= smoothstep(0., .18, s.x) * smoothstep(0., .18, 1. - s.x) * smoothstep(0., .1, 1. - s.y);
  float l = clamp(v, 0., 1.);
  // La luz fria solo llega a las crestas: plata y perla en la zona media, blanco apenas en los reflejos.
  vec3 c = mix(ramp[0], ramp[1], smoothstep(0., .15, l));
  c = mix(c, ramp[2], smoothstep(.2, .45, l));
  c = mix(c, ramp[3], smoothstep(.4, .7, l));
  c = mix(c, ramp[4], smoothstep(.8, 1., l));
  // Curva suave contra el tope: el humo gana presencia en la zona media sin pasar nunca del tope.
  float a = ceiling * (1. - exp(-pow(l, .7) * strength / ceiling));
  gl_FragColor = vec4(c * a, a);
}`;

  const config = { vertex: VERTEX, fragment: FRAGMENT, ramp, strength, ceiling, frameMs: FRAME_MS, speed: SPEED, start: START };

  // ---- Motor de dibujo. Autocontenido: se serializa tal cual para el Worker ----
  // Compilacion sin bloquear: con KHR_parallel_shader_compile el shader se compila en segundo plano y
  // draw() devuelve false hasta que esta listo; preguntar antes por LINK_STATUS congelaria el hilo.
  function createSmoke(target, cfg) {
    const gl = target.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false });
    if (!gl) return null;
    target.addEventListener('webglcontextlost', (event) => event.preventDefault());
    const parallel = gl.getExtension('KHR_parallel_shader_compile');
    const program = gl.createProgram();
    for (const [type, source] of [[gl.VERTEX_SHADER, cfg.vertex], [gl.FRAGMENT_SHADER, cfg.fragment]]) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      gl.attachShader(program, shader);
    }
    gl.linkProgram(program);

    let ready = false;
    let failed = false;
    let uRes = null;
    let uTime = null;
    let size = null;
    let sized = false;
    function link() {
      if (ready || failed) return ready;
      if (parallel && !gl.getProgramParameter(program, parallel.COMPLETION_STATUS_KHR)) return false;
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { failed = true; return false; }
      gl.useProgram(program);
      gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      const position = gl.getAttribLocation(program, 'a');
      gl.enableVertexAttribArray(position);
      gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
      uRes = gl.getUniformLocation(program, 'res');
      uTime = gl.getUniformLocation(program, 't');
      gl.uniform3fv(gl.getUniformLocation(program, 'ramp'), new Float32Array(cfg.ramp));
      gl.uniform1f(gl.getUniformLocation(program, 'strength'), cfg.strength);
      gl.uniform1f(gl.getUniformLocation(program, 'ceiling'), cfg.ceiling);
      ready = true;
      return true;
    }
    return {
      get failed() { return failed; },
      hasParallelCompile: Boolean(parallel),
      setSize(width, height) { size = [width, height]; sized = false; },
      draw(seconds) {
        if (!size || !link()) return false;
        if (!sized) {
          sized = true;
          if (target.width !== size[0]) target.width = size[0];
          if (target.height !== size[1]) target.height = size[1];
          gl.viewport(0, 0, size[0], size[1]);
          gl.uniform2f(uRes, size[0], size[1]);
        }
        gl.uniform1f(uTime, seconds);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        return true;
      },
    };
  }

  // ---- Reloj del humo: avanza solo mientras corre, dibuja cada FRAME_MS y reintenta si el shader no esta listo ----
  function createClock(smoke, cfg) {
    let elapsed = cfg.start;
    let sinceDraw = cfg.frameMs;
    let stillTimer = 0;
    const clock = {
      // Devuelve false si el shader fallo y no tiene sentido seguir.
      step(dt) {
        elapsed += dt * cfg.speed;
        sinceDraw += dt * 1000;
        if (sinceDraw < cfg.frameMs - 2) return true;
        if (smoke.draw(elapsed)) sinceDraw = 0;
        return !smoke.failed;
      },
      // Modo sin movimiento: un solo cuadro, en cuanto el shader termine de compilar.
      still() {
        clearTimeout(stillTimer);
        if (!smoke.draw(elapsed) && !smoke.failed) stillTimer = setTimeout(clock.still, 50);
      },
      cancelStill() { clearTimeout(stillTimer); },
      setFrameMs(ms) { cfg.frameMs = ms; },
    };
    return clock;
  }

  // ---- Worker: su propio requestAnimationFrame, fuera del hilo de la pagina ----
  function smokeWorker(createSmoke, createClock) {
    let smoke = null;
    let clock = null;
    let mode = 'stop';
    let raf = 0;
    let last = null;
    const frame = self.requestAnimationFrame ? (fn) => self.requestAnimationFrame(fn) : (fn) => setTimeout(() => fn(performance.now()), 16);
    const cancel = self.cancelAnimationFrame ? (id) => self.cancelAnimationFrame(id) : (id) => clearTimeout(id);
    function tick(now) {
      raf = 0;
      const dt = last === null ? 0 : Math.min((now - last) / 1000, 0.1);
      last = now;
      if (clock.step(dt)) raf = frame(tick);
    }
    self.onmessage = ({ data }) => {
      if (data.canvas) {
        smoke = createSmoke(data.canvas, data.config);
        if (smoke) clock = createClock(smoke, data.config);
      }
      if (!smoke) return;
      if (data.frameMs) clock.setFrameMs(data.frameMs);
      if (data.size) {
        smoke.setSize(data.size[0], data.size[1]);
        if (mode === 'still') clock.still();
      }
      if (data.mode && data.mode !== mode) {
        mode = data.mode;
        cancel(raf);
        raf = 0;
        last = null;
        clock.cancelStill();
        if (mode === 'run') raf = frame(tick);
        else if (mode === 'still') clock.still();
      }
    };
  }

  // Tamano interno del canvas. ResizeObserver no fuerza layout; tras el primer tamano, se espera a que el resize se asiente.
  function watchSize(apply) {
    let timer = 0;
    let first = true;
    new ResizeObserver(([entry]) => {
      const box = entry.contentRect;
      const next = [Math.max(1, Math.ceil(box.width / SCALE)), Math.max(1, Math.ceil(box.height / SCALE))];
      clearTimeout(timer);
      if (first) { first = false; apply(next); } else timer = setTimeout(() => apply(next), 150);
    }).observe(canvas);
  }

  // Ritmo segun lo que se ve: a pleno ritmo solo mientras el hero esta en pantalla.
  function watchHero(apply) {
    const hero = document.querySelector('.intro');
    if (!hero || !('IntersectionObserver' in window)) return;
    new IntersectionObserver(([entry]) => apply(entry.isIntersecting ? FRAME_MS : FAR_MS)).observe(hero);
  }

  function startInWorker() {
    if (!('transferControlToOffscreen' in canvas) || typeof Worker === 'undefined' || !('ResizeObserver' in window)) return false;
    let worker;
    try {
      const source = `'use strict';\n${createSmoke}\n${createClock}\n(${smokeWorker})(createSmoke, createClock);`;
      const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
      worker = new Worker(url);
      URL.revokeObjectURL(url);
      const offscreen = canvas.transferControlToOffscreen();
      worker.postMessage({ canvas: offscreen, config }, [offscreen]);
    } catch (error) {
      worker?.terminate();
      return false;
    }
    const mode = () => (reduced.matches ? 'still' : document.hidden ? 'stop' : 'run');
    const sendMode = () => worker.postMessage({ mode: mode() });
    watchSize((size) => worker.postMessage({ size }));
    watchHero((frameMs) => worker.postMessage({ frameMs }));
    sendMode();
    reduced.addEventListener('change', sendMode);
    document.addEventListener('visibilitychange', sendMode);
    return true;
  }

  function startHere() {
    const smoke = createSmoke(canvas, config);
    if (!smoke) return;
    const clock = createClock(smoke, config);
    // Sin la extension, el enlace bloquea: solo se permite cuando la pagina ya se pinto y el navegador esta libre.
    let allowed = smoke.hasParallelCompile;
    const step = (dt) => { if (allowed && !clock.step(dt)) window.SplitterLoop.remove(step); };
    function sync() {
      window.SplitterLoop.remove(step);
      clock.cancelStill();
      if (!reduced.matches) window.SplitterLoop.add(step);
      else if (allowed) clock.still();
    }
    if (!allowed) {
      const allow = () => { allowed = true; sync(); };
      const idle = () => ('requestIdleCallback' in window ? requestIdleCallback(allow, { timeout: 1500 }) : setTimeout(allow, 200));
      if (document.readyState === 'complete') idle();
      else window.addEventListener('load', idle, { once: true });
    }
    const resize = (size) => { smoke.setSize(size[0], size[1]); if (reduced.matches && allowed) clock.still(); };
    watchHero((frameMs) => clock.setFrameMs(frameMs));
    if ('ResizeObserver' in window) watchSize(resize);
    else resize([Math.max(1, Math.ceil(canvas.clientWidth / SCALE)), Math.max(1, Math.ceil(canvas.clientHeight / SCALE))]);
    reduced.addEventListener('change', sync);
    sync();
  }

  if (!startInWorker()) startHere();
})();
