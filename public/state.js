export const LEGACY_AGENDAS = [
  { id: 'tac_amb', name: 'TAC ambulatori', telematic: true, color: 'hsl(199 92% 55%)' },
  { id: 'eco_amb', name: 'Eco ambulatòria', telematic: false, color: 'hsl(154 86% 48%)' },
  { id: 'tac_urg', name: 'TAC urgent', telematic: false, color: 'hsl(3 94% 62%)' },
  { id: 'eco_urg', name: 'Eco urgent', telematic: false, color: 'hsl(28 94% 58%)' },
  { id: 'eco_tec', name: 'Eco tècnics', telematic: false, color: 'hsl(174 84% 46%)' },
  { id: 'reso', name: 'Ressonància', telematic: true, color: 'hsl(257 91% 67%)' },
  { id: 'intervencio', name: 'Intervencionisme', telematic: false, color: 'hsl(328 88% 61%)' },
  { id: 'general', name: 'General', telematic: false, color: 'hsl(210 15% 62%)' },
  { id: 'gestio', name: 'Gestió', telematic: true, color: 'hsl(65 86% 53%)' },
  { id: 'telemando', name: 'Telecomandament', telematic: true, color: 'hsl(187 88% 51%)' }
];

export function normalizeBootstrapState(payload) {
  payload.team = Array.isArray(payload.team) ? payload.team : [];
  payload.agendas = Array.isArray(payload.agendas) ? payload.agendas : [];
  payload.hospitals = Array.isArray(payload.hospitals) ? payload.hospitals : [];
  for (const hospital of payload.hospitals) hospital.locationKnown = hospital.locationKnown !== false;
  payload.archivedTeam = Array.isArray(payload.archivedTeam) ? payload.archivedTeam : [];
  payload.archivedAgendas = Array.isArray(payload.archivedAgendas) ? payload.archivedAgendas : [];
  payload.coverage ||= {};
  payload.guards = Array.isArray(payload.guards) ? payload.guards : [];
  payload.holidays = Array.isArray(payload.holidays) ? payload.holidays : [];
  payload.published = Array.isArray(payload.published) ? payload.published : [];
  for (let day = 1; day <= 5; day += 1) payload.coverage[day] ||= {};
  for (const member of [...payload.team, ...payload.archivedTeam]) {
    member.availableDays = Array.isArray(member.availableDays) ? member.availableDays : [];
    const legacyTeleDays = Array.isArray(member.teleDays) ? member.teleDays : [];
    const rawWeeks = member.workPattern?.weeks?.length ? member.workPattern.weeks : [[...member.availableDays]];
    member.workPattern = { weeks: rawWeeks.slice(0, 5).map((week) => {
      if (!Array.isArray(week)) return { workingDays: [...(week.workingDays || [])], teleDays: [...(week.teleDays || [])] };
      return { workingDays: [...week], teleDays: week.filter((day) => legacyTeleDays.includes(day)) };
    }) };
    member.fixedRules = Array.isArray(member.fixedRules) ? member.fixedRules : [];
    member.agendaPreferences = member.agendaPreferences && typeof member.agendaPreferences === 'object' ? member.agendaPreferences : {};
    member.managementQuota = Math.min(5, Math.max(0, Number(member.managementQuota || 0)));
    member.vacations = Array.isArray(member.vacations) ? member.vacations : [];
    member.vacationDates = Array.isArray(member.vacationDates) ? member.vacationDates : [];
    member.statusHistory = Array.isArray(member.statusHistory) ? member.statusHistory : [];
    member.active = member.active !== false;
  }
  for (const agenda of [...payload.agendas, ...payload.archivedAgendas]) {
    agenda.priority = Math.min(4, Math.max(1, Number(agenda.priority || 3)));
    agenda.loadPercentage = Number(agenda.loadPercentage) === 50 ? 50 : 100;
    agenda.shift = ['morning', 'afternoon'].includes(agenda.shift) ? agenda.shift : 'morning';
    agenda.recurrences = Array.isArray(agenda.recurrences) ? agenda.recurrences : [];
  }
  return payload;
}
