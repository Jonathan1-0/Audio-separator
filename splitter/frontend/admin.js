// Panel de administración. Usa la cookie de sesión; el servidor solo responde a la cuenta admin.
// Todo se arma con textContent: los nombres y correos de los usuarios nunca se interpretan como HTML.
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const fechaHora = (iso) => (iso ? new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' }) : '—');
  const numero = (n) => Number(n || 0).toLocaleString('es-MX');
  const dinero = (monto, moneda = 'MXN') => Number(monto || 0).toLocaleString('es-MX', { style: 'currency', currency: moneda });
  const duracion = (seg) => (seg == null ? '—' : `${Math.floor(seg / 60)}:${String(Math.round(seg % 60)).padStart(2, '0')}`);
  const NOMBRE_PLAN = { gratis: 'Gratis', pro: 'Pro', admin: 'Admin' };
  const ESTADO_TRABAJO = { en_cola: 'En cola', procesando: 'Procesando', completado: 'Completado', error: 'Error' };

  async function api(url, { method = 'GET', body } = {}) {
    const res = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch { /* sin cuerpo */ }
    if (!res.ok) {
      const error = new Error(typeof data?.detail === 'string' ? data.detail : 'No se pudo completar la acción.');
      error.status = res.status;
      throw error;
    }
    return data;
  }

  function el(tag, props = {}, ...hijos) {
    const nodo = Object.assign(document.createElement(tag), props);
    for (const h of hijos) if (h != null) nodo.append(h);
    return nodo;
  }
  const etiqueta = (texto, tipo = '') => el('span', { className: `etiqueta ${tipo ? `etiqueta-${tipo}` : ''}`, textContent: texto });

  function aviso(texto, enlace) {
    const caja = $('admin-aviso');
    caja.replaceChildren(texto);
    if (enlace) caja.append(' ', el('a', { href: enlace.href, textContent: enlace.texto }));
    caja.hidden = false;
    $('admin-panel').hidden = true;
  }

  // ---------- Pestañas (con flechas, como pide ARIA) ----------
  const tabs = [...document.querySelectorAll('.admin-tab')];
  const cargado = new Set();
  function mostrar(tab, foco = false) {
    for (const t of tabs) {
      const activa = t === tab;
      t.setAttribute('aria-selected', String(activa));
      t.tabIndex = activa ? 0 : -1;
      $(t.getAttribute('aria-controls')).hidden = !activa;
    }
    if (foco) tab.focus();
    const vista = tab.id.replace('tab-', '');
    if (!cargado.has(vista)) { cargado.add(vista); CARGAR[vista](1); }
  }
  for (const t of tabs) {
    t.addEventListener('click', () => mostrar(t));
    t.addEventListener('keydown', (e) => {
      const i = tabs.indexOf(t);
      const destino = { ArrowRight: tabs[(i + 1) % tabs.length], ArrowLeft: tabs[(i - 1 + tabs.length) % tabs.length], Home: tabs[0], End: tabs[tabs.length - 1] }[e.key];
      if (destino) { e.preventDefault(); mostrar(destino, true); }
    });
  }

  // ---------- Tablas y páginas ----------
  function tabla(id, columnas, filas, vacio) {
    const t = $(id);
    const cabeza = el('thead', {}, el('tr', {}, ...columnas.map((c) => el('th', { scope: 'col', textContent: c.titulo, className: c.num ? 'num' : '' }))));
    const cuerpo = el('tbody');
    if (!filas.length) cuerpo.append(el('tr', {}, el('td', { colSpan: columnas.length, className: 'admin-vacio', textContent: vacio })));
    for (const fila of filas) {
      cuerpo.append(el('tr', {}, ...columnas.map((c) => {
        const valor = c.valor(fila);
        const celda = el('td', { className: [c.num ? 'num' : '', c.envuelve ? 'envuelve' : ''].join(' ').trim() });
        celda.append(valor instanceof Node ? valor : String(valor ?? '—'));
        return celda;
      })));
    }
    t.replaceChildren(cabeza, cuerpo);
  }

  function paginas(id, datos, cargar) {
    const nav = $(id);
    const total = Math.max(1, Math.ceil(datos.total / datos.por_pagina));
    const anterior = el('button', { type: 'button', className: 'admin-boton admin-boton-sec', textContent: 'Anterior', disabled: datos.pagina <= 1 });
    const siguiente = el('button', { type: 'button', className: 'admin-boton admin-boton-sec', textContent: 'Siguiente', disabled: datos.pagina >= total });
    anterior.addEventListener('click', () => cargar(datos.pagina - 1));
    siguiente.addEventListener('click', () => cargar(datos.pagina + 1));
    nav.replaceChildren(el('span', { textContent: `${numero(datos.total)} en total · página ${datos.pagina} de ${total}` }), anterior, siguiente);
  }

  // ---------- Resumen ----------
  async function cargarResumen() {
    const r = await api('/admin/resumen');
    const p = r.usuarios.por_plan || {};
    const tarjetas = [
      [numero(r.usuarios.total), 'Usuarios'],
      [numero(r.usuarios.nuevos_7_dias), 'Nuevos en 7 días'],
      [numero(p.pro || 0), 'Con Pro'],
      [numero(r.usuarios.correo_confirmado), 'Con correo confirmado'],
      [dinero(r.ingresos_30_dias, r.moneda), 'Ingresos en 30 días'],
      [numero(r.trabajos.ultimas_24_h), 'Trabajos en 24 h'],
      [numero(r.trabajos.ultimos_7_dias), 'Trabajos en 7 días'],
      [numero(r.trabajos.errores_7_dias), 'Errores en 7 días'],
      [numero(r.trabajos.minutos_gpu_7_dias), 'Minutos de GPU en 7 días'],
      [numero(r.trabajos.minutos_gpu_30_dias), 'Minutos de GPU en 30 días'],
      [`${r.cola.procesando} / ${r.cola.en_cola}`, 'Procesando / en cola ahora'],
      [numero(r.usuarios.suspendidos), 'Cuentas suspendidas'],
    ];
    $('resumen-tarjetas').replaceChildren(...tarjetas.map(([valor, nombre]) => el('div', { className: 'admin-tarjeta' },
      el('span', { className: 'admin-tarjeta-valor', textContent: valor }),
      el('span', { className: 'admin-tarjeta-nombre', textContent: nombre }))));
  }

  // ---------- Usuarios ----------
  let busqueda = '';
  async function cargarUsuarios(pagina = 1) {
    const datos = await api(`/admin/usuarios?${new URLSearchParams({ q: busqueda, pagina })}`);
    tabla('tabla-usuarios', [
      { titulo: 'Nombre', valor: (u) => u.nombre, envuelve: true },
      { titulo: 'Correo', valor: (u) => u.email, envuelve: true },
      { titulo: 'Plan', valor: (u) => etiqueta(NOMBRE_PLAN[u.plan] || u.plan, u.plan === 'pro' ? 'pro' : '') },
      { titulo: 'Correo confirmado', valor: (u) => etiqueta(u.email_verificado ? 'Sí' : 'No', u.email_verificado ? 'bien' : '') },
      { titulo: 'Entra con', valor: (u) => ({ email: 'Contraseña', google: 'Google', facebook: 'Facebook' }[u.proveedor] || u.proveedor) },
      { titulo: 'Trabajos', valor: (u) => numero(u.trabajos), num: true },
      { titulo: 'Alta', valor: (u) => fechaHora(u.creado_en) },
      { titulo: 'Estado', valor: (u) => etiqueta(u.estado === 'activo' ? 'Activo' : 'Suspendido', u.estado === 'activo' ? 'bien' : 'mal') },
      { titulo: '', valor: (u) => botonEstado(u, pagina) },
    ], datos.usuarios, busqueda ? 'Nadie coincide con esa búsqueda.' : 'Todavía no hay usuarios.');
    paginas('paginas-usuarios', datos, cargarUsuarios);
  }
  function botonEstado(u, pagina) {
    if (u.plan === 'admin') return '';
    const suspender = u.estado === 'activo';
    const boton = el('button', {
      type: 'button',
      className: `admin-boton ${suspender ? 'admin-boton-peligro' : 'admin-boton-sec'}`,
      textContent: suspender ? 'Suspender' : 'Reactivar',
    });
    boton.setAttribute('aria-label', `${suspender ? 'Suspender' : 'Reactivar'} a ${u.email}`);
    boton.addEventListener('click', async () => {
      boton.disabled = true;
      try {
        await api(`/admin/usuarios/${u.id}/estado`, { method: 'POST', body: { estado: suspender ? 'suspendido' : 'activo' } });
        await cargarUsuarios(pagina);
      } catch (err) { boton.disabled = false; boton.textContent = err.message; }
    });
    return boton;
  }
  $('buscar-usuarios').addEventListener('submit', (e) => { e.preventDefault(); busqueda = $('buscar-texto').value.trim(); cargarUsuarios(1); });

  // ---------- Trabajos ----------
  async function cargarTrabajos(pagina = 1) {
    const datos = await api(`/admin/trabajos?${new URLSearchParams({ estado: $('filtro-estado').value, pagina })}`);
    tabla('tabla-trabajos', [
      { titulo: 'Fecha', valor: (t) => fechaHora(t.creado_en) },
      { titulo: 'Usuario', valor: (t) => t.email, envuelve: true },
      { titulo: 'Archivo', valor: (t) => t.nombre_original, envuelve: true },
      { titulo: 'Tipo', valor: (t) => t.preset },
      { titulo: 'Duración', valor: (t) => duracion(t.duracion_audio_seg), num: true },
      { titulo: 'GPU (s)', valor: (t) => (t.gpu_seconds == null ? '—' : Math.round(t.gpu_seconds)), num: true },
      { titulo: 'Estado', valor: (t) => etiqueta(ESTADO_TRABAJO[t.estado] || t.estado, t.estado === 'completado' ? 'bien' : t.estado === 'error' ? 'mal' : '') },
      { titulo: 'Error', valor: (t) => t.mensaje_error || '', envuelve: true },
    ], datos.trabajos, 'No hay trabajos con ese filtro.');
    paginas('paginas-trabajos', datos, cargarTrabajos);
  }
  $('filtro-estado').addEventListener('change', () => cargarTrabajos(1));

  // ---------- Pagos ----------
  async function cargarPagos(pagina = 1) {
    const datos = await api(`/admin/pagos?${new URLSearchParams({ pagina })}`);
    tabla('tabla-pagos', [
      { titulo: 'Fecha', valor: (p) => fechaHora(p.fecha) },
      { titulo: 'Usuario', valor: (p) => p.email, envuelve: true },
      { titulo: 'Plan', valor: (p) => NOMBRE_PLAN[p.plan] || p.plan },
      { titulo: 'Monto', valor: (p) => dinero(p.monto, p.moneda), num: true },
      { titulo: 'Estado', valor: (p) => etiqueta(p.estado === 'pagado' ? 'Pagado' : 'Fallido', p.estado === 'pagado' ? 'bien' : 'mal') },
      { titulo: 'Transacción', valor: (p) => p.id_transaccion },
    ], datos.pagos, 'Todavía no hay pagos.');
    paginas('paginas-pagos', datos, cargarPagos);
  }

  // ---------- Base de datos ----------
  async function cargarBase(pagina = 1) {
    const select = $('base-tabla');
    if (!select.options.length) {
      const tablas = await api('/admin/base');
      select.replaceChildren(...tablas.map((t) => el('option', { value: t.nombre, textContent: `${t.nombre} (${numero(t.filas)})` })));
    }
    const datos = await api(`/admin/base/${encodeURIComponent(select.value)}?${new URLSearchParams({ pagina })}`);
    const columnas = datos.columnas.map((nombre, i) => ({
      titulo: nombre,
      valor: (f) => (f[i] === null ? '—' : typeof f[i] === 'boolean' ? (f[i] ? 'Sí' : 'No') : f[i]),
      num: typeof datos.filas[0]?.[i] === 'number',
    }));
    tabla('tabla-base', columnas, datos.filas, 'Tabla vacía.');
    paginas('paginas-base', datos, cargarBase);
  }
  $('base-tabla').addEventListener('change', () => cargarBase(1));

  const CARGAR = { resumen: cargarResumen, usuarios: cargarUsuarios, trabajos: cargarTrabajos, pagos: cargarPagos, base: cargarBase };

  // ---------- Inicio ----------
  (async () => {
    try {
      await cargarResumen();
      cargado.add('resumen');
      $('admin-panel').hidden = false;
    } catch (err) {
      if (err.status === 401) aviso('Inicia sesión con la cuenta de administrador para ver el panel.', { href: '/#login', texto: 'Iniciar sesión' });
      else if (err.status === 403) aviso('Esta página es solo para la cuenta de administrador.', { href: '/', texto: 'Volver a Splitter' });
      else aviso(err.message);
    }
  })();
})();
