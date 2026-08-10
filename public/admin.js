import { api, ApiError } from '/api.js?v=14';

const root = document.querySelector('#admin-app');
let overview = null;
let recoveryCode = '';

const escapeHtml = (value = '') => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const formatDate = (value) => value
  ? new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  : 'Nunca';

const formatBytes = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
};

function message(error) {
  return error instanceof ApiError ? error.message : 'Ha ocurrido un error inesperado';
}

function loginView(error = '') {
  root.innerHTML = `
    <section class="admin-login-shell">
      <form class="admin-login-card" id="admin-login-form">
        <div class="admin-brand"><span class="admin-logo">+</span><div><strong>Pinendar</strong><small>Consola de administración</small></div></div>
        <h1>Acceso de administrador</h1>
        <p>Esta sesión es independiente de la aplicación de planificación.</p>
        ${error ? `<div class="notice danger" role="alert">${escapeHtml(error)}</div>` : ''}
        <label>Usuario<input name="username" autocomplete="username" required autofocus /></label>
        <label>Contraseña<input name="password" type="password" autocomplete="current-password" required /></label>
        <button type="submit">Entrar</button>
        <a class="back-link" href="/">Volver a Pinendar</a>
      </form>
    </section>`;
}

function accountRow(account) {
  const protectedAccount = account.isAdmin;
  return `
    <form class="account-row" data-account-id="${escapeHtml(account.id)}">
      <div class="account-title"><strong>${escapeHtml(account.username)}</strong>${protectedAccount ? '<span class="badge">Admin</span>' : ''}</div>
      <label>Usuario<input name="username" value="${escapeHtml(account.username)}" ${protectedAccount ? 'disabled' : ''} required /></label>
      <label>Estado<select name="disabled" ${protectedAccount ? 'disabled' : ''}><option value="false" ${account.disabled ? '' : 'selected'}>Activo</option><option value="true" ${account.disabled ? 'selected' : ''}>Desactivado</option></select></label>
      <label>Nueva contraseña<input name="password" type="password" minlength="8" placeholder="Sin cambios" ${protectedAccount ? 'disabled' : ''} /></label>
      <div class="account-meta">Creado: ${formatDate(account.createdAt)}<br>Último acceso: ${formatDate(account.lastActiveAt)}</div>
      ${protectedAccount ? '<span class="protected">Cuenta protegida</span>' : '<div class="row-actions"><button type="submit">Guardar</button><button type="button" class="danger ghost" data-action="delete-account">Eliminar</button></div>'}
    </form>`;
}

function dashboardView() {
  const requests = overview.signupRequests.map((item) => `
    <tr><td><strong>${escapeHtml(item.username)}</strong></td><td>${formatDate(item.createdAt)}</td><td class="table-actions"><button data-action="approve" data-id="${escapeHtml(item.id)}">Aceptar</button><button class="danger ghost" data-action="reject" data-id="${escapeHtml(item.id)}">Rechazar</button></td></tr>`).join('');
  const backups = overview.backups.map((item) => `
    <tr><td>${escapeHtml(item.name)}</td><td>${formatDate(item.createdAt)}</td><td>${formatBytes(item.size)}</td><td><a class="button ghost" href="${escapeHtml(item.downloadUrl)}">Descargar</a></td></tr>`).join('');

  root.innerHTML = `
    <header class="admin-header"><div class="admin-brand"><span class="admin-logo">+</span><div><strong>Pinendar</strong><small>Administración</small></div></div><div><a class="button ghost" href="/">Abrir aplicación</a><button class="ghost" data-action="logout">Cerrar sesión</button></div></header>
    <div class="admin-layout">
      <div class="admin-intro"><div><h1>Panel de administración</h1><p>Solicitudes, usuarios y copias de seguridad.</p></div><button data-action="refresh">Actualizar</button></div>
      ${recoveryCode ? `<div class="notice recovery"><div><strong>Guarda el código de recuperación antes de salir</strong><code>${escapeHtml(recoveryCode)}</code></div><button class="ghost" data-action="copy-recovery">Copiar</button></div>` : ''}
      <section class="admin-card">
        <div class="section-title"><div><h2>Solicitudes pendientes</h2><p>${overview.signupRequests.length} pendientes</p></div></div>
        <div class="table-wrap"><table><thead><tr><th>Usuario</th><th>Fecha</th><th>Acciones</th></tr></thead><tbody>${requests || '<tr><td colspan="3" class="empty">No hay solicitudes pendientes</td></tr>'}</tbody></table></div>
      </section>
      <section class="admin-card">
        <div class="section-title"><div><h2>Usuarios</h2><p>${overview.accounts.length} cuentas</p></div></div>
        <form id="create-account-form" class="create-account"><label>Usuario<input name="username" required /></label><label>Contraseña inicial<input name="password" type="password" minlength="8" required /></label><button type="submit">Crear usuario</button></form>
        <div class="account-list">${overview.accounts.map(accountRow).join('')}</div>
      </section>
      <section class="admin-card">
        <div class="section-title"><div><h2>Copias de seguridad</h2><p>Incluyen usuarios y todas sus bases de datos.</p></div><button data-action="backup">Crear backup</button></div>
        <div class="table-wrap"><table><thead><tr><th>Archivo</th><th>Fecha</th><th>Tamaño</th><th></th></tr></thead><tbody>${backups || '<tr><td colspan="4" class="empty">No hay copias todavía</td></tr>'}</tbody></table></div>
      </section>
    </div>`;
}

async function refresh() {
  overview = await api.adminOverview();
  dashboardView();
}

async function run(action) {
  try {
    await action();
  } catch (error) {
    window.alert(message(error));
  }
}

root.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  if (form.id === 'admin-login-form') {
    try {
      await api.adminLogin(data.get('username'), data.get('password'));
      await refresh();
    } catch (error) {
      loginView(message(error));
    }
    return;
  }
  if (form.id === 'create-account-form') {
    await run(async () => {
      const created = await api.createAccount({ username: data.get('username'), password: data.get('password') });
      recoveryCode = created.recoveryCode;
      await refresh();
    });
    return;
  }
  if (form.matches('.account-row')) {
    const payload = { username: data.get('username'), disabled: data.get('disabled') === 'true' };
    if (data.get('password')) payload.password = data.get('password');
    await run(async () => { await api.updateAccount(form.dataset.accountId, payload); await refresh(); });
  }
});

root.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const { action, id } = button.dataset;
  if (action === 'logout') {
    await api.adminLogout();
    overview = null;
    recoveryCode = '';
    loginView();
  } else if (action === 'refresh') {
    await run(refresh);
  } else if (action === 'approve') {
    await run(async () => { await api.approveSignup(id); await refresh(); });
  } else if (action === 'reject' && window.confirm('¿Rechazar esta solicitud?')) {
    await run(async () => { await api.rejectSignup(id); await refresh(); });
  } else if (action === 'delete-account') {
    const form = button.closest('.account-row');
    if (window.confirm(`¿Eliminar definitivamente a ${form.querySelector('[name="username"]').value} y todos sus datos?`)) {
      await run(async () => { await api.deleteAccount(form.dataset.accountId); await refresh(); });
    }
  } else if (action === 'backup') {
    await run(async () => { await api.createBackup(); await refresh(); });
  } else if (action === 'copy-recovery') {
    await navigator.clipboard.writeText(recoveryCode);
    button.textContent = 'Copiado';
  }
});

(async () => {
  try {
    await refresh();
  } catch (error) {
    if (error instanceof ApiError && [401, 403].includes(error.status)) loginView();
    else loginView(message(error));
  }
})();
