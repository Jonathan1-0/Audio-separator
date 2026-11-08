// Presentation only: index.js owns form state and validation.
(() => {
  'use strict';
  // Aged Gold -> Soft Champagne -> Warm Stone -> Muted Olive: cada barra mezcla los dos tonos vecinos segun su posicion.
  const TONES = ['voz', 'bateria', 'bajo', 'otros'].map(name => `var(--stem-${name})`);
  function toneAt(position) {
    const scaled = position * (TONES.length - 1);
    const index = Math.min(TONES.length - 2, Math.floor(scaled));
    const share = ((scaled - index) * 100).toFixed(1);
    return `color-mix(in oklab, ${TONES[index]} ${(100 - share).toFixed(1)}%, ${TONES[index + 1]} ${share}%)`;
  }
  function drawWave(container, names, barsPerGroup) {
    const fragment = document.createDocumentFragment();
    names.forEach((name, groupIndex) => {
      const group = document.createElement('span');
      group.className = 'stem-group';
      group.dataset.stem = name;
      for (let i = 0; i < barsPerGroup; i++) {
        const bar = document.createElement('i');
        bar.className = 'wave-bar';
        const position = (groupIndex * barsPerGroup + i) / (names.length * barsPerGroup - 1);
        const envelope = Math.sin(position * Math.PI);
        const pulse = .35 + .65 * Math.abs(Math.sin(i * 1.73 + groupIndex * .9));
        bar.style.setProperty('--bar-height', (8 + 88 * envelope * pulse).toFixed(2) + '%');
        if (!container.dataset.tone) bar.style.background = toneAt(position);
        group.append(bar);
      }
      fragment.append(group);
    });
    container.replaceChildren(fragment);
  }
  document.querySelectorAll('.mini-spectrum').forEach(element => {
    const names = element.dataset.stems.split(' ');
    drawWave(element, names, Math.round(32 / names.length));
  });

  // CSS handles the reveal. No scroll loop or animation library is needed.
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  // El formulario es un solo bloque (.flow-block): se revela entero, con el formulario, el proceso o los resultados dentro.
  const sections = [...document.querySelectorAll('.flow-block')];
  let observer;
  function setupReveals() {
    observer?.disconnect();
    if (motion.matches || !('IntersectionObserver' in window)) {
      sections.forEach(section => section.classList.remove('reveal-pending', 'reveal-ready'));
      return;
    }
    observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        entry.target.classList.remove('reveal-pending');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0, rootMargin: '0px 0px -32px 0px' });
    sections.forEach(section => {
      // Content already in view remains visible, avoiding a flash on load.
      const box = section.getBoundingClientRect();
      if (box.top < innerHeight && box.bottom > 0) section.classList.add('is-visible');
      if (!section.classList.contains('is-visible')) section.classList.add('reveal-pending');
      section.classList.add('reveal-ready');
      observer.observe(section);
    });
  }
  setupReveals();
  motion.addEventListener('change', setupReveals);
})();
