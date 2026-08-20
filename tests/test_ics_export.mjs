import assert from 'node:assert/strict';

import {
  buildIcsCalendar,
  buildIcsEvent,
  hospitalExportColor,
} from '../public/ics-export.mjs';

const member = { name: 'Anna Serra', email: 'anna@example.test' };
const hospital = { catalogId: 'hospital-trueta', name: 'Hospital Trueta', shortName: 'Trueta' };
const morning = buildIcsEvent({
  event: { id: 'morning-event', date: '2026-08-13' },
  member,
  agenda: { name: 'Ecografia', shift: 'morning' },
  hospital,
});
const afternoonPeonada = buildIcsEvent({
  event: { id: 'afternoon-event', date: '2026-08-14', peonada: true },
  member,
  agenda: { name: 'TAC urgent', shift: 'afternoon' },
  hospital,
});
const deferred = buildIcsEvent({
  event: { id: 'deferred-event', date: '2026-08-17', deferredOriginDate: '2026-08-11' },
  member,
  agenda: { name: 'RM telemàtica', shift: 'morning' },
  hospital,
});

assert.match(morning, /DTSTART:20260813T080000\r\n/);
assert.match(morning, /DTEND:20260813T150000\r\n/);
assert.match(morning, /SUMMARY:Anna Serra · Ecografia · Trueta\r\n/);
assert.match(afternoonPeonada, /DTSTART:20260814T150000\r\n/);
assert.match(afternoonPeonada, /DTEND:20260814T200000\r\n/);
assert.match(afternoonPeonada, /SUMMARY:Anna Serra · TAC urgent · Trueta \(P\)\r\n/);
assert.match(deferred, /SUMMARY:Anna Serra · RM telemàtica · Trueta \(D\)\r\n/);
assert.match(deferred, /DESCRIPTION:Diferida del 2026-08-11\r\n/);
assert.match(morning, /CATEGORIES:Trueta\r\n/);
assert.match(morning, new RegExp(`COLOR:${hospitalExportColor(hospital)}\\r\\n`));

assert.equal(
  hospitalExportColor(hospital),
  hospitalExportColor({ catalogId: 'hospital-trueta', name: 'Nombre cambiado' }),
  'El color debe depender del identificador estable del hospital',
);

const management = buildIcsEvent({
  event: { id: 'management-event', date: '2026-08-17', type: 'management' },
  member,
  agenda: { id: 'management', name: 'Gestió' },
});
assert.match(management, /DTSTART;VALUE=DATE:20260817\r\n/);
assert.match(management, /DTEND;VALUE=DATE:20260818\r\n/);
assert.match(management, /SUMMARY:Anna Serra · Gestió\r\n/);

const vacation = buildIcsEvent({
  event: {
    id: 'vacation-event',
    type: 'vacation',
    allDay: true,
    start: '2026-08-18',
    end: '2026-08-20',
  },
  member,
  agenda: { name: 'Vacaciones' },
});
assert.match(vacation, /DTSTART;VALUE=DATE:20260818\r\n/);
assert.match(vacation, /DTEND;VALUE=DATE:20260821\r\n/);
assert.match(vacation, /SUMMARY:Anna Serra · Vacaciones\r\n/);

const vacant = buildIcsEvent({
  event: { id: 'vacant-event', date: '2026-08-21' },
  agenda: { name: 'TAC urgent', shift: 'morning' },
  hospital,
});
assert.match(vacant, /SUMMARY:TAC urgent · Trueta\r\n/);
assert.match(vacant, /DTSTART:20260821T080000\r\n/);
assert.equal(
  hospitalExportColor({ catalogId: 'hospital-trueta' }),
  hospitalExportColor({ catalogId: 'hospital-trueta' }),
);

const calendar = buildIcsCalendar([morning, afternoonPeonada, deferred, management, vacation, vacant]);
assert.ok(calendar.startsWith('BEGIN:VCALENDAR\r\nVERSION:2.0'));
assert.match(calendar, /CALSCALE:GREGORIAN\r\nMETHOD:PUBLISH\r\nPRODID:-\/\/Pinendar\/\/CA/);
assert.ok(calendar.endsWith('END:VCALENDAR'));
assert.equal(calendar.match(/BEGIN:VEVENT/g)?.length, 6);

console.log('ics-export tests passed');
