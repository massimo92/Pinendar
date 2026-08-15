import assert from 'node:assert/strict';

import {
  MANAGEMENT_ACTIVITY,
  assignmentExchangePreviewLabels,
  compactActivityMeta,
  compactHospitalName,
  historicalActivityCounts,
  historicalEquityAnalysis,
  historicalEquityTimeline,
  hospitalInitials,
  operationalEquityAnalysis,
  planningActivities,
  planningActivityGroups,
  sortByName,
} from '../public/activity-utils.mjs';

const clinical = [
  { id: 'full', name: 'Completa', loadPercentage: 100 },
  { id: 'half', name: 'Parcial', loadPercentage: 50 },
];
const activities = planningActivities(clinical);

assert.deepEqual(activities.map((item) => item.id), ['full', 'half', 'management']);
assert.equal(planningActivities(activities).filter((item) => item.id === 'management').length, 1);
assert.equal(MANAGEMENT_ACTIVITY.telematic, true);
assert.equal(compactActivityMeta({ id: 'morning-full', shift: 'morning', loadPercentage: 100 }), 'M · C');
assert.equal(compactActivityMeta({ id: 'afternoon-half', shift: 'afternoon', loadPercentage: 50 }), 'T · P');
assert.equal(compactActivityMeta(MANAGEMENT_ACTIVITY), 'C');
assert.equal(hospitalInitials("Hospital d'Olot i Comarcal de la Garrotxa"), 'HOCG');
assert.equal(hospitalInitials('Hospital Santa Caterina-Ias'), 'HSC');
assert.equal(hospitalInitials('Hospital Universitari de Girona Dr. Josep Trueta'), 'HUGDJT');
assert.equal(hospitalInitials('CAP Güell'), 'CG');
assert.equal(compactHospitalName({ shortName: 'Trueta', name: 'Hospital Universitari de Girona Dr. Josep Trueta' }), 'Trueta');
assert.equal(compactHospitalName({ shortName: '  ', name: 'Hospital Santa Caterina-Ias' }), 'HSC');
assert.deepEqual(
  assignmentExchangePreviewLabels({
    sourceAgenda: { name: 'Eco', hospitalId: 'trueta' },
    targetAgenda: { name: 'TAC', hospitalId: 'bellvitge' },
    hospitals: [
      { catalogId: 'trueta', name: 'Hospital Universitari de Girona Dr. Josep Trueta' },
      { catalogId: 'bellvitge', name: 'Hospital Universitari de Bellvitge' },
    ],
  }),
  {
    sourceToTarget: 'Eco · HUGDJT → TAC · HUB',
    targetToSource: 'TAC · HUB → Eco · HUGDJT',
  },
);

const counts = historicalActivityCounts(
  [{ id: 'person-a' }, { id: 'person-b' }],
  activities,
  [{
    assignments: [
      { memberId: 'person-a', type: 'full' },
      { memberId: 'person-a', type: 'half' },
      { memberId: 'person-a', type: 'management' },
      { memberId: 'person-a', type: 'no_assignment' },
      { memberId: 'person-b', type: 'management' },
    ],
  }],
);

assert.deepEqual(counts['person-a'], { full: 1, half: 0.5, management: 1 });
assert.deepEqual(counts['person-b'], { full: 0, half: 0, management: 1 });

assert.deepEqual(sortByName([{ name: 'Zulu' }, { name: 'Àgata' }]).map((item) => item.name), ['Àgata', 'Zulu']);
const grouped = planningActivityGroups({
  agendas: [
    { id: 'z', name: 'Zulu', hospitalId: 'hospital-b' },
    { id: 'a', name: 'Àgata', hospitalId: 'hospital-b' },
    { id: 'c', name: 'Colon', hospitalId: 'hospital-a' },
  ],
  hospitals: [
    { catalogId: 'hospital-b', name: 'Trueta' },
    { catalogId: 'hospital-a', name: 'Banyoles' },
  ],
});
assert.deepEqual(grouped.map((group) => group.label), ['Banyoles', 'Trueta', 'Altres activitats']);
assert.deepEqual(grouped[1].items.map((item) => item.name), ['Àgata', 'Zulu']);
assert.deepEqual(grouped[2].items.map((item) => item.id), ['management']);

const equityActivities = [
  { id: 'general', name: 'General', loadPercentage: 100 },
  { id: 'olot', name: 'Olot', loadPercentage: 100 },
  { id: 'gestio', name: 'Gestió', loadPercentage: 100 },
];
const equityMembers = [{ id: 'old' }, { id: 'new' }];
const equityAssignments = [
  { date: '2024-01-08', memberId: 'old', type: 'general' },
  { date: '2025-01-08', memberId: 'old', type: 'general' },
  { date: '2026-01-08', memberId: 'old', type: 'general' },
  { date: '2026-01-08', memberId: 'new', type: 'olot' },
  { date: '2026-01-09', memberId: 'old', type: 'gestio', fixed: true },
];
const equity = historicalEquityAnalysis({
  members: equityMembers,
  activities: equityActivities,
  assignments: equityAssignments,
});
assert.deepEqual(equity.activities.map((item) => item.id), ['general', 'olot']);
assert.equal(equity.memberDetails.old.startDate, '2024-01-08');
assert.equal(equity.memberDetails.new.startDate, '2026-01-08');
assert.equal(equity.memberScores.old, 0, 'Un reparto concentrado no se excusa por capacidades o reglas');
assert.equal(equity.memberScores.new, 0, 'La persona evaluada debe excluirse de la media del equipo');

