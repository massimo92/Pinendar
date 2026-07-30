export class ApiError extends Error {
  constructor(payload, status) {
    super(payload?.error?.message || 'Error');
    this.name = 'ApiError';
    this.status = status;
    this.code = payload?.error?.code || 'REQUEST_FAILED';
    this.field = payload?.error?.field || null;
    this.details = payload?.error?.details || {};
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'content-type': 'application/json', ...(options.headers || {}) },
  });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(payload, response.status);
  return payload;
}

const json = (method, body) => ({ method, body: JSON.stringify(body) });

export const api = {
  login: (username, password) => request('/api/v1/auth/login', json('POST', { username, password })),
  signup: (username, password) => request('/api/v1/auth/signup', json('POST', { username, password })),
  recover: (username, recoveryCode, newPassword) => request('/api/v1/auth/recover', json('POST', { username, recoveryCode, newPassword })),
  rotateRecoveryCode: () => request('/api/v1/auth/recovery-code', { method: 'POST' }),
  markGuideOnboardingSeen: () => request('/api/v1/auth/guide-onboarding-seen', { method: 'POST' }),
  logout: () => request('/api/v1/auth/logout', { method: 'POST' }),
  bootstrap: () => request('/api/v1/bootstrap'),
  previewGuardImport: (body) => request('/api/v1/guard-imports/preview', json('POST', body)),
  addGuards: (body) => request('/api/v1/guards', json('POST', body)),
  replaceGuards: (body) => request('/api/v1/guards', json('PUT', body)),
  previewGuardCession: (body) => request('/api/v1/guard-cessions/preview', json('POST', body)),
  applyGuardCession: (body) => request('/api/v1/guard-cessions', json('POST', body)),
  previewGuardExchange: (body) => request('/api/v1/guard-exchanges/preview', json('POST', body)),
  applyGuardExchange: (body) => request('/api/v1/guard-exchanges', json('POST', body)),
  saveMemberAlias: (body) => request('/api/v1/member-aliases', json('POST', body)),
  changeLanguage: (language) => request('/api/v1/settings/language', json('PATCH', { language })),
  searchHospitals: (query) => request(`/api/v1/hospitals?query=${encodeURIComponent(query)}`),
  hospitalDetails: (id) => request(`/api/v1/hospitals/${encodeURIComponent(id)}`),
  selectHospital: (body) => request('/api/v1/selected-hospitals', json('POST', body)),
  updateHospitalAlias: (id, shortName) => request(`/api/v1/selected-hospitals/${encodeURIComponent(id)}`, json('PATCH', { shortName })),
  removeHospital: (id) => request(`/api/v1/selected-hospitals/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  saveMember: (id, body) => request(id ? `/api/v1/members/${encodeURIComponent(id)}` : '/api/v1/members', json(id ? 'PUT' : 'POST', body)),
  deleteMember: (id) => request(`/api/v1/members/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  randomMemberColor: (id) => request(`/api/v1/members/${encodeURIComponent(id)}/random-color`, { method: 'POST' }),
  saveAgenda: (id, body) => request(id ? `/api/v1/agendas/${encodeURIComponent(id)}` : '/api/v1/agendas', json(id ? 'PUT' : 'POST', body)),
  deleteAgenda: (id) => request(`/api/v1/agendas/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  randomAgendaColor: (id) => request(`/api/v1/agendas/${encodeURIComponent(id)}/random-color`, { method: 'POST' }),
  deleteGuard: (id) => request(`/api/v1/guards/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  addHoliday: (date) => request('/api/v1/holidays', json('POST', { date })),
  deleteHoliday: (date) => request(`/api/v1/holidays/${encodeURIComponent(date)}`, { method: 'DELETE' }),
  updateAssignment: (id, type) => request(`/api/v1/calendar/events/${encodeURIComponent(id)}`, json('PATCH', { type })),
  assignmentExchangeOptions: (id, includeFixed = false) => request(`/api/v1/calendar/events/${encodeURIComponent(id)}/exchange-options${includeFixed ? '?includeFixed=true' : ''}`),
  exchangeAssignments: (id, targetAssignmentId, confirmFixed = false) => request(`/api/v1/calendar/events/${encodeURIComponent(id)}/exchange`, json('POST', { targetAssignmentId, confirmFixed })),
  extraAssignmentOptions: (date, memberId) => request(`/api/v1/calendar/dates/${encodeURIComponent(date)}/members/${encodeURIComponent(memberId)}/extra-options`),
  openExtraAssignment: (date, memberId, agendaId) => request(`/api/v1/calendar/dates/${encodeURIComponent(date)}/members/${encodeURIComponent(memberId)}/extra-assignments`, json('POST', { agendaId })),
  deleteCalendarRange: (startDate, endDate) => request(`/api/v1/calendar/assignments?startDate=${encodeURIComponent(startDate)}&endDate=${encodeURIComponent(endDate)}`, { method: 'DELETE' }),
  startGeneration: (body) => request('/api/v1/generation-jobs', json('POST', body)),
  generationJob: (id) => request(`/api/v1/generation-jobs/${encodeURIComponent(id)}`),
};

export async function waitForGeneration(id) {
  for (;;) {
    const job = await api.generationJob(id);
    if (['succeeded', 'failed', 'stale'].includes(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}
