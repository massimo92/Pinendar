const HOSPITAL_COLORS = Object.freeze([
  '#D13438',
  '#CA5010',
  '#FFB900',
  '#498205',
  '#00CC6A',
  '#038387',
  '#0099BC',
  '#0078D4',
  '#4F6BED',
  '#8764B8',
  '#C239B3',
  '#E3008C',
]);

export function icsText(value = '') {
  return String(value)
    .replaceAll('\\', '\\\\')
    .replaceAll('\n', '\\n')
    .replaceAll(',', '\\,')
    .replaceAll(';', '\\;');
}

export function hospitalExportColor(hospital = {}) {
  const key = String(hospital.catalogId || hospital.id || hospital.name || 'without-hospital');
  let hash = 2166136261;
  for (let index = 0; index < key.length; index += 1) {
    hash ^= key.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return HOSPITAL_COLORS[(hash >>> 0) % HOSPITAL_COLORS.length];
}

function compactDate(value = '') {
  return String(value).replaceAll('-', '');
}

function addDays(value, amount) {
  const result = new Date(`${value}T12:00:00Z`);
  result.setUTCDate(result.getUTCDate() + amount);
  return result.toISOString().slice(0, 10);
}

export function buildIcsEvent({ event, member = {}, agenda = {}, hospital = {} }) {
  const allDay = Boolean(event.allDay || event.type === 'management' || agenda.id === 'management');
  const hospitalAlias = hospital.alias || hospital.shortName || hospital.name;
  const summaryParts = [member.name, agenda.name, hospitalAlias].filter(Boolean);
  const summary = `${summaryParts.join(' · ')}${event.peonada ? ' (P)' : ''}`;
  const category = hospitalAlias || 'Pinendar';
  const dates = allDay
    ? [
      `DTSTART;VALUE=DATE:${compactDate(event.start || event.date)}`,
      `DTEND;VALUE=DATE:${compactDate(addDays(event.end || event.start || event.date, 1))}`,
    ]
    : [
      `DTSTART:${compactDate(event.date)}T${agenda.shift === 'afternoon' ? '150000' : '080000'}`,
      `DTEND:${compactDate(event.date)}T${agenda.shift === 'afternoon' ? '200000' : '150000'}`,
    ];

  return [
    'BEGIN:VEVENT',
    `UID:${icsText(event.id)}@pinendar`,
    ...dates,
    `SUMMARY:${icsText(summary)}`,
    `LOCATION:${icsText(hospital.name || '')}`,
    `CATEGORIES:${icsText(category)}`,
    `COLOR:${hospitalExportColor(hospital)}`,
    `ATTENDEE;CN=${icsText(member.name || '')}:MAILTO:${member.email || ''}`,
    'END:VEVENT',
  ].join('\r\n');
}

export function buildIcsCalendar(events) {
  return [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'PRODID:-//Pinendar//CA',
    ...events,
    'END:VCALENDAR',
  ].join('\r\n');
}
