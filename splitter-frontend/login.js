// UI only. Authentication will be connected in a later integration.
// Motion is optional: if the CDN is unreachable the modal still works, without animation.
const MOTION_URL = 'https://cdn.jsdelivr.net/npm/motion@14.9.0/+esm';
const EASE = [0.22, 1, 0.36, 1];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let motion = null;
import(MOTION_URL).then((module) => { motion = module; }).catch(() => {});
const canAnimate = () => motion !== null && !reduced.matches;

const $ = (id) => document.getElementById(id);
const dialog = $('login-dialog');
const scrim = $('login-scrim');
const panel = $('login-panel');
const form = $('login-form');
const email = $('login-email');
const password = $('login-password');
const confirm = $('login-confirm');
const message = $('login-message');
const modes = {
  login: { title: 'Inicia sesión', lead: 'Guarda tus separaciones y vuelve a ellas cuando quieras.', submit: 'Iniciar sesión', switchText: '¿No tienes cuenta?', switchLink: 'Crear cuenta', next: 'register', autocomplete: 'current-password' },
  register: { title: 'Crea tu cuenta', lead: 'Gratis. Solo necesitas un correo y una contraseña.', submit: 'Crear cuenta', switchText: '¿Ya tienes cuenta?', switchLink: 'Inicia sesión', next: 'login', autocomplete: 'new-password' },
  reset: { title: 'Recupera tu acceso', lead: 'Escribe tu correo y te enviaremos un enlace para elegir otra contraseña.', submit: 'Enviar enlace', switchText: '¿Ya la recuerdas?', switchLink: 'Volver a iniciar sesión', next: 'login' },
};
let mode = 'login';
let opener = null;
let closing = false;
let flip = null;

// Direct children of the form that are visible, minus the close button.
const contentItems = () => [...form.children].filter((el) => el.id !== 'login-close' && !el.hidden);
const clearInline = (...elements) => elements.forEach((el) => { el.style.removeProperty('opacity'); el.style.removeProperty('transform'); });
const enter = (targets, from, delay) => motion.animate(targets, { opacity: [0, 1], y: [from, 0] }, { duration: 0.3, ease: EASE, delay }).finished.then(() => clearInline(...[].concat(targets)));

function setMessage(text = '') {
  message.textContent = text;
  message.hidden = !text;
}

function setMode(next) {
  mode = next;
  const m = modes[next];
  $('login-title').textContent = m.title;
  $('login-lead').textContent = m.lead;
  $('login-submit').textContent = m.submit;
  $('switch-text').textContent = m.switchText;
  $('switch-link').textContent = m.switchLink;
  $('switch-link').dataset.modeTarget = m.next;
  $('password-fields').hidden = next === 'reset';
  $('confirm-field').hidden = next !== 'register';
  $('forgot-link').hidden = next !== 'login';
  $('social-auth').hidden = next === 'reset';
  if (m.autocomplete) password.autocomplete = m.autocomplete;
  password.required = next !== 'reset';
  confirm.required = next === 'register';
  setMessage();
}

function endFlip() {
  flip?.stop();
  flip = null;
  panel.style.removeProperty('transform');
  panel.style.removeProperty('overflow');
  form.style.removeProperty('transform');
}

// Height changes are animated with transform only: the panel is scaled from its old
// height to its new one while the form is counter-scaled, so text is never stretched.
function morph(change, fadeIn) {
  if (!canAnimate()) { change(); return; }
  endFlip();
  const before = panel.offsetHeight;
  change();
  const after = panel.offsetHeight;
  const targets = fadeIn();
  if (targets.length) enter(targets, 8, motion.stagger(0.06));
  if (before === after) return;
  const ratio = before / after;
  const apply = (progress) => {
    const scale = ratio + (1 - ratio) * progress;
    panel.style.transform = `scaleY(${scale})`;
    form.style.transform = `scaleY(${1 / scale})`;
  };
  panel.style.overflow = 'hidden';
  apply(0);
  flip = motion.animate(0, 1, { duration: 0.3, ease: EASE, onUpdate: apply, onComplete: endFlip });
}

