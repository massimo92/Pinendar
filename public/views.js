function logo() {
  return document.querySelector('#icon-logo')?.innerHTML || '';
}

const navIcons = {
  calendar: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4m8-4v4M3 10h18"/></svg>',
  guards: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 7v5c0 4.8 3.1 7.7 8 9 4.9-1.3 8-4.2 8-9V7l-8-4Z"/><path d="m9 12 2 2 4-4"/></svg>',
  team: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2"/><path d="M3 20c0-4 2.4-6 6-6s6 2 6 6m0-5c3.5 0 5 1.7 5 5"/></svg>',
  agendas: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/></svg>',
  setup: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1A7 7 0 0 0 15 6l-.3-2.6h-4L10.4 6a7 7 0 0 0-1.5.9l-2.4-1-2 3.4 2 1.6a7 7 0 0 0 0 2.2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 1.5.9l.3 2.6h4L15 18a7 7 0 0 0 1.5-.9l2.4 1 2-3.4-2-1.6c.1-.3.1-.7.1-1.1Z"/></svg>',
  history: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20V10m6 10V4m6 16v-7m4 7H2"/></svg>',
  guide: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A3.5 3.5 0 0 1 7.5 2H12v18H7.5A3.5 3.5 0 0 0 4 23V5.5Zm16 0A3.5 3.5 0 0 0 16.5 2H12v18h4.5A3.5 3.5 0 0 1 20 23V5.5Z"/></svg>',
};

export function loginTemplate({ mode = 'login', error = '', recoveryCode = '', username = '', signupEnabled = true, approvalPending = false }, escapeHtml) {
  const fields = mode === 'signup'
    ? `<div class="field"><label>Usuari</label><input name="username" autocomplete="username" autofocus required minlength="3" placeholder="El teu usuari" /></div>
      <div class="field"><label>Contrasenya</label><input type="password" name="password" autocomplete="new-password" required minlength="8" placeholder="Mínim 8 caràcters" /></div>
      <div class="field"><label>Repeteix la contrasenya</label><input type="password" name="confirmation" autocomplete="new-password" required minlength="8" /></div>`
    : mode === 'recover'
      ? `<div class="field"><label>Usuari</label><input name="username" autocomplete="username" autofocus required value="${escapeHtml(username)}" /></div>
        <div class="field"><label>Clau de recuperació</label><input name="recoveryCode" autocomplete="off" required placeholder="XXXX-XXXX-…" /></div>
        <div class="field"><label>Contrasenya nova</label><input type="password" name="password" autocomplete="new-password" required minlength="8" /></div>
        <div class="field"><label>Repeteix la contrasenya</label><input type="password" name="confirmation" autocomplete="new-password" required minlength="8" /></div>`
      : `<div class="field"><label>Usuari</label><input name="username" autocomplete="username" autofocus required /></div>
        <div class="field"><label>Contrasenya</label><input type="password" name="password" autocomplete="current-password" required /></div>`;
  const title = mode === 'signup' ? 'Crea el teu entorn.' : mode === 'recover' ? 'Recupera l’accés.' : 'Planifica amb calma.';
  const action = mode === 'signup' ? 'Crea el compte' : mode === 'recover' ? 'Canvia la contrasenya' : 'Entra a Pinendar';
  if (recoveryCode) return `<section class="login"><div class="login-card">
    <div class="brand">${logo()}<span>Pinendar</span></div>
    <h1>Desa aquesta clau.</h1><p class="muted">${approvalPending ? 'La sol·licitud està pendent d’aprovació. Desa la clau i entra quan l’administrador l’hagi acceptat.' : 'És l’única manera de recuperar el compte sense correu. Només es mostra ara.'}</p>
    <code class="recovery-code" id="recovery-code">${escapeHtml(recoveryCode)}</code>
    <button class="button secondary" type="button" data-auth-action="copy-recovery">Copia la clau</button>
    <button class="button ghost" type="button" data-auth-action="download-recovery" data-username="${escapeHtml(username)}">Descarrega-la</button>
    <button class="button" type="button" data-auth-action="continue">Continua</button>
  </div></section>`;
  return `<section class="login"><form class="login-card" id="login-form" data-mode="${mode}">
    <div class="brand">${logo()}<span>Pinendar</span></div>
    <h1>${title}</h1><p class="muted">${mode === 'login' ? 'Accedeix al teu entorn de planificació.' : 'Cada compte té dades completament independents.'}</p>
    ${fields}
    ${error ? `<p class="form-error">${escapeHtml(error)}</p>` : ''}
    <button class="button">${action}</button>
    <div class="auth-links">${mode !== 'login' ? '<button type="button" data-auth-mode="login">Ja tinc compte</button>' : `${signupEnabled ? '<button type="button" data-auth-mode="signup">Crea un compte</button>' : ''}<button type="button" data-auth-mode="recover">He oblidat la contrasenya</button>`}</div>
  </form></section>`;
}

