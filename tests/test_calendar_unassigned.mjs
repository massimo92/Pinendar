import assert from 'node:assert/strict';
import {
  calendarRowsForDate,
  calendarIncidentsForDate,
  calendarIssueFilterFromValue,
  dailyAssignmentLoad,
  eligibleUnassignedMemberIds,
  toggleCalendarIssueFilter,
  vacanciesForDate,
  visibleAbsencesForDate,
} from '../public/calendar-utils.mjs';

assert.deepEqual(
  toggleCalendarIssueFilter(new Set(['partial']), 'vacancy'),
  new Set(['vacancy']),
  'Un filtro de incidencia nuevo debe reemplazar el anterior',
);
assert.deepEqual(
  toggleCalendarIssueFilter(new Set(['vacancy']), 'vacancy'),
  new Set(),
  'Pulsar de nuevo el filtro activo debe limpiarlo',
);
assert.deepEqual(
  calendarIssueFilterFromValue('partial,vacancy', new Set(['partial', 'vacancy'])),
  new Set(['vacancy']),
  'Una URL antigua con varios filtros debe conservar sólo el último',
);

const members = [
  { id: 'active', active: true },
  { id: 'available', active: true },
  { id: 'inactive', active: false },
  { id: 'vacation', active: true },
  { id: 'postguard', active: true },
];
const assignments = [{ memberId: 'active', date: '2026-08-01', type: 'clinical' }];
const ids = ({ assignments: input = assignments } = {}) => eligibleUnassignedMemberIds({
  members,
  assignments: input,
  date: '2026-08-01',
  memberWorksOnDate: () => true,
  isMemberAbsentOnDate: (member) => ['vacation', 'postguard'].includes(member.id),
});

assert.deepEqual(ids(), new Set(['available']));
assert.deepEqual(ids({ assignments: [{ memberId: 'active', date: '2026-08-01', type: 'no_assignment' }] }), new Set());
assert.deepEqual(ids({ assignments: [{ memberId: 'inactive', date: '2026-08-01', type: 'clinical' }] }), new Set());

const agendas = [
  { id: 'half-a', loadPercentage: 50 },
  { id: 'half-b', loadPercentage: 50 },
  { id: 'full', loadPercentage: 100 },
];
assert.equal(dailyAssignmentLoad({
  assignments: [{ memberId: 'active', date: '2026-08-01', type: 'half-a' }],
  agendas,
  memberId: 'active',
  date: '2026-08-01',
}), 50);
assert.equal(dailyAssignmentLoad({
  assignments: [
    { memberId: 'active', date: '2026-08-01', type: 'half-a' },
    { memberId: 'active', date: '2026-08-01', type: 'half-b' },
  ],
  agendas,
  memberId: 'active',
  date: '2026-08-01',
}), 100);
assert.equal(dailyAssignmentLoad({
  assignments: [{
    memberId: 'active',
    date: '2026-08-01',
    type: 'full',
    loadPercentage: 50,
  }],
  agendas,
  memberId: 'active',
  date: '2026-08-01',
}), 50, 'El evento conserva su carga histórica aunque cambie la agenda');
assert.deepEqual(
  vacanciesForDate({
    unfilled: [
      { date: '2026-08-01', type: 'half-a' },
      { date: '2026-08-01', type: 'half-b' },
      { date: '2026-08-02', type: 'half-a' },
    ],
    date: '2026-08-01',
    selectedAgendaIds: new Set(['half-a']),
  }),
  [{ date: '2026-08-01', type: 'half-a' }],
);
assert.deepEqual(
  calendarRowsForDate({
    assignments: [
      { memberId: 'active', date: '2026-08-01', type: 'half-a' },
      { memberId: 'available', date: '2026-08-01', type: 'half-b' },
    ],
    guards: [
      { memberId: 'active', date: '2026-08-01' },
      { memberId: 'available', date: '2026-08-01' },
    ],
    vacancies: [{ date: '2026-08-01', type: 'half-a' }],
    date: '2026-08-01',
    selectedMemberIds: new Set(['active']),
    selectedAgendaIds: new Set(['half-a']),
  }),
  {
    assignments: [{ memberId: 'active', date: '2026-08-01', type: 'half-a' }],
    guards: [{ memberId: 'active', date: '2026-08-01' }],
    vacancies: [],
  },
  'Un filtro de persona no debe dejar pasar vacantes ni filas de otras personas',
);
assert.deepEqual(
  visibleAbsencesForDate({
    savedAbsences: [{
      memberId: 'active',
      category: 'vacances',
      start: '2026-08-01',
      end: '2026-08-03',
    }],
    calendarAbsences: [{
      id: 'vacation-active',
      memberId: 'active',
      category: 'vacances',
      start: '2026-08-01',
      end: '2026-08-03',
    }],
    date: '2026-08-02',
  }),
  [{
    id: 'vacation-active',
    memberId: 'active',
    category: 'vacances',
    start: '2026-08-01',
    end: '2026-08-03',
  }],
);

const incidents = calendarIncidentsForDate({
  assignments: [
    { memberId: 'active', date: '2026-08-01', type: 'half-a' },
    { memberId: 'available', date: '2026-08-01', type: 'no_assignment' },
  ],
  agendas,
  unfilled: [
    { date: '2026-08-01', type: 'full' },
    { date: '2026-08-01', type: 'half-b' },
  ],
  members,
  date: '2026-08-01',
  memberWorksOnDate: () => true,
  isMemberAbsentOnDate: (member) => ['vacation', 'postguard'].includes(member.id),
});
assert.equal(incidents.vacancies.length, 2);
assert.deepEqual(incidents.unassignedMemberIds, new Set(['available']));
assert.deepEqual(incidents.partialMemberIds, new Set(['active']));
