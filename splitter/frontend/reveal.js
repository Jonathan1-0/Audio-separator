// Página principal: lo que está debajo de la portada aparece suavemente la primera vez que llega a la pantalla
(() => {
  if (!('IntersectionObserver' in window) || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (document.documentElement.dataset.restore) return;   // al volver a un trabajo o a resultados no se anima

  const grupos = [
    ['.upload-step .step-heading', '#dropzone'],
    ['.mode-step .step-heading', ...document.querySelectorAll('.mode-card')],
    ['.action-row'],
    ['.workspace-footer', '.pie-legal'],
  ];

  const observer = new IntersectionObserver((entradas) => {
    for (const entrada of entradas) {
      if (!entrada.isIntersecting) continue;
      entrada.target.classList.add('is-revealed');
      observer.unobserve(entrada.target);   // solo la primera vez
    }
  }, { threshold: 0.15 });

  for (const grupo of grupos) {
    let paso = 0;
    for (const item of grupo) {
      const el = typeof item === 'string' ? document.querySelector(item) : item;
      if (!el) continue;
      el.classList.add('reveal');
      el.style.setProperty('--reveal-delay', `${paso++ * 90}ms`);
      observer.observe(el);
    }
  }
})();