const showMessage = (text) => morph(() => setMessage(text), () => (text ? [message] : []));
const switchMode = (next) => morph(() => setMode(next), () => contentItems().filter((el) => !el.classList.contains('login-brand')));

function openDialog(trigger) {
  opener = trigger;
  setMode('login');
  dialog.showModal();
  email.focus();
  if (!canAnimate()) return;
  const items = contentItems();
  motion.animate(scrim, { opacity: [0, 1] }, { duration: 0.2, ease: EASE }).finished.then(() => clearInline(scrim));
  motion.animate(panel, { opacity: [0, 1], y: [16, 0] }, { duration: 0.3, ease: EASE }).finished.then(() => clearInline(panel));
  enter(items, 12, motion.stagger(0.06, { startDelay: 0.1 }));
}

async function requestClose() {
  if (closing || !dialog.open) return;
  closing = true;
  endFlip();
  if (canAnimate()) {
    const exit = Promise.all([
      motion.animate(scrim, { opacity: [1, 0] }, { duration: 0.2, ease: EASE }).finished,
      motion.animate(panel, { opacity: [1, 0], y: [0, 8] }, { duration: 0.2, ease: EASE }).finished,
    ]);
    // A page that is not painting (background tab) never finishes its animations.
    await Promise.race([exit, new Promise((resolve) => setTimeout(resolve, 400))]);
  }
  dialog.close();
  clearInline(scrim, panel, ...contentItems());
  closing = false;
}

document.querySelectorAll('[data-open-login]').forEach((button) => {
  button.addEventListener('click', () => openDialog(button));
});
form.addEventListener('click', (event) => {
  const provider = event.target.closest('[data-provider]');
  if (provider) {
    // No fabricated session: the provider flow will be connected in a later integration.
    const name = provider.querySelector('.social-name').textContent;
    showMessage(`Vista previa: el acceso con ${name} estará disponible próximamente.`);
    return;
  }
  const target = event.target.closest('[data-mode-target]');
  if (!target) return;
  switchMode(target.dataset.modeTarget);
  email.focus();
});
$('login-close').addEventListener('click', requestClose);
// Escape runs the exit animation instead of closing the dialog abruptly.
dialog.addEventListener('cancel', (event) => { event.preventDefault(); requestClose(); });
dialog.addEventListener('close', () => {
  form.reset();
  setMode('login');
  endFlip();
  opener?.focus();
});

// Only close on the backdrop when the press also started there, not when a text
// selection drag from an input ends outside the panel.
let pressedBackdrop = false;
const isBackdrop = (target) => target === dialog || target === scrim;
dialog.addEventListener('pointerdown', (event) => { pressedBackdrop = isBackdrop(event.target); });
dialog.addEventListener('click', (event) => {
  if (pressedBackdrop && isBackdrop(event.target)) requestClose();
  pressedBackdrop = false;
});

// Keep Tab inside the dialog.
dialog.addEventListener('keydown', (event) => {
  if (event.key !== 'Tab') return;
  const focusable = [...dialog.querySelectorAll('button, input, a[href]')].filter((el) => !el.disabled && el.getClientRects().length > 0);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !dialog.contains(active))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (active === last || !dialog.contains(active))) { event.preventDefault(); first.focus(); }
});

form.addEventListener('submit', (event) => {
  event.preventDefault();
  if (!email.value.trim() || !email.validity.valid) {
    showMessage('Escribe un correo electrónico válido.');
    email.focus();
    return;
  }
  if (mode !== 'reset' && !password.value) {
    showMessage('Escribe tu contraseña.');
    password.focus();
    return;
  }
  if (mode === 'register') {
    if (password.value.length < 8) {
      showMessage('La contraseña debe tener al menos 8 caracteres.');
      password.focus();
      return;
    }
    if (confirm.value !== password.value) {
      showMessage('Las contraseñas no coinciden.');
      confirm.focus();
      return;
    }
  }
  // No fabricated session or email: this phase only implements the interface.
  showMessage(mode === 'login' ? 'Vista previa: el inicio de sesión estará disponible próximamente.'
    : mode === 'register' ? 'Vista previa: el registro estará disponible próximamente.'
    : 'Vista previa: la recuperación de acceso estará disponible próximamente.');
});
