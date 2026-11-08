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

  // ---------- Configuracion ----------
  function renderRequirements() {
    const box = $('file-requirements');
    if (!cfg) {
      box.textContent = configFailed ? 'No se pudo conectar con el servidor.' : 'Comprobando los requisitos…';
      return;
    }
    const formats = cfg.accepted_extensions.map((ext) => ext.replace('.', '').toUpperCase()).join(', ');
    const minutes = cfg.invitado.max_audio_minutes;
    const parts = [formats, `Hasta ${cfg.max_upload_mb} MB`, `Máximo ${minutes} ${minutes === 1 ? 'minuto' : 'minutos'}`];
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
    renderRequirements();
    updateAction();
  }

  // ---------- Formulario ----------
  function updateAction() {
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

  form.addEventListener('change', (event) => {
    if (event.target.name === 'mode') {
      mode = event.target.value;
      $('quality-options').hidden = mode !== 'instruments';
      renderTracks();
      updateAction();
    }
  });

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
    // El limite de un invitado sin cuenta viene de /api/config; el servidor lo vuelve a comprobar.
    const limit = cfg.invitado.max_audio_minutes;
    if (duration !== null && duration > limit * 60) {
      showError(`El audio supera los ${limit} ${limit === 1 ? 'minuto' : 'minutos'}. Elige un fragmento más corto.`);
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
      xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(event.loaded / event.total); };
      xhr.onload = () => {
        let body = null;
        try { body = JSON.parse(xhr.responseText); } catch { /* sin cuerpo JSON */ }
        if (xhr.status >= 200 && xhr.status < 300 && body) { resolve(body); return; }
        if (body && typeof body.detail === 'string') { reject(new Error(body.detail)); return; }
        const fallback = new Response(null, { status: xhr.status });
        errorDetail(fallback).then((message) => reject(new Error(message)));
      };
      xhr.onerror = () => reject(new Error('Se perdió la conexión al subir el archivo. Revisa tu internet e intenta de nuevo.'));
      xhr.onabort = () => reject(new Error('cancelado'));
      xhr.send(data);
      upload.xhr = xhr;
    });
  }

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
    if (currentJob) fetch(`/api/jobs/${currentJob.id}`, { method: 'DELETE', keepalive: true }).catch(() => {});
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
        const res = await fetch(`/api/jobs/${id}`);
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

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if ($('start-button').disabled) return;
    submitting = true;
    cancelled = false;
    updateAction();
    showError();
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
      if (!cancelled) { showView('form', { focus: false }); showError(error.message); }
      updateAction();
      return;
    }
    if (cancelled) { fetch(`/api/jobs/${job.id}`, { method: 'DELETE' }).catch(() => {}); return; }
    currentJob = job;
    handleUpdate(job);
    if (currentJob) follow(job.id);
  });

  $('job-cancel').addEventListener('click', () => {
    cancelled = true;
    upload.xhr?.abort();
    discardJob();
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
  const fillOf = (range) => range.style.setProperty('--fill', `${range.max > 0 ? (range.value / range.max) * 100 : 0}%`);

  function setPlaying(on) {
    playing = on;
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
    range.className = 'range';
    range.min = '0';
    range.max = '100';
    range.value = '100';
    range.setAttribute('aria-label', `Volumen de ${name}`);
    fillOf(range);
    const percent = document.createElement('span');
    percent.className = 'track-vol';
    percent.textContent = '100%';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary-button';
    button.textContent = 'Descargar';
    button.setAttribute('aria-label', `Descargar ${name}`);
    row.append(title, range, percent, button);

    const audio = new Audio();
    audio.preload = 'auto';
    audio.src = stem.preview_url;
    const track = { audio, volume: 1, gain: null, source: null };
    range.addEventListener('input', () => {
      setVolume(track, range.value / 100);
      percent.textContent = `${range.value}%`;
      fillOf(range);
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
  function showResults(job) {
    clearTracks();
    showResultsError('');
    for (const stem of job.stems) addTrack(stem);
    const mine = tracks;
    mine[0]?.audio.addEventListener('ended', () => { pauseAll(); seekAll(0); });
    $('player-status').textContent = 'Cargando pistas…';
    Promise.all(mine.map((track) => metadataReady(track.audio))).then(() => {
      if (tracks !== mine) return;   // ya se paso a otro audio
      const total = Math.max(...mine.map((track) => track.audio.duration || 0));
      seek.max = String(total);
      $('time-total').textContent = clock(total);
      $('play-all').disabled = false;
      seek.disabled = false;
      $('player-status').textContent = '';
    }, () => {
      if (tracks === mine) $('player-status').textContent = 'No se pudo cargar la vista previa. Puedes descargar las pistas igual.';
    });
    $('download-all').hidden = job.stems.length < 2;
    $('expires').textContent = job.expires_in_minutes
      ? `Tus archivos se borran automáticamente en ${job.expires_in_minutes} ${job.expires_in_minutes === 1 ? 'minuto' : 'minutos'}. Descárgalos antes.`
      : 'Tus archivos se borran automáticamente en pocos minutos. Descárgalos antes.';
    showView('results');
  }

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
    clearTracks();
    discardJob();
    clearFile();
    showView('form', { focus: false });
    window.scrollTo({ top: Math.max(0, $('flow-block').offsetTop - 88), behavior: reduced.matches ? 'auto' : 'smooth' });
  });

  // Al salir de la pagina: se corta el flujo, se silencia el audio y se borra el trabajo del servidor.
  window.addEventListener('pagehide', () => {
    clearTracks();
    discardJob();
  });

  renderRequirements();
  updateAction();
  loadConfig();
})();
