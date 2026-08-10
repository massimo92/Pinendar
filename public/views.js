function logo() {
  return document.querySelector('#icon-logo')?.innerHTML || '';
}

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

export function navTemplate({ page, language, labelFor }) {
  const items = [['calendar', 'Calendari'], ['guards', 'Guàrdies'], ['team', 'Equip'], ['agendas', 'Agendes'], ['setup', 'Configuració'], ['history', 'Equitat i històric'], ['guide', 'Guia d’ús']];
  return `<aside class="sidebar"><div class="brand">${logo()}<span>Pinendar</span></div>
    <nav class="nav">${items.map(([id, label]) => `<button data-page="${id}" class="${page === id ? 'active' : ''}"><span class="dot"></span>${language === 'es' ? labelFor(id) : label}</button>`).join('')}</nav>
    <div class="sidebar-foot">Servei de Radiologia Abdominal<br><span class="status">Dades locals · SQLite</span></div>
  </aside>`;
}

export function headerTemplate({ title, subtitle, actions, language, account }) {
  const languages = [['ca', 'CA', 'Català'], ['es', 'ES', 'Español']];
  const selected = languages.find(([value]) => value === language) || languages[0];
  const languagePicker = `<details class="language-picker"><summary aria-label="Idioma" aria-haspopup="listbox"><span>${selected[1]}</span></summary><div class="language-menu" role="listbox">${languages.map(([value, short, name]) => `<button type="button" role="option" aria-selected="${value === language}" data-action="language" data-language="${value}"><span>${name}</span><b>${short}</b>${value === language ? '<i aria-hidden="true">✓</i>' : '<i aria-hidden="true"></i>'}</button>`).join('')}</div></details>`;
  const recoveryButton = `<button class="button ghost small" data-action="open-recovery-code" title="Compte: ${account?.username || ''}">Clau de recuperació</button>`;
  return `<header class="topbar"><div><h1>${title}</h1>${subtitle ? `<div class="muted">${subtitle}</div>` : ''}</div><div class="top-actions">${actions}${languagePicker}${recoveryButton}<button class="button ghost small" data-action="logout">Surt</button></div></header>`;
}

export function shellTemplate({ navigation, view, modal }) {
  return `<div class="shell">${navigation}<main class="page">${view}</main></div><div class="toast"></div>${modal}`;
}