export function navTemplate({ page, language, labelFor, publicAccess = false }) {
  const items = publicAccess
    ? [['calendar', 'Calendari'], ['history', 'Equitat i històric']]
    : [['calendar', 'Calendari'], ['guards', 'Guàrdies'], ['team', 'Equip'], ['agendas', 'Agendes'], ['setup', 'Configuració'], ['history', 'Equitat i històric'], ['guide', 'Guia d’ús']];
  return `<aside class="sidebar"><div class="brand">${logo()}<span>Pinendar</span></div>
    <nav class="nav" aria-label="Navegació principal">${items.map(([id, label]) => { const text = language === 'es' ? labelFor(id) : label; return `<button data-page="${id}" class="${page === id ? 'active' : ''}" aria-label="${text}" aria-current="${page === id ? 'page' : 'false'}"><span class="nav-icon">${navIcons[id]}</span><span class="nav-label">${text}</span></button>`; }).join('')}</nav>
    <div class="sidebar-foot">${publicAccess ? 'Consulta compartida' : 'Servei de Radiologia Abdominal'}<br><span class="status">${publicAccess ? 'Accés públic · només lectura' : 'Dades locals · SQLite'}</span></div>
  </aside>`;
}

export function headerTemplate({ title, subtitle, actions, language, account, publicAccess = false }) {
  if (publicAccess) return `<header class="topbar"><div><h1>${title}</h1>${subtitle ? `<div class="muted">${subtitle}</div>` : ''}</div><div class="top-actions"><span class="readonly-badge">Només lectura</span></div></header>`;
  const languages = [['ca', 'CA', 'Català'], ['es', 'ES', 'Español']];
  const selected = languages.find(([value]) => value === language) || languages[0];
  const languagePicker = `<details class="language-picker"><summary aria-label="Idioma" aria-haspopup="listbox"><span>${selected[1]}</span></summary><div class="language-menu" role="listbox">${languages.map(([value, short, name]) => `<button type="button" role="option" aria-selected="${value === language}" data-action="language" data-language="${value}"><span>${name}</span><b>${short}</b>${value === language ? '<i aria-hidden="true">✓</i>' : '<i aria-hidden="true"></i>'}</button>`).join('')}</div></details>`;
  const recoveryButton = `<button class="button ghost small" data-action="open-recovery-code" title="Compte: ${account?.username || ''}">Clau de recuperació</button>`;
  const publicLinkButton = `<button class="button ghost small" data-action="open-public-link">Enllaç públic</button>`;
  return `<header class="topbar"><div><h1>${title}</h1>${subtitle ? `<div class="muted">${subtitle}</div>` : ''}</div><div class="top-actions">${actions}${publicLinkButton}${languagePicker}${recoveryButton}<button class="button ghost small" data-action="logout">Surt</button></div></header>`;
}

export function shellTemplate({ navigation, view, modal, publicAccess = false }) {
  return `<div class="shell ${publicAccess ? 'public-readonly' : ''}">${navigation}<main class="page">${view}</main></div><div class="toast"></div>${modal}`;
}