const balancedEquity = historicalEquityAnalysis({
  members: equityMembers,
  activities: equityActivities,
  assignments: [
    { date: '2026-01-08', memberId: 'old', type: 'general' },
    { date: '2026-01-09', memberId: 'old', type: 'olot' },
    { date: '2026-01-08', memberId: 'new', type: 'general' },
    { date: '2026-01-09', memberId: 'new', type: 'olot' },
  ],
});
assert.equal(balancedEquity.memberScores.old, 100);
assert.equal(balancedEquity.memberScores.new, 100);
assert.equal(balancedEquity.globalScore, 100);

const universalMembers = [
  { id: 'person-a', allowedTypes: ['general', 'olot', 'remote'] },
  { id: 'person-b', allowedTypes: ['general', 'olot', 'remote'] },
];
const universalActivities = [
  { id: 'general', name: 'General', loadPercentage: 100 },
  { id: 'olot', name: 'Olot', loadPercentage: 100 },
  { id: 'remote', name: 'Remota', loadPercentage: 100 },
];
const universalAssignments = [
  ...Array.from({ length: 8 }, (_, index) => ({ date: `2026-01-${String(index + 1).padStart(2, '0')}`, memberId: 'person-a', type: 'general' })),
  ...Array.from({ length: 2 }, (_, index) => ({ date: `2026-01-${String(index + 9).padStart(2, '0')}`, memberId: 'person-a', type: 'olot' })),
  ...Array.from({ length: 6 }, (_, index) => ({ date: `2026-01-${String(index + 1).padStart(2, '0')}`, memberId: 'person-b', type: 'general' })),
  ...Array.from({ length: 3 }, (_, index) => ({ date: `2026-01-${String(index + 7).padStart(2, '0')}`, memberId: 'person-b', type: 'olot' })),
  { date: '2026-01-10', memberId: 'person-b', type: 'remote' },
];
const operationalEquity = operationalEquityAnalysis({
  members: universalMembers,
  activities: universalActivities,
  assignments: universalAssignments,
});
assert.equal(operationalEquity.memberScores['person-a'], 80, 'La referencia operativa debe excluir a la persona evaluada');
assert.equal(operationalEquity.memberScores['person-b'], 80);
assert.equal(operationalEquity.globalScore, 80);
assert.equal(operationalEquity.worstScore, 80);

const structuralWithUniversalCapabilities = historicalEquityAnalysis({
  members: universalMembers,
  activities: universalActivities,
  assignments: universalAssignments,
});
assert.deepEqual(
  structuralWithUniversalCapabilities.memberScores,
  operationalEquity.memberScores,
  'Las equidades deben coincidir por persona cuando todos pueden hacer todas las agendas',
);
assert.equal(structuralWithUniversalCapabilities.globalScore, operationalEquity.globalScore);
const universalTimeline = historicalEquityTimeline({
  members: universalMembers,
  activities: universalActivities,
  assignments: universalAssignments,
});
assert.equal(universalTimeline.series['person-a'].at(-1).value, 0.8);
assert.equal(universalTimeline.series['person-b'].at(-1).value, 0.8);

const singleCapableMembers = [
  { id: 'specialist', allowedTypes: ['general', 'exclusive'] },
  { id: 'peer', allowedTypes: ['general'] },
];
const singleCapableActivities = [
  { id: 'general', name: 'General', loadPercentage: 100 },
  { id: 'exclusive', name: 'Exclusiva', loadPercentage: 100 },
];
const singleCapableAssignments = [
  { date: '2026-02-01', memberId: 'specialist', type: 'general' },
  { date: '2026-02-01', memberId: 'specialist', type: 'exclusive' },
  { date: '2026-02-01', memberId: 'peer', type: 'general' },
];
const singleCapableStructural = historicalEquityAnalysis({
  members: singleCapableMembers,
  activities: singleCapableActivities,
  assignments: singleCapableAssignments,
});
const singleCapableOperational = operationalEquityAnalysis({
  members: singleCapableMembers,
  activities: singleCapableActivities,
  assignments: singleCapableAssignments,
});
assert.deepEqual(singleCapableStructural.memberScores, { specialist: 50, peer: 50 });
assert.deepEqual(
  singleCapableOperational.memberScores,
  { specialist: 100, peer: 100 },
  'Una agenda sin otro compañero capacitado no debe desviar la equidad operativa',
);

const equityTimeline = historicalEquityTimeline({
  members: equityMembers,
  activities: equityActivities,
  assignments: equityAssignments,
  resolution: 'month',
});
assert.deepEqual(equityTimeline.dates, ['2024-01-08', '2025-01-08', '2026-01-08']);
assert.equal(equityTimeline.series.old.at(-1).value, equity.memberScores.old / 100);
assert.equal(equityTimeline.series.new.at(-1).value, equity.memberScores.new / 100);

console.log('activity-utils tests passed');
