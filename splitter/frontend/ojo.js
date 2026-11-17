// Ojo para ver u ocultar la contrasena: se agrega solo a cada <input type="password"> (tambien a los que se crean despues).
(() => {
  const OJO = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  const OJO_TACHADO = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/><path d="M4 4l16 16"/></svg>';

  function agregar(input) {
    if (input.dataset.ojo) return;
    input.dataset.ojo = '1';
    const caja = document.createElement('span');
    caja.className = 'clave-caja';
    input.before(caja);
    caja.append(input);
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'clave-ojo';
    caja.append(boton);
    const pintar = () => {
      const visible = input.type === 'text';
      boton.innerHTML = visible ? OJO_TACHADO : OJO;
      boton.setAttribute('aria-label', visible ? 'Ocultar contraseña' : 'Mostrar contraseña');
      boton.setAttribute('aria-pressed', String(visible));
    };
    boton.addEventListener('click', () => {
      const inicio = input.selectionStart, fin = input.selectionEnd;
      input.type = input.type === 'password' ? 'text' : 'password';
      pintar();
      input.focus();
      try { input.setSelectionRange(inicio, fin); } catch {}
    });
    pintar();
  }

  const buscar = (raiz) => raiz.querySelectorAll?.('input[type="password"]').forEach(agregar);
  buscar(document);
  new MutationObserver((cambios) => {
    for (const c of cambios) for (const n of c.addedNodes) if (n.nodeType === 1) { if (n.matches('input[type="password"]')) agregar(n); else buscar(n); }
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
