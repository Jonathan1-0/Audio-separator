// Formulario de Splitter conectado al backend (FastAPI, /api/...).
// Tres vistas en el mismo bloque: formulario, proceso (progreso real) y resultados (reproductor multipista + descargas).
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const form = $('splitter-form');
  const fileInput = $('audio-file');
  const dropzone = $('dropzone');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  // Etiquetas en espanol; los ids viajan en ingles al backend.
  const STEM_LABELS = { vocals: 'Voz', instrumental: 'Música sin voz', drums: 'Batería', bass: 'Bajo', other: 'Otros instrumentos', voice: 'Voz' };
  const stemLabel = (id) => STEM_LABELS[id] || id;
  // Pistas elegibles por modo (clean tiene una sola pista: no hay nada que elegir).
  const trackDefinitions = {
    vocals: ['vocals', 'instrumental'],
    instruments: ['vocals', 'drums', 'bass', 'other'],
  };
  const selectedTracks = Object.fromEntries(Object.entries(trackDefinitions).map(([key, ids]) => [key, new Set(ids)]));
  // El backend no conoce los modos de la pagina: se traducen a presets.
  function presetFor(mode) {
    if (mode === 'vocals') return '2stem';
    if (mode === 'instruments') return form.elements.quality.value === 'best' ? '4stem' : '4stem_fast';
    if (mode === 'clean') return 'denoise';
    return '';
  }

  let cfg = null;
  let configFailed = false;
  let mode = '';
  let audioFile = null;
  let validating = false;
  let submitting = false;
  let fileRevision = 0;
  let dragDepth = 0;

  // ---------- Cuenta (account.js) ----------
  // Con sesion se usan los limites del plan (GET /suscripcion); sin ella, los de invitado de /api/config.
  const sesion = () => window.getSesion?.() || null;
  const cuenta = () => sesion()?.cuenta || null;
  const auth = () => window.authHeaders?.() || {};
  const hasHistory = () => Boolean(cuenta()?.historial);
  const maxMinutes = () => cuenta()?.minutos_max_audio ?? cfg?.invitado.max_audio_minutes;
  const canBest = () => Boolean(cuenta()?.mejor_calidad);

  // ---------- Configuracion ----------
  function renderRequirements() {
    const box = $('file-requirements');
    if (!cfg) {
      box.textContent = configFailed ? 'No se pudo conectar con el servidor.' : 'Comprobando los requisitos…';
      return;
    }
    const formats = cfg.accepted_extensions.map((ext) => ext.replace('.', '').toUpperCase()).join(', ');
    const minutes = maxMinutes();
    const parts = [formats, `Hasta ${cfg.max_upload_mb} MB`, `Máximo ${minutes} ${minutes === 1 ? 'minuto' : 'minutos'}`];
    // Sin sesion: limite diario de invitados (si el servidor lo informa).
    const diarios = cfg.invitado?.max_jobs_per_day;
    if (!sesion() && diarios != null) parts.push(`${diarios} ${diarios === 1 ? 'audio' : 'audios'} al día sin cuenta`);
    box.replaceChildren();
    parts.forEach((text, index) => {
      if (index) { const dot = document.createElement('span'); dot.textContent = '·'; box.append(dot); }
      box.append(document.createTextNode(text));
    });
  }

  async function loadConfig() {
    try {
      const res = await fetch('/api/config');
      if (!res.ok) throw new Error(String(res.status));
      cfg = await res.json();
    } catch {
      configFailed = true;
      renderRequirements();
      updateAction();
      return;
    }
    fileInput.accept = cfg.accepted_extensions.join(',');
    const select = $('format');
    select.replaceChildren();
    for (const format of cfg.output_formats) {
      const option = document.createElement('option');
      option.value = format;
      option.textContent = format === 'mp3' ? 'MP3 (recomendado)' : format.toUpperCase();
      select.append(option);
    }
    select.value = cfg.output_formats.includes('mp3') ? 'mp3' : cfg.output_formats[0];
    buildFormatPicker();
    renderRequirements();
    updateAction();
  }

  // ---------- Desplegable del formato de descarga ----------
  // El <select id="format"> sigue siendo la fuente del valor (las descargas lo leen), pero queda oculto: encima va un
  // boton con flecha y una lista propia (MP3 con su etiqueta "Recomendado" y una palomita en el elegido).
  // Accesible: boton con aria-haspopup="listbox", lista role="listbox" con aria-activedescendant; flechas, Inicio/Fin,
  // Enter/Espacio para elegir, Escape o Tab para cerrar; un clic fuera la cierra.
  const CHECK = '<svg class="format-check" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  const CHEVRON = '<svg class="format-chevron" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M6 9l6 6 6-6"/></svg>';
  let formatPicker = null;
  function buildFormatPicker() {
    const select = $('format');
    document.querySelector('.format-picker-ghost')?.remove();   // el de muestra que se dibuja al recargar
    if (!formatPicker) {
      formatPicker = document.createElement('div');
      formatPicker.className = 'format-picker';
      formatPicker.innerHTML = `<button type="button" id="format-button" class="format-button" aria-haspopup="listbox" aria-expanded="false" aria-controls="format-list">
          <span class="format-current"></span>${CHEVRON}</button>
        <ul id="format-list" class="format-list" role="listbox" tabindex="-1" aria-label="Formato de descarga" hidden></ul>`;
      select.after(formatPicker);
      select.hidden = true;
      const button = formatPicker.querySelector('.format-button');
      // "Formato:" es solo texto (un clic en el no abre la lista); el boton lo toma como parte de su nombre accesible.
      button.setAttribute('aria-labelledby', 'format-label format-button');
      const list = formatPicker.querySelector('.format-list');
      const options = () => [...list.querySelectorAll('[role="option"]')];
      let active = -1;
      const setActive = (i) => {
        const all = options();
        if (!all.length) return;
        active = (i + all.length) % all.length;
        all.forEach((li, k) => li.classList.toggle('is-active', k === active));
        list.setAttribute('aria-activedescendant', all[active].id);
        all[active].scrollIntoView({ block: 'nearest' });
      };
      const open = () => {
        list.hidden = false;
        button.setAttribute('aria-expanded', 'true');
        setActive(Math.max(options().findIndex((li) => li.dataset.value === select.value), 0));
        list.focus();
      };
      const close = (focusButton = true) => {
        if (list.hidden) return;
        list.hidden = true;
        button.setAttribute('aria-expanded', 'false');
        if (focusButton) button.focus();
      };
      const choose = (li) => {
        if (!li) return;
        if (select.value !== li.dataset.value) {
          select.value = li.dataset.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
        }
        renderFormatPicker();
        close();
      };
      button.addEventListener('click', () => (list.hidden ? open() : close()));
      button.addEventListener('keydown', (event) => {
        if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) { event.preventDefault(); open(); }
      });
      list.addEventListener('keydown', (event) => {
        const keys = { ArrowDown: () => setActive(active + 1), ArrowUp: () => setActive(active - 1), Home: () => setActive(0), End: () => setActive(options().length - 1),
          Enter: () => choose(options()[active]), ' ': () => choose(options()[active]), Escape: () => close() };
        if (event.key === 'Tab') { close(false); return; }
        if (keys[event.key]) { event.preventDefault(); keys[event.key](); }
      });
      list.addEventListener('click', (event) => choose(event.target.closest('[role="option"]')));
      list.addEventListener('pointermove', (event) => {
        const li = event.target.closest('[role="option"]');
        if (li) setActive(options().indexOf(li));
      });
      document.addEventListener('pointerdown', (event) => { if (!formatPicker.contains(event.target)) close(false); });
    }
    const list = formatPicker.querySelector('.format-list');
    list.replaceChildren(...[...select.options].map((option) => {
      const li = document.createElement('li');
      li.id = `format-option-${option.value}`;
      li.className = 'format-option';
      li.setAttribute('role', 'option');
      li.dataset.value = option.value;
      const label = document.createElement('span');
      label.textContent = option.textContent;
      li.append(label);
      if (option.value === 'mp3') li.insertAdjacentHTML('beforeend', '<span class="format-badge">Recomendado</span>');
      li.insertAdjacentHTML('beforeend', CHECK);
      return li;
    }));
    renderFormatPicker();
  }
  function renderFormatPicker() {
    if (!formatPicker) return;
    const select = $('format');
    formatPicker.querySelector('.format-current').textContent = select.selectedOptions[0]?.textContent || '';
    try { sessionStorage.setItem('splitter-formato', formatPicker.querySelector('.format-current').textContent); } catch { /* sin almacenamiento */ }
    for (const li of formatPicker.querySelectorAll('[role="option"]')) li.setAttribute('aria-selected', String(li.dataset.value === select.value));
  }

  // ---------- Formulario ----------
  function updateAction() {
    // La fuente de verdad es la tarjeta marcada: si el modo guardado no coincide (restauracion del navegador,
    // vuelta atras, etc.) se toma el de la tarjeta, para no pedir "Elige qué quieres hacer" con una ya elegida.
    const checked = form.querySelector('input[name="mode"]:checked')?.value || '';
    if (checked && checked !== mode) {
      mode = checked;
      $('quality-options').hidden = mode !== 'instruments';
      renderTracks();
    }
    const noTracks = mode in selectedTracks && selectedTracks[mode].size === 0;
    $('action-label').textContent = mode === 'clean' ? 'Limpiar audio' : mode ? 'Separar' : 'Empezar';
    $('start-button').disabled = !cfg || !mode || !audioFile || validating || submitting || noTracks;
    $('action-hint').textContent = configFailed ? 'No hay conexión con el servidor. Recarga la página.'
      : !cfg ? 'Conectando con el servidor…'
      : !mode ? 'Elige qué quieres hacer.'
      : validating ? 'Comprobando tu archivo…'
      : !audioFile ? 'Sube un archivo de audio.'
      : noTracks ? 'Selecciona al menos una pista.'
      : 'Todo listo. Tu audio está preparado.';
  }

  // Las pastillas se montan una sola vez; al cambiar de modo solo se muestran u ocultan y se restaura su estado.
  const allTracks = [];
  for (const ids of Object.values(trackDefinitions)) for (const id of ids) if (!allTracks.includes(id)) allTracks.push(id);
  const trackChips = new Map();
  for (const value of allTracks) {
    const label = document.createElement('label');
    label.className = 'track-chip';
    label.hidden = true;
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.name = 'tracks';
    input.value = value;
    input.disabled = true;
    input.addEventListener('change', () => {
      if (input.checked) selectedTracks[mode].add(value);
      else selectedTracks[mode].delete(value);
      updateAction();
    });
    label.append(input, document.createTextNode(stemLabel(value)));
    $('track-options').append(label);
    trackChips.set(value, { label, input });
  }

  function renderTracks() {
    $('tracks-section').hidden = !(mode in trackDefinitions);
    const visible = new Set(trackDefinitions[mode] || []);
    for (const [value, { label, input }] of trackChips) {
      label.hidden = !visible.has(value);
      input.disabled = !visible.has(value);
      input.checked = visible.has(value) && selectedTracks[mode].has(value);
    }
  }

  // "Mejor calidad" es del plan Pro (el servidor tambien lo revisa).
  const bestInput = form.querySelector('input[name="quality"][value="best"]');
  const bestNote = bestInput.closest('label').querySelector('small');
  const bestText = bestNote.textContent;
  function renderQuality() {
    const allowed = canBest();
    bestInput.disabled = !allowed;
    bestNote.textContent = allowed ? bestText : 'Disponible con el plan Pro.';
    if (!allowed && bestInput.checked) form.querySelector('input[name="quality"][value="fast"]').checked = true;
  }

  function applyMode(value) {
    mode = value;
    $('quality-options').hidden = mode !== 'instruments';
    renderTracks();
    updateAction();
  }
  form.addEventListener('change', (event) => {
    if (event.target.name === 'mode') applyMode(event.target.value);
  });
  // Al recargar o volver atras, el navegador restaura la tarjeta marcada sin disparar "change": la opcion
  // se ve elegida pero el modo quedaba vacio y se pedia "Elige qué quieres hacer". Se lee la marcada.
  function syncMode() {
    const checked = form.querySelector('input[name="mode"]:checked')?.value || '';
    if (checked && checked !== mode) applyMode(checked);
  }
  addEventListener('load', syncMode);
  addEventListener('pageshow', syncMode);
  form.addEventListener('pointerdown', () => updateAction());
  form.addEventListener('focusin', () => updateAction());

  function showError(message = '') {
    $('file-error').textContent = message;
    $('file-error').hidden = !message;
    fileInput.setAttribute('aria-invalid', String(Boolean(message)));
  }

  function clearFile() {
    fileRevision++;
    audioFile = null;
    validating = false;
    fileInput.value = '';
    $('file-summary').hidden = true;
    $('upload-prompt').hidden = false;
    showError();
    updateAction();
  }

  function readDuration(file) {
    return new Promise((resolve) => {
      const audio = document.createElement('audio');
      const url = URL.createObjectURL(file);
      const timeout = setTimeout(() => finish(null), 8000);
      function finish(duration) {
        clearTimeout(timeout);
        audio.onloadedmetadata = null;
        audio.onerror = null;
        audio.removeAttribute('src');
        audio.load();
        URL.revokeObjectURL(url);
        resolve(duration);
      }
      audio.preload = 'metadata';
      audio.onloadedmetadata = () => finish(Number.isFinite(audio.duration) ? audio.duration : null);
      audio.onerror = () => finish(null);
      audio.src = url;
    });
  }

  const clock = (seconds) => {
    const total = Math.max(0, Math.floor(seconds || 0));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
  };

  async function selectFile(file) {
    clearFile();
    if (!file || !cfg) return;
    const ext = file.name.includes('.') ? `.${file.name.split('.').pop().toLowerCase()}` : '';
    if (!cfg.accepted_extensions.includes(ext)) {
      showError(`Ese tipo de archivo no se puede usar. Prueba con ${cfg.accepted_extensions.map((e) => e.slice(1).toUpperCase()).join(', ')}.`);
      return;
    }
    if (!file.size) { showError('El archivo está vacío. Elige otro audio.'); return; }
    if (file.size > cfg.max_upload_mb * 1024 * 1024) {
      showError(`El archivo pesa ${Math.ceil(file.size / 1024 / 1024)} MB y el máximo es ${cfg.max_upload_mb} MB.`);
      return;
    }
    const revision = fileRevision;
    validating = true;
    updateAction();
    const duration = await readDuration(file);
    if (revision !== fileRevision) return;
    validating = false;
    // El limite depende del plan (o de invitado); el servidor lo vuelve a comprobar.
    const limit = maxMinutes();
    if (duration !== null && duration > limit * 60) {
      const upsell = cuenta() && !hasHistory() ? ' Con el plan Pro puedes subir audios más largos.' : '';
      showError(`El audio supera los ${limit} ${limit === 1 ? 'minuto' : 'minutos'} de tu plan. Elige un fragmento más corto.${upsell}`);
      updateAction();
      return;
    }
    audioFile = file;
    $('file-name').textContent = file.name;
    const size = file.size < 1024 * 1024 ? `${Math.ceil(file.size / 1024)} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`;
    $('file-meta').textContent = `${size} · ${duration === null ? 'Duración no disponible' : `${clock(duration)} min`}`;
    $('upload-prompt').hidden = true;
    $('file-summary').hidden = false;
    updateAction();
  }

  fileInput.addEventListener('change', () => selectFile(fileInput.files[0]));
  $('remove-file').addEventListener('click', () => { clearFile(); fileInput.focus(); });
  dropzone.addEventListener('dragenter', (event) => { event.preventDefault(); dragDepth++; dropzone.classList.add('is-dragover'); });
  dropzone.addEventListener('dragover', (event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; });
  dropzone.addEventListener('dragleave', (event) => { event.preventDefault(); if (--dragDepth <= 0) { dragDepth = 0; dropzone.classList.remove('is-dragover'); } });
  dropzone.addEventListener('drop', (event) => {
    event.preventDefault();
    dragDepth = 0;
    dropzone.classList.remove('is-dragover');
    if (event.dataTransfer.files.length !== 1) { showError('Añade un solo archivo de audio a la vez.'); return; }
    selectFile(event.dataTransfer.files[0]);
  });
  // Evita que el navegador abra el archivo si se suelta fuera de la zona.
  for (const eventName of ['dragover', 'drop']) {
    window.addEventListener(eventName, (event) => {
      if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault();
    });
  }

  // ---------- Vistas ----------
  const panels = { form, job: $('job-panel'), results: $('results-panel') };
  function showView(name, { focus = true } = {}) {
    for (const [key, element] of Object.entries(panels)) element.hidden = key !== name;
    try { sessionStorage.setItem('splitter-vista', name); } catch { /* sin almacenamiento */ }   // la usa el <head> al recargar
    if (!focus) return;
    const title = name === 'job' ? $('job-title') : name === 'results' ? $('results-title') : null;
    if (title) { title.tabIndex = -1; title.focus({ preventScroll: true }); }
    const top = $('flow-block').getBoundingClientRect().top;
    if (top < 72 || top > innerHeight * 0.6) {
      window.scrollTo({ top: scrollY + top - 88, behavior: reduced.matches ? 'auto' : 'smooth' });
    }
  }

  // ---------- Errores del servidor ----------
  async function errorDetail(res) {
    try {
      const body = await res.json();
      if (typeof body.detail === 'string') return body.detail;
    } catch { /* sin cuerpo JSON */ }
    if (res.status === 413) return 'El archivo es demasiado grande.';
    if (res.status === 415) return 'Ese formato de audio no está soportado.';
    if (res.status === 429) return 'Se alcanzó el límite de trabajos por día. Intenta más tarde.';
    if (res.status === 503) return 'El servicio está muy ocupado. Intenta de nuevo en unos minutos.';
    if (res.status >= 500) return 'El servidor tuvo un problema. Intenta de nuevo en unos minutos.';
    return 'No se pudo completar la acción. Intenta de nuevo.';
  }

  // ---------- Crear el trabajo ----------
  function upload(data, onProgress) {
    // XMLHttpRequest y no fetch: fetch no informa del avance de la subida.
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/jobs');
      for (const [name, value] of Object.entries(auth())) xhr.setRequestHeader(name, value);
      xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(event.loaded / event.total); };
      xhr.onload = () => {
        let body = null;
        try { body = JSON.parse(xhr.responseText); } catch { /* sin cuerpo JSON */ }
        if (xhr.status >= 200 && xhr.status < 300 && body) { resolve(body); return; }
        if (xhr.status === 401) window.setSesion?.(null);   // la sesion vencio: se vuelve a pedir cuenta
        const fail = (message) => reject(Object.assign(new Error(message), { status: xhr.status }));
        if (body && typeof body.detail === 'string') { fail(body.detail); return; }
        const fallback = new Response(null, { status: xhr.status });
        errorDetail(fallback).then(fail);
      };
      xhr.onerror = () => reject(new Error('Se perdió la conexión al subir el archivo. Revisa tu internet e intenta de nuevo.'));
      xhr.onabort = () => reject(new Error('cancelado'));
      xhr.send(data);
      upload.xhr = xhr;
    });
  }

  // El id del trabajo se guarda por pestana para volver a el al recargar.
  const SAVED_JOB_KEY = 'splitter-trabajo';
  function saveJobId(id) { try { sessionStorage.setItem(SAVED_JOB_KEY, id); } catch { /* sin almacenamiento */ } }
  function forgetJobId() { try { sessionStorage.removeItem(SAVED_JOB_KEY); } catch { /* sin almacenamiento */ } }
  function savedJobId() { try { return sessionStorage.getItem(SAVED_JOB_KEY) || ''; } catch { return ''; } }

  let currentJob = null;   // ultimo trabajo creado en el servidor (para borrarlo)
  let events = null;       // EventSource
  let pollTimer = 0;
  let pollId = '';
  let cancelled = false;

  function stopFollowing() {
    events?.close();
    events = null;
    clearTimeout(pollTimer);
    pollTimer = 0;
    pollId = '';
  }

  function discardJob() {
    stopFollowing();
    // Con el plan Pro el trabajo se queda en "Mis audios"; sin el, se borra al pasar a otro o al salir.
    if (currentJob && !hasHistory()) fetch(`/api/jobs/${currentJob.id}`, { method: 'DELETE', keepalive: true, headers: auth() }).catch(() => {});
    currentJob = null;
  }

  // ---------- Estado del proceso ----------
  const bar = $('job-bar');
  function setBar(fraction) {
    const indeterminate = fraction == null;
    bar.classList.toggle('is-indeterminate', indeterminate);
    if (indeterminate) {
      bar.removeAttribute('aria-valuenow');
      bar.removeAttribute('aria-valuetext');
    } else {
      bar.style.setProperty('--p', String(Math.min(1, Math.max(0, fraction))));
      bar.setAttribute('aria-valuenow', String(Math.round(fraction * 100)));
    }
  }
  function setJobText(message, detail = '') {
    $('job-message').textContent = message;
    $('job-detail').textContent = detail;
  }
  const actionName = () => (mode === 'clean' ? 'Limpiando tu audio' : 'Separando tu audio');

  function renderJob(job) {
    $('job-title').textContent = mode === 'clean' ? 'Limpiando tu audio' : 'Separando tu audio';
    if (job.status === 'queued') {
      const position = job.queue_position || 0;
      setBar(null);
      setJobText('Esperando turno…', position > 0 ? `Posición en la cola: ${position}.` : 'Eres el siguiente.');
      return;
    }
    // processing
    const progress = typeof job.progress === 'number' ? job.progress : null;
    setBar(progress);
    const message = job.message || `${actionName()}…`;
    const percent = progress == null ? '' : ` ${Math.round(progress * 100)}%`;
    const details = [];
    if (job.phase === 'waiting_gpu') details.push('Esperando a que haya una GPU disponible.');
    if (job.queue_position > 0) details.push(`Posición en la cola: ${job.queue_position}.`);
    if (!details.length) details.push('Puedes dejar esta página abierta mientras termina.');
    setJobText(`${message}${percent}`, details.join(' '));
  }

  function failJob(message) {
    forgetJobId();
    stopFollowing();
    currentJob = null;
    submitting = false;
    showView('form', { focus: false });
    showError(message || 'No se pudo procesar el audio. Intenta de nuevo.');
    updateAction();
  }

  function handleUpdate(job) {
    if (!currentJob || job.id !== currentJob.id) return;
    if (job.status === 'done') { stopFollowing(); currentJob = job; submitting = false; showResults(job); return; }
    if (job.status === 'error') { failJob(job.error); return; }
    renderJob(job);
  }

  function poll(id) {
    // Respaldo cuando el SSE falla.
    async function tick() {
      if (pollId !== id) return;
      try {
        const res = await fetch(`/api/jobs/${id}`, { headers: auth() });
        if (res.status === 404) { failJob('Este trabajo ya no está disponible. Vuelve a subir el archivo.'); return; }
        if (res.ok) handleUpdate(await res.json());
      } catch { /* se reintenta */ }
      if (pollId === id) pollTimer = setTimeout(tick, 1500);
    }
    clearTimeout(pollTimer);
    pollId = id;
    pollTimer = setTimeout(tick, 1000);
  }

  function follow(id) {
    if (!('EventSource' in window)) { poll(id); return; }
    events = new EventSource(`/api/jobs/${id}/events`);
    events.addEventListener('update', (event) => { try { handleUpdate(JSON.parse(event.data)); } catch { /* dato ilegible */ } });
    events.addEventListener('gone', () => failJob('Este trabajo ya no está disponible. Vuelve a subir el archivo.'));
    events.onerror = () => {
      // Si el flujo se cierra, se sigue por polling.
      if (events && events.readyState === EventSource.CLOSED) { events = null; poll(id); }
    };
  }

  // ---------- Limite de separaciones del plan ----------
  // Ventana en lugar de un aviso chico: cuantas usaste, cuando se renuevan, "Ver planes" y "Volver".
  // Fecha de renovacion: la de la base de datos (GET /suscripcion -> cuenta.fin_periodo), la misma que usa el
  // servidor para devolver las separaciones. Se muestra en la hora local del equipo de quien la ve.
  function fechaLarga(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const mismoAnio = d.getFullYear() === new Date().getFullYear();
    return d.toLocaleDateString('es-MX', { day: 'numeric', month: 'long', ...(mismoAnio ? {} : { year: 'numeric' }) });
  }
  const sinSeparaciones = (c) => Boolean(c) && c.trabajos_usados >= c.trabajos_por_mes;
  let limitDialog = null;
  function showLimit(serverMessage = '') {
    if (!window.crearDialogoCuenta) { showError(serverMessage); return; }
    if (!limitDialog) {
      limitDialog = window.crearDialogoCuenta('limit-dialog');
      limitDialog.setAttribute('aria-labelledby', 'limit-title');
      limitDialog.setAttribute('aria-describedby', 'limit-text');
      // Arriba y al centro: el logo de la barra (sus barras se mueven despacio, styles.css) y el nombre.
      limitDialog.innerHTML = `<div class="limit-brand" aria-hidden="true">
          <svg class="limit-logo" viewBox="36 30 115 112" focusable="false"><rect x="36" y="72" width="11" height="27" rx="5.5"/><rect x="53" y="51" width="11" height="69" rx="5.5"/><rect x="71" y="30" width="11" height="112" rx="5.5"/><rect x="105" y="30" width="11" height="112" rx="5.5"/><rect x="123" y="51" width="11" height="69" rx="5.5"/><rect x="140" y="72" width="11" height="27" rx="5.5"/></svg>
          <span class="limit-word">Splitter</span>
        </div>
        <h2 id="limit-title"></h2><p id="limit-text"></p>
        <div class="wall-actions">
          <a id="limit-plans" class="primary-button" href="planes.html">Ver planes</a>
          <button type="button" class="back-button" data-cerrar>
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>Volver
          </button>
        </div>`;
    }
    const sesion = window.getSesion?.();
    const c = sesion?.cuenta;
    const titulo = $('limit-title');
    const texto = $('limit-text');
    if (c && sinSeparaciones(c)) {
      const total = c.trabajos_por_mes;
      titulo.textContent = `Ya usaste tus ${total} ${total === 1 ? 'separación' : 'separaciones'} de este periodo`;
      const fecha = c.fin_periodo ? fechaLarga(c.fin_periodo) : '';
      texto.textContent = fecha ? `Se renuevan el ${fecha}.` : 'Se renuevan al empezar tu siguiente periodo.';
    } else {
      // Sin cuenta (limite por conexion) o sin datos de la cuenta: se usa lo que dijo el servidor.
      titulo.textContent = 'Llegaste al límite de separaciones';
      texto.textContent = serverMessage || 'Por ahora no puedes separar más audios.';
    }
    $('limit-plans').hidden = sesion?.plan === 'pro' || sesion?.plan === 'admin';   // con Pro o admin no hay plan mayor que ofrecer
    if (!limitDialog.open) limitDialog.showModal();
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if ($('start-button').disabled) return;
    // Si la cuenta ya no tiene separaciones, se avisa sin subir nada ni mover la pagina.
    if (sinSeparaciones(window.getSesion?.()?.cuenta)) {
      await window.refrescarCuenta?.();   // por si el periodo ya se renovo
      if (sinSeparaciones(window.getSesion?.()?.cuenta)) { showLimit(); return; }
    }
    const scrollAntes = scrollY;
    submitting = true;
    cancelled = false;
    updateAction();
    showError();
    forgetJobId();
    discardJob();
    const data = new FormData();
    data.append('file', audioFile);
    data.append('preset', presetFor(mode));
    // Solo las pistas elegibles viajan; las modos de una sola pista (clean) mandan vacio = todas.
    data.append('stems', mode in selectedTracks ? [...selectedTracks[mode]].join(',') : '');
    $('job-file').textContent = audioFile.name;
    $('job-title').textContent = 'Subiendo tu audio';
    setBar(0);
    setJobText('Subiendo tu archivo…');
    showView('job');
    let job;
    try {
      job = await upload(data, (fraction) => {
        setBar(fraction);
        setJobText(`Subiendo tu archivo… ${Math.round(fraction * 100)}%`);
      });
    } catch (error) {
      submitting = false;
      if (!cancelled && error.status === 429) {
        // Limite alcanzado: se vuelve a donde estaba el usuario (sin el salto hacia arriba) y se abre la ventana.
        showView('form', { focus: false });
        setTimeout(() => window.scrollTo({ top: scrollAntes, behavior: 'instant' }), 0);
        await window.refrescarCuenta?.();
        showLimit(error.message);
      } else if (!cancelled) {
        showView('form', { focus: false });
        showError(error.message);
        // showView('job') subio la pagina al inicio del bloque ("¿Qué quieres hacer?"): sin esto el error quedaba
        // fuera de la vista y parecia que se pedia volver a elegir. Se lleva al usuario al mensaje.
        // Salto inmediato y en el siguiente frame: asi cancela el desplazamiento suave que inicio showView('job').
        setTimeout(() => $('file-error').scrollIntoView({ behavior: 'instant', block: 'center' }), 0);
      }
      updateAction();
      return;
    }
    if (cancelled) { fetch(`/api/jobs/${job.id}`, { method: 'DELETE', headers: auth() }).catch(() => {}); return; }
    window.refrescarCuenta?.();   // el trabajo ya cuenta en el consumo del periodo
    currentJob = job;
    saveJobId(job.id);
    handleUpdate(job);
    if (currentJob) follow(job.id);
  });

  $('job-cancel').addEventListener('click', () => {
    cancelled = true;
    forgetJobId();
    upload.xhr?.abort();
    // Cancelar si borra el trabajo, tambien en Pro (el servidor lo marca como cancelado).
    stopFollowing();
    if (currentJob) fetch(`/api/jobs/${currentJob.id}`, { method: 'DELETE', headers: auth() }).catch(() => {});
    currentJob = null;
    submitting = false;
    showView('form', { focus: false });
    updateAction();
  });

  // ---------- Reproductor multipista ----------
  // Cada pista es su propio <audio> y suenan todas a la vez. El volumen va por Web Audio porque en iPhone `audio.volume` no se puede cambiar.
  const PLAY_ICON = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M8 5v14l11-7z" fill="currentColor"/></svg>';
  const PAUSE_ICON = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" fill="currentColor"/></svg>';
  let actx = null;
  let tracks = [];
  let playing = false;
  let syncTimer = 0;
  let dragging = false;
  const seek = $('seek');
  const glassRefresh = new WeakMap();   // input -> repintar su pastilla de vidrio (cambios de valor por codigo)
  const fillOf = (range) => {
    range.style.setProperty('--fill', `${range.max > 0 ? (range.value / range.max) * 100 : 0}%`);
    glassRefresh.get(range)?.();
  };

  // Deslizador de volumen con pastilla de vidrio liquido (al arrastrar). El <input type="range"> nativo sigue
  // encima, invisible: da el arrastre (raton, dedo), el teclado y la accesibilidad. Lo visible solo se mueve con
  // transform (sin left/width: no recalcula el layout), como mucho una vez por cuadro; el filtro del vidrio
  // (backdrop-filter) solo existe mientras se arrastra (.is-active).
  function glassRange(input) {
    const wrap = document.createElement('div');
    wrap.className = 'glass-range';
    wrap.innerHTML = `<span class="glass-range-track" aria-hidden="true"><span class="glass-range-fill"></span></span>
      <span class="glass-range-thumb" aria-hidden="true"><span class="glass-range-knob">
        <span class="glass-range-lens"></span><span class="glass-range-tint"></span><span class="glass-range-shine"></span>
      </span></span>`;
    input.classList.add('glass-range-input');
    input.classList.remove('range');   // sus estilos de barra nativa chocarian con los del vidrio
    if (input.parentNode) input.replaceWith(wrap);   // un input que ya esta en la pagina (#seek) se envuelve en su sitio
    wrap.append(input);
    const fill = wrap.querySelector('.glass-range-fill');
    const thumb = wrap.querySelector('.glass-range-thumb');
    let width = 0;
    let thumbWidth = 0;
    let frame = 0;
    function paint() {
      frame = 0;
      const min = Number(input.min) || 0;
      const span = (Number(input.max) || 100) - min;
      const p = span > 0 ? Math.min(Math.max((Number(input.value) - min) / span, 0), 1) : 0;
      // Mismo reparto que el input nativo: el centro de la pastilla recorre de tw/2 a ancho - tw/2.
      const x = p * Math.max(width - thumbWidth, 0);
      thumb.style.transform = `translate3d(${x}px, -50%, 0)`;
      const filled = width ? (x + thumbWidth / 2) / width : 0;
      fill.style.transform = `translate3d(${(filled - 1) * 100}%, 0, 0)`;
    }
    const schedule = () => { if (!frame) frame = requestAnimationFrame(paint); };
    if ('ResizeObserver' in window) new ResizeObserver(() => { width = wrap.clientWidth; thumbWidth = thumb.offsetWidth; paint(); }).observe(wrap);
    input.addEventListener('input', schedule);
    glassRefresh.set(input, schedule);
    const release = () => wrap.classList.remove('is-active');
    input.addEventListener('pointerdown', () => {
      wrap.classList.add('is-active');
      document.addEventListener('pointerup', release, { once: true });
      document.addEventListener('pointercancel', release, { once: true });
    });
    input.addEventListener('blur', release);
    requestAnimationFrame(() => { width = wrap.clientWidth; thumbWidth = thumb.offsetWidth; paint(); });
    return wrap;
  }
  // La barra de reproduccion usa la misma pastilla de vidrio que el volumen; se sigue pudiendo arrastrar para saltar.
  const seekWrap = glassRange(seek);
  seekWrap.classList.add('glass-range-seek');

  function setPlaying(on) {
    playing = on;
    // Mientras suena, la pastilla de la barra se desliza entre las actualizaciones (cada 250 ms) en vez de saltar.
    seekWrap.classList.toggle('is-playing', on);
    $('play-all').innerHTML = on ? PAUSE_ICON : PLAY_ICON;
    $('play-all').setAttribute('aria-label', on ? 'Pausar' : 'Reproducir');
    clearInterval(syncTimer);
    syncTimer = on ? setInterval(sync, 250) : 0;
  }

  function connectAudio() {
    // Se crea en el primer play: los navegadores no dejan sonar nada antes de un clic.
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return;
    if (!actx) actx = new Context();
    for (const track of tracks) {
      if (track.gain) continue;
      track.source = actx.createMediaElementSource(track.audio);
      track.gain = actx.createGain();
      track.gain.gain.value = track.volume;
      track.source.connect(track.gain).connect(actx.destination);
    }
    if (actx.state === 'suspended') actx.resume();
  }

  function setVolume(track, value) {
    track.volume = value;
    if (track.gain) track.gain.gain.value = value;
    else track.audio.volume = value;
  }

  async function playAll() {
    if (!tracks.length) return;
    connectAudio();
    const at = tracks[0].audio.currentTime;
    for (const track of tracks) if (Math.abs(track.audio.currentTime - at) > 0.01) track.audio.currentTime = at;
    setPlaying(true);
    try {
      await Promise.all(tracks.map((track) => track.audio.play()));
      $('player-status').textContent = '';
    } catch (error) {
      // AbortError: se pauso antes de arrancar (el usuario, o mientras otra pista carga).
      if (error && error.name === 'AbortError') return;
      pauseAll();
      $('player-status').textContent = 'No se pudo reproducir. Intenta de nuevo.';
    }
  }

  function pauseAll() { for (const track of tracks) track.audio.pause(); setPlaying(false); }

  function showTime(seconds) {
    $('time-now').textContent = clock(seconds);
    if (!dragging) { seek.value = seconds; fillOf(seek); }
  }

  function seekAll(seconds) { for (const track of tracks) track.audio.currentTime = seconds; showTime(seconds); }

  function sync() {
    // Cada pista lleva su propio reloj: la que se desfasa se alinea con la primera.
    if (!tracks.length) return;
    const lead = tracks[0].audio;
    for (const track of tracks.slice(1)) {
      if (!track.audio.paused && Math.abs(track.audio.currentTime - lead.currentTime) > 0.08) track.audio.currentTime = lead.currentTime;
    }
    showTime(lead.currentTime);
  }

  function addTrack(stem) {
    const name = stemLabel(stem.name);
    const row = document.createElement('li');
    row.className = 'track-row';
    const title = document.createElement('strong');
    title.textContent = name;
    const range = document.createElement('input');
    range.type = 'range';
    range.min = '0';
    range.max = '100';
    range.value = '100';
    range.setAttribute('aria-label', `Volumen de ${name}`);
    const slider = glassRange(range);
    const percent = document.createElement('span');
    percent.className = 'track-vol';
    percent.textContent = '100%';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary-button';
    button.textContent = 'Descargar';
    button.setAttribute('aria-label', `Descargar ${name}`);
    row.append(title, slider, percent, button);

    const audio = new Audio();
    audio.preload = 'auto';
    audio.src = stem.preview_url;
    const track = { audio, volume: 1, gain: null, source: null };
    range.addEventListener('input', () => {
      setVolume(track, range.value / 100);
      percent.textContent = `${range.value}%`;
    });
    button.addEventListener('click', () => prepareDownload(button, stem.download_url));
    // Si una pista se queda cargando, las demas la esperan; al volver se igualan a su tiempo.
    audio.addEventListener('waiting', () => { if (playing) for (const other of tracks) if (other !== track) other.audio.pause(); });
    audio.addEventListener('playing', () => {
      if (!playing) return;
      for (const other of tracks) {
        if (other.audio.paused) { other.audio.currentTime = audio.currentTime; other.audio.play().catch(() => {}); }
      }
    });
    tracks.push(track);
    $('track-list').append(row);
    return track;
  }

  function metadataReady(audio) {
    return new Promise((resolve, reject) => {
      if (audio.readyState >= 1) { resolve(); return; }
      audio.addEventListener('loadedmetadata', resolve, { once: true });
      audio.addEventListener('error', reject, { once: true });
    });
  }

  function clearTracks() {
    // Un audio que ya no se ve sigue sonando si no se detiene y se le quita la fuente.
    setPlaying(false);
    for (const track of tracks) {
      track.audio.pause();
      track.source?.disconnect();
      track.gain?.disconnect();
      track.audio.removeAttribute('src');
      track.audio.load();
    }
    tracks = [];
    $('track-list').replaceChildren();
    seek.max = '0';
    seek.value = '0';
    fillOf(seek);
    $('time-now').textContent = '0:00';
    $('time-total').textContent = '0:00';
    $('play-all').disabled = true;
    seek.disabled = true;
  }

  $('play-all').addEventListener('click', () => (playing ? pauseAll() : playAll()));
  seek.addEventListener('pointerdown', () => { dragging = true; });
  seek.addEventListener('input', () => { $('time-now').textContent = clock(Number(seek.value)); fillOf(seek); });
  seek.addEventListener('change', () => { dragging = false; seekAll(Number(seek.value)); });

  // ---------- Resultados ----------
  let previewReady = Promise.resolve(false);
  function showResults(job) {
    clearTracks();
    showResultsError('');
    for (const stem of job.stems) addTrack(stem);
    // Nombres de las pistas para dibujarlas al instante si se recarga la pagina (final de index.html).
    try { sessionStorage.setItem('splitter-pistas', JSON.stringify(job.stems.map((stem) => stemLabel(stem.name)))); } catch { /* sin almacenamiento */ }
    const mine = tracks;
    mine[0]?.audio.addEventListener('ended', () => { pauseAll(); seekAll(0); });
    // Al recargar no se muestra: la linea aparecia y desaparecia, moviendo las pistas.
    $('player-status').textContent = document.documentElement.classList.contains('is-restoring') ? '' : 'Cargando pistas…';
    // true si las pistas se pueden escuchar; lo espera la restauracion al recargar.
    previewReady = Promise.all(mine.map((track) => metadataReady(track.audio))).then(() => {
      if (tracks !== mine) return false;   // ya se paso a otro audio
      const total = Math.max(...mine.map((track) => track.audio.duration || 0));
      seek.max = String(total);
      fillOf(seek);
      $('time-total').textContent = clock(total);
      try { sessionStorage.setItem('splitter-duracion', clock(total)); } catch { /* sin almacenamiento */ }
      $('play-all').disabled = false;
      seek.disabled = false;
      $('player-status').textContent = '';
      return true;
    }, () => {
      if (tracks === mine) $('player-status').textContent = 'No se pudo cargar la vista previa. Puedes descargar las pistas igual.';
      return false;
    });
    $('download-all').hidden = job.stems.length < 2;
    $('expires').textContent = expiresText(job);
    showView('results');
  }

  function expiresText(job) {
    const minutes = job.expires_at ? Math.max(0, Math.round((new Date(job.expires_at) - Date.now()) / 60000)) : job.expires_in_minutes;
    // Pro: una semana y quedan en "Mis audios". Gratis e invitados: 1 hora.
    if (minutes > 120 && job.expires_at) {
      const date = new Date(job.expires_at).toLocaleDateString('es-MX', { day: 'numeric', month: 'long' });
      return hasHistory()
        ? `Tus archivos se guardan hasta el ${date} y también los encuentras en Mis audios.`
        : `Tus archivos se guardan hasta el ${date}. Descárgalos antes.`;
    }
    let text = minutes
      ? `Tus archivos se borran automáticamente en ${minutes} ${minutes === 1 ? 'minuto' : 'minutos'}. Descárgalos antes.`
      : 'Tus archivos se borran automáticamente en pocos minutos. Descárgalos antes.';
    if (cuenta() && !hasHistory()) text += ' Con el plan Pro se guardan una semana y quedan en tu historial.';
    // Con cuenta gratis que ya ve "Mis audios" (el servidor lo habilita): mientras duran, tambien estan ahi.
    else if (cuenta() && cuenta().plan === 'gratis') text = text.replace(' Descárgalos antes.', ' Mientras tanto también los encuentras en Mis audios. Con Pro se guardan una semana.');
    return text;
  }

  // "Mis audios" (account.js) abre aqui un trabajo guardado. Devuelve false si ya no esta disponible.
  window.abrirTrabajo = async (id) => {
    let job;
    try {
      const res = await fetch(`/api/jobs/${id}`, { headers: auth() });
      if (!res.ok) return false;
      job = await res.json();
    } catch { return false; }
    if (job.status === 'error') return false;
    upload.xhr?.abort();
    clearTracks();
    discardJob();
    submitting = false;
    currentJob = job;
    saveJobId(job.id);
    mode = job.preset === 'denoise' ? 'clean' : job.preset === '2stem' ? 'vocals' : 'instruments';
    $('job-file').textContent = job.filename;
    handleUpdate(job);
    if (currentJob && job.status !== 'done') { showView('job'); follow(job.id); }
    return true;
  };

  function showResultsError(message) {
    $('results-error').textContent = message || '';
    $('results-error').hidden = !message;
  }

  // Descarga en dos pasos: el servidor convierte el formato la primera vez (puede tardar).
  async function prepareDownload(button, baseUrl) {
    if (button.getAttribute('aria-disabled') === 'true') return;
    const url = `${baseUrl}?format=${encodeURIComponent($('format').value)}`;
    const label = button.textContent;
    button.textContent = 'Preparando…';
    button.setAttribute('aria-disabled', 'true');
    showResultsError('');
    try {
      const res = await fetch(`${url}&prepare=1`);
      if (!res.ok) throw new Error(await errorDetail(res));
      const body = await res.json();
      if (!body.ready) throw new Error('No se pudo preparar la descarga. Intenta de nuevo.');
      const link = document.createElement('a');
      link.href = url;
      link.download = '';
      document.body.append(link);
      link.click();
      link.remove();
    } catch (error) {
      showResultsError(error instanceof TypeError ? 'Se perdió la conexión con el servidor. Intenta de nuevo.' : error.message);
    } finally {
      button.textContent = label;
      button.removeAttribute('aria-disabled');
    }
  }
  $('download-all').addEventListener('click', () => { if (currentJob) prepareDownload($('download-all'), currentJob.download_all_url); });

  $('again').addEventListener('click', () => {
    forgetJobId();
    clearTracks();
    discardJob();
    clearFile();
    showView('form', { focus: false });
    window.scrollTo({ top: Math.max(0, $('flow-block').offsetTop - 88), behavior: reduced.matches ? 'auto' : 'smooth' });
  });

  // El logo siempre lleva al inicio, desde donde sea: deja el trabajo actual (como "Procesar otro audio"),
  // corta una subida en curso y sube al principio de la pagina. Recargar, en cambio, si vuelve al trabajo.
  document.querySelector('.site-header .brand')?.addEventListener('click', (event) => {
    event.preventDefault();
    if (submitting) { cancelled = true; upload.xhr?.abort(); }
    forgetJobId();
    clearTracks();
    discardJob();
    clearFile();
    submitting = false;
    showView('form', { focus: false });
    updateAction();
    if (location.hash) history.replaceState(null, '', location.pathname + location.search);
    window.scrollTo({ top: 0, behavior: reduced.matches ? 'auto' : 'smooth' });
  });

  // "Mis audios" (account.js) borro este trabajo en el servidor: la pagina vuelve al inicio sin otro DELETE.
  window.olvidarTrabajo = (id) => {
    if (!id || (currentJob?.id !== id && savedJobId() !== id)) return;
    forgetJobId();
    clearTracks();
    stopFollowing();
    currentJob = null;
    clearFile();
    submitting = false;
    showView('form', { focus: false });
    updateAction();
  };

  // Al salir o recargar: se corta el flujo y se silencia el audio. El trabajo NO se borra: el servidor
  // borra los archivos solo al vencer (1 hora en Gratis/invitados, 7 dias en Pro/admin).
  window.addEventListener('pagehide', () => {
    clearTracks();
    stopFollowing();
  });

  // Al iniciar o cerrar sesion, o al cambiar de plan, cambian los limites que se muestran.
  window.onSesion?.(() => { renderQuality(); renderRequirements(); });
  renderRequirements();
  updateAction();
  syncMode();
  loadConfig();

  // Al recargar con un trabajo en curso o con resultados, se vuelve a ese punto.
  // El <head> ya muestra el panel guardado (html.is-restoring + data-restore) y el final del <body> coloca el scroll,
  // asi que nunca se ve el inicio ni una pantalla vacia. Aqui, en cuanto el servidor responde (una sola peticion),
  // se llena el panel y su contenido aparece. No se espera a que carguen las pistas ni el resto de la pagina.
  // La entrada suave del panel (html.restore-in) es solo para la recarga: al terminar se quita para que no se repita.
  document.addEventListener('animationend', (event) => {
    if (event.animationName === 'panel-in') document.documentElement.classList.remove('restore-in');
  });
  const reveal = () => { document.documentElement.classList.remove('is-restoring'); delete document.documentElement.dataset.restore; };
  const jumpToFlow = () => {
    const top = $('flow-block').getBoundingClientRect().top + scrollY - 88;
    window.scrollTo({ top: Math.max(0, top), behavior: 'instant' });
    return Math.round(scrollY);
  };
  function backHome() {
    forgetJobId();
    clearTracks();
    stopFollowing();
    currentJob = null;
    showView('form', { focus: false });
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  (async () => {
    // Llegada desde el logo de otra pagina (index.html#inicio): siempre al inicio.
    if (location.hash === '#inicio') { forgetJobId(); history.replaceState(null, '', location.pathname + location.search); }
    const id = /#(restablecer|sesion|error)=/.test(location.hash) ? '' : savedJobId();   // esos hash los manejan otros scripts
    if (!id) { reveal(); return; }
    const safety = setTimeout(reveal, 2500);   // nunca dejar el contenido oculto
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';   // si no, el navegador pisa el scroll
    const ok = await window.abrirTrabajo(id);
    if (!ok) { forgetJobId(); window.scrollTo({ top: 0, behavior: 'instant' }); }   // ya no existe: al inicio
    const placed = ok ? jumpToFlow() : 0;
    clearTimeout(safety);
    requestAnimationFrame(reveal);
    if (!ok) return;
    // Si al terminar de cargar la pagina cambio de alto (fuentes, imagenes), se corrige sin animar, salvo que la
    // persona ya se haya movido.
    const fix = () => { if (Math.round(scrollY) === placed) jumpToFlow(); };
    if (document.readyState === 'complete') fix(); else addEventListener('load', fix, { once: true });
    // Pistas que ya no se pueden escuchar (vencieron o el servidor se reinicio): no se deja un reproductor roto.
    if (!panels.results.hidden && !(await previewReady) && currentJob?.id === id) backHome();
  })();
})();
