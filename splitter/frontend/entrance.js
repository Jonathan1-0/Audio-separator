// Entrada de la pagina: barras del logo y h1. Si este modulo no carga, la pagina se ve completa.
import { animate, stagger } from 'https://cdn.jsdelivr.net/npm/motion@14.9.0/+esm';

const EASE = [0.22, 1, 0.36, 1];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const bars = [...document.querySelectorAll('.brand-bars rect')];
const title = document.getElementById('page-title');

function enterBars() {
  for (const bar of bars) Object.assign(bar.style, { opacity: '0', transform: 'translateY(40px)' });
  animate(bars, { opacity: [0, 1], y: [40, 0] }, { duration: 0.2, ease: EASE, delay: stagger(0.025) })
    .finished.then(() => bars.forEach((bar) => bar.removeAttribute('style')));
}

function enterTitle() {
  const text = title.textContent.trim();
  title.setAttribute('aria-label', text);
  title.replaceChildren(...text.split(' ').flatMap((word, index) => {
    const wrap = document.createElement('span');
    wrap.setAttribute('aria-hidden', 'true');
    wrap.style.cssText = 'display:inline-block;white-space:nowrap';
    wrap.append(...[...word].map((char) => {
      const letter = document.createElement('span');
      letter.textContent = char;
      letter.style.cssText = 'display:inline-block;opacity:0;filter:blur(10px);will-change:opacity,filter';
      return letter;
    }));
    return index ? [' ', wrap] : [wrap];
  }));
  const letters = [...title.querySelectorAll('[style*="blur"]')];
  // Orden aleatorio (Fisher-Yates): rango de llegada de cada letra.
  const order = letters.map((_, i) => i);
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [order[i], order[j]] = [order[j], order[i]];
  }
  const duration = 0.2;
  const step = (0.4 - duration) / Math.max(letters.length - 1, 1); // 100ms -> 500ms
  const done = letters.map((letter, i) => animate(
    letter,
    { opacity: [0, 1], filter: ['blur(10px)', 'blur(0px)'] },
    { duration, ease: EASE, delay: 0.1 + order[i] * step },
  ).finished);
  // Un frame despues, para que Motion termine de fijar el estado final antes de limpiarlo.
  Promise.all(done).then(() => requestAnimationFrame(() => letters.forEach((letter) => {
    for (const prop of ['will-change', 'opacity', 'filter']) letter.style.removeProperty(prop);
  })));
}

function setupLogoHover() {
  const brand = document.querySelector('.brand');
  let running = false;
  brand.addEventListener('pointerenter', (event) => {
    if (running || reduced.matches || event.pointerType === 'touch') return;
    running = true;
    const wobble = bars.map((bar, i) => animate(
      bar,
      { scaleY: i % 2 ? [1, 1.12, 0.7, 1] : [1, 0.62, 1.1, 1] },
      { duration: 0.4, ease: EASE },
    ).finished.then(() => bar.removeAttribute('style')));
    Promise.all(wobble).then(() => { running = false; });
  });
}

if (bars.length && title) {
  setupLogoHover();
  if (!reduced.matches) {
    enterBars();
    enterTitle();
  }
}
