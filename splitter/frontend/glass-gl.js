// Vidrio liquido propio de Splitter (sustituye a liquidGL + html2canvas).
// No captura la pagina: el vidrio vuelve a calcular lo que hay detras con la MISMA formula del humo
// (window.SplitterSmoke.glsl) y la textura de light.svg, en la posicion refractada. Asi refracta el humo
// en movimiento y la luz sin snapshots, sin texturas desfasadas y sin recapturas al cambiar la altura.
//  - Un canvas WebGL fijo (#glass-canvas) entre el fondo y el contenido; las tarjetas siguen encima.
//  - Cada lente es un elemento vacio (.lente / .lente-pastilla) que glass.js mueve; aqui solo se lee su caja.
//  - Optica por pixel: perfil de bisel circular, refraccion hacia dentro, aberracion cromatica en el borde,
//    fresnel, especular con la luz arriba a la derecha (donde esta la fuente de light.svg) y sombra suave.
//  - Ritmo: dibuja cuando cambia el humo (30/12 fps segun smoke.js), cuando una lente se mueve, o con poke().
// API: window.SplitterGlass = { supported, add(el, preset) -> { el, setTint, set, remove }, poke() }.
(() => {
  'use strict';
  const smoke = window.SplitterSmoke;
  const loop = window.SplitterLoop;
  const MAX_DPR = 1.5;         // el vidrio es suave; mas densidad cuesta el doble y no se nota
  const SHADOW_PAD = 28;       // px css alrededor de cada lente para la sombra

  // Presets en px css. bevel = ancho del bisel; refraction = desplazamiento maximo en el borde;
  // chroma = separacion de canales en el borde; gain = cuanto "concentra" la luz el vidrio (contraste del fondo).
  // rim / rimWidth = intensidad y grosor (px) de la linea de borde (sin ellos: 1 y 1.6, el borde original).
  // gem (lente de las tarjetas) y small (calidad): vidrio claro con borde blanco marcado y destellos en las esquinas.
  const PRESETS = {
    gem:  { bevel: 30, refraction: 56, chroma: 0.5, magnify: 1.03, gain: 1.6, specular: 1.8, tint: 0.02, shadow: 0.55, rim: 3.6, rimWidth: 2.2 },
    small:{ bevel: 24, refraction: 36, chroma: 0.4, magnify: 1.05, gain: 1.55, specular: 1.6, tint: 0.02, shadow: 0.45, rim: 3, rimWidth: 2 },
    chip: { bevel: 12, refraction: 12, chroma: 0.12, magnify: 1.0,  gain: 1.4, specular: 0.45, tint: 0.06, shadow: 0.25 },
    // panel (recuadro de subir audio): mismo vidrio que gem, con bisel ancho para una superficie grande.
    panel:{ bevel: 40, refraction: 60, chroma: 0.35, magnify: 1.02, gain: 1.5, specular: 1.5, tint: 0.03, shadow: 0.4, rim: 2.8, rimWidth: 1.8 },
  };

  const noop = { el: null, setTint() {}, set() {}, remove() {} };
  const api = { supported: false, add: () => noop, poke() {} };
  window.SplitterGlass = api;
  if (!smoke || !loop) return;

  const canvas = document.createElement('canvas');
  canvas.id = 'glass-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false, stencil: false });
  if (!gl) return;

  const VERTEX = 'attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}';
  const FRAGMENT = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec2 uView;        // viewport en px css
uniform float uDpr;        // px del canvas por px css
uniform vec2 uSmokeRes;    // tamano interno del canvas del humo
uniform float t;
uniform vec3 ramp[5];
uniform float strength;
uniform float ceiling;
uniform vec3 uBg;
uniform sampler2D uLight;
uniform vec4 uLightRect;   // caja de .light en px css (x, y, w, h); w = 0 sin luz
uniform vec4 uRect;        // caja de la lente en px css (x, y, w, h)
uniform vec4 uShape;       // radio, bisel, refraccion, croma
uniform vec4 uLook;        // tinte, opacidad, ganancia, especular
uniform vec2 uExtra;       // magnify, sombra
uniform vec2 uRim;         // intensidad y grosor (px) de la linea de borde
uniform sampler2D uSmoke;  // el humo del cuadro actual, a la misma resolucion baja que su canvas (pasada previa)

// Lo que hay detras en el punto p (px css, origen arriba a la izquierda): fondo, humo encima, luz encima.
// El humo se lee de la textura con filtro lineal: es exactamente lo que se ve en pantalla (el canvas del humo
// es 1/8 de resolucion escalado por CSS), sin repetir la formula entera en cada pixel del vidrio.
vec3 behind(vec2 p) {
  vec2 fc = vec2(p.x, uView.y - p.y) * uSmokeRes / uView;
  vec4 s = texture2D(uSmoke, fc / uSmokeRes);
  vec3 c = uBg * (1. - s.a) + s.rgb;
  if (uLightRect.z > 0.) {
    vec2 lu = (p - uLightRect.xy) / uLightRect.zw;
    if (lu.x >= 0. && lu.y >= 0. && lu.x <= 1. && lu.y <= 1.) {
      vec4 l = texture2D(uLight, lu);
      c = c * (1. - l.a) + l.rgb;
    }
  }
  return c;
}

float sdRound(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return length(max(q, 0.)) + min(max(q.x, q.y), 0.) - r;
}

void main() {
  vec2 px = vec2(gl_FragCoord.x, uView.y * uDpr - gl_FragCoord.y) / uDpr;
  vec2 hb = uRect.zw * .5;
  vec2 lp = px - (uRect.xy + hb);
  float r = min(uShape.x, min(hb.x, hb.y));
  float d = sdRound(lp, hb, r);
  float aa = 1. / uDpr;

  // Sombra fuera de la lente, un poco hacia abajo.
  if (d > 0.) {
    float ds = sdRound(lp - vec2(0., 5.), hb, r);
    float sh = uExtra.y * exp(-max(ds, 0.) / 9.) * uLook.y;
    gl_FragColor = vec4(0., 0., 0., sh * (1. - smoothstep(0., aa, -d)));
    return;
  }

  float depth = -d;
  float x = clamp(depth / uShape.y, 0., 1.);       // 0 en el borde, 1 en la meseta
  float h = sqrt(1. - (1. - x) * (1. - x));        // perfil circular del bisel
  vec2 e = vec2(.5, 0.);
  vec2 g = vec2(sdRound(lp + e.xy, hb, r) - sdRound(lp - e.xy, hb, r),
                sdRound(lp + e.yx, hb, r) - sdRound(lp - e.yx, hb, r));
  g = g / max(length(g), 1e-4);                    // normal 2D hacia fuera
  float slope = (1. - x) / max(h, .08);

  // Refraccion: el borde trae hacia dentro lo que hay fuera (como una lente gruesa) + leve aumento.
  vec2 center = uRect.xy + hb;
  vec2 base = center + lp / uExtra.x;
  vec2 off = -g * uShape.z * (1. - h);
  vec3 col;
  if (x < .999) {
    float ca = uShape.w;
    col.r = behind(base + off * (1. + ca)).r;
    col.g = behind(base + off).g;
    col.b = behind(base + off * (1. - ca)).b;
  } else {
    col = behind(base);
  }

  // El vidrio concentra la luz: sube el contraste del fondo respecto al negro de la pagina.
  col = uBg + (col - uBg) * uLook.z;
  col = mix(col, uBg, uLook.x);

  // Iluminacion: normal 3D del bisel, luz arriba a la derecha.
  vec3 n = normalize(vec3(g * slope * .85, 1.));
  vec3 L = normalize(vec3(.45, -.8, .6));
  float spec = pow(max(dot(reflect(-L, n), vec3(0., 0., 1.)), 0.), 24.) * uLook.w;
  float fres = pow(1. - n.z, 2.2) * .38;
  float lit = .5 + .5 * dot(g, normalize(vec2(.55, -.85)));     // el borde de arriba-derecha brilla mas
  float rim = (1. - smoothstep(0., uRim.y, depth)) * (.12 + .3 * lit) * uRim.x;
  vec3 white = ramp[4];
  col += white * (spec + fres * (.4 + .6 * lit) + rim);

  float alpha = smoothstep(0., aa, depth) * uLook.y;
  gl_FragColor = vec4(col * alpha, alpha);
}`;

  // Pasada del humo: la misma formula de smoke.js (SplitterSmoke.glsl), dibujada a la resolucion del canvas del
  // humo en una textura. Cuesta ~13 mil pixeles por cuadro en vez de recalcularla en cada pixel del vidrio.
  const SMOKE_FRAGMENT = `
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
${smoke.glsl}
void main(){ gl_FragColor = smokeAt(gl_FragCoord.xy, res, t); }`;

  function compile(type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    return shader;
  }
  function link(fragment, label) {
    const p = gl.createProgram();
    gl.attachShader(p, compile(gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fragment));
    gl.bindAttribLocation(p, 0, 'a');   // las dos pasadas comparten el mismo triangulo
    gl.linkProgram(p);
    if (gl.getProgramParameter(p, gl.LINK_STATUS)) return p;
    console.warn(`[glass] shader ${label}:`, gl.getProgramInfoLog(p));
    return null;
  }
  const smokeProgram = link(SMOKE_FRAGMENT, 'humo');
  const program = smokeProgram && link(FRAGMENT, 'vidrio');
  if (!program) return;
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

  gl.useProgram(smokeProgram);
  const SU = { res: gl.getUniformLocation(smokeProgram, 'res'), t: gl.getUniformLocation(smokeProgram, 't') };
  gl.uniform3fv(gl.getUniformLocation(smokeProgram, 'ramp'), new Float32Array(smoke.ramp));
  gl.uniform1f(gl.getUniformLocation(smokeProgram, 'strength'), smoke.strength);
  gl.uniform1f(gl.getUniformLocation(smokeProgram, 'ceiling'), smoke.ceiling);
  const smokeTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, smokeTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
  for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
  const smokeFbo = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, smokeFbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, smokeTex, 0);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  let smokeSize = [0, 0];
  let smokeT = null;
  // Rehace la textura del humo solo si cambio su t o su tamano; deja el estado listo para la pasada del vidrio.
  function renderSmoke(time, res) {
    if (time === smokeT && res[0] === smokeSize[0] && res[1] === smokeSize[1]) return;
    gl.bindTexture(gl.TEXTURE_2D, smokeTex);
    if (res[0] !== smokeSize[0] || res[1] !== smokeSize[1]) {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, res[0], res[1], 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      smokeSize = [res[0], res[1]];
    }
    smokeT = time;
    gl.bindFramebuffer(gl.FRAMEBUFFER, smokeFbo);
    gl.disable(gl.SCISSOR_TEST);
    gl.disable(gl.BLEND);
    gl.viewport(0, 0, res[0], res[1]);
    gl.useProgram(smokeProgram);
    gl.uniform2f(SU.res, res[0], res[1]);
    gl.uniform1f(SU.t, time);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.enable(gl.BLEND);
    gl.enable(gl.SCISSOR_TEST);
    gl.useProgram(program);
  }

  gl.useProgram(program);
  const U = {};
  for (const name of ['uView', 'uDpr', 'uSmokeRes', 'uBg', 'uLight', 'uLightRect', 'uRect', 'uShape', 'uLook', 'uExtra', 'uRim', 'uSmoke']) {
    U[name] = gl.getUniformLocation(program, name);
  }
  gl.uniform3fv(gl.getUniformLocation(program, 'ramp'), new Float32Array(smoke.ramp));   // ramp[4]: el blanco de los brillos
  gl.uniform1i(U.uSmoke, 1);   // unidad 1: humo; unidad 0: luz
  const bgHex = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim().replace('#', '') || '0A0A0A';
  const bgN = parseInt(bgHex.length === 3 ? bgHex.replace(/./g, '$&$&') : bgHex, 16);
  gl.uniform3f(U.uBg, ((bgN >> 16) & 255) / 255, ((bgN >> 8) & 255) / 255, (bgN & 255) / 255);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  gl.enable(gl.SCISSOR_TEST);
  gl.clearColor(0, 0, 0, 0);

  // ---- Luz: light.svg rasterizado una vez a textura; su caja se lee de .light (incluye la deriva CSS) ----
  const lightEl = document.querySelector('.light');
  let lightReady = false;
  const lightTex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, lightTex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
  for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
  gl.uniform1i(U.uLight, 0);
  if (lightEl) {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = 1600; c.height = 1000;
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      gl.bindTexture(gl.TEXTURE_2D, lightTex);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, c);
      lightReady = true;
      dirty = true;
    };
    img.src = 'light.svg';
  }

  // ---- Lentes ----
  const lenses = [];
  let dirty = true;
  let activeUntil = 0;
  const poke = (ms = 700) => { activeUntil = Math.max(activeUntil, performance.now() + ms); dirty = true; };

  function parseTint(value) {
    if (typeof value === 'number') return value;
    const m = /rgba?\([^)]*,\s*([\d.]+)\s*\)$/.exec(String(value || ''));
    return m ? Math.min(1, Number(m[1]) * 0.25) : null;   // los tintes viejos (0.72 / 0.4) eran para tapar; aqui solo matizan
  }
  function radiusOf(el) {
    const r = parseFloat(getComputedStyle(el).borderTopLeftRadius);
    return Number.isFinite(r) ? r : 24;
  }

  function add(el, preset = 'small') {
    const lens = { el, opts: { ...(PRESETS[preset] || PRESETS.small) }, radius: radiusOf(el), opacity: 1 };
    lenses.push(lens);
    dirty = true;
    start();
    return {
      el,
      setTint(value) { const a = parseTint(value); if (a !== null) { lens.opts.tint = a; dirty = true; } },
      set(opts) { Object.assign(lens.opts, opts); dirty = true; },
      remove() { const i = lenses.indexOf(lens); if (i >= 0) lenses.splice(i, 1); dirty = true; },
    };
  }

  // ---- Canvas y tamano ----
  Object.assign(canvas.style, { position: 'fixed', inset: '0', width: '100%', height: '100%', zIndex: '-1', pointerEvents: 'none', display: 'block' });
  document.body.append(canvas);
  let viewW = 0, viewH = 0, dpr = 1;
  function resize() {
    // Tamano real del canvas en pantalla. innerWidth incluye la barra de scroll y el canvas (100%) no: con
    // innerWidth el dibujo se estiraba a un ancho menor y todo el vidrio quedaba corrido hacia la izquierda.
    viewW = canvas.clientWidth || window.innerWidth; viewH = canvas.clientHeight || window.innerHeight;
    dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    const w = Math.max(1, Math.round(viewW * dpr)), h = Math.max(1, Math.round(viewH * dpr));
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    gl.viewport(0, 0, w, h);
    for (const lens of lenses) lens.radius = radiusOf(lens.el);
    dirty = true;
  }
  window.addEventListener('resize', resize, { passive: true });
  // La barra de scroll aparece o desaparece cuando cambia la altura de la pagina, sin evento resize.
  if ('ResizeObserver' in window) new ResizeObserver(() => resize()).observe(canvas);
  // Sin avisos por scroll, cursor o teclado: draw() ya compara en cada cuadro la caja de cada lente y el t del humo,
  // y solo redibuja si algo cambio. Antes cada movimiento del raton en cualquier parte forzaba redibujar el vidrio.
  resize();

  // ---- Dibujo ----
  let lastT = -1;
  let lastKey = '';
  function draw(force) {
    const time = smoke.time();
    const res = smoke.res();
    const boxes = [];
    let key = '';
    for (const lens of lenses) {
      if (lens.el.hidden || !lens.el.isConnected) continue;
      const b = lens.el.getBoundingClientRect();
      if (b.width < 2 || b.height < 2 || b.bottom < -SHADOW_PAD || b.top > viewH + SHADOW_PAD) continue;
      boxes.push([lens, b]);
      key += `${b.x | 0},${b.y | 0},${b.width | 0},${b.height | 0},${lens.opts.tint};`;
    }
    if (!force && !dirty && time === lastT && key === lastKey && performance.now() > activeUntil) return;
    lastT = time; lastKey = key; dirty = false;

    gl.disable(gl.SCISSOR_TEST);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.SCISSOR_TEST);
    if (!boxes.length || !res) return;

    renderSmoke(time, res);
    gl.uniform2f(U.uView, viewW, viewH);
    gl.uniform1f(U.uDpr, dpr);
    gl.uniform2f(U.uSmokeRes, res[0], res[1]);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, smokeTex);
    if (lightReady && lightEl) {
      const l = lightEl.getBoundingClientRect();
      gl.uniform4f(U.uLightRect, l.x, l.y, l.width, l.height);
    } else gl.uniform4f(U.uLightRect, 0, 0, 0, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, lightTex);

    for (const [lens, b] of boxes) {
      const o = lens.opts;
      const x0 = Math.max(0, Math.floor((b.left - SHADOW_PAD) * dpr));
      const x1 = Math.min(canvas.width, Math.ceil((b.right + SHADOW_PAD) * dpr));
      const y0 = Math.max(0, Math.floor((viewH - b.bottom - SHADOW_PAD) * dpr));
      const y1 = Math.min(canvas.height, Math.ceil((viewH - b.top + SHADOW_PAD) * dpr));
      if (x1 <= x0 || y1 <= y0) continue;
      gl.scissor(x0, y0, x1 - x0, y1 - y0);
      gl.uniform4f(U.uRect, b.left, b.top, b.width, b.height);
      gl.uniform4f(U.uShape, lens.radius, o.bevel, o.refraction, o.chroma);
      gl.uniform4f(U.uLook, o.tint, lens.opacity, o.gain, o.specular);
      gl.uniform2f(U.uExtra, o.magnify, o.shadow);
      gl.uniform2f(U.uRim, o.rim ?? 1, o.rimWidth ?? 1.6);   // sin rim/rimWidth: el borde de siempre
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
  }

  let running = false;
  const step = () => draw(false);
  function start() {
    if (running) return;
    running = true;
    loop.add(step);
  }
  canvas.addEventListener('webglcontextlost', (event) => { event.preventDefault(); loop.remove(step); running = false; document.documentElement.classList.add('no-glass'); });

  Object.assign(api, { supported: true, add, poke, redraw: () => draw(true) });
})();
