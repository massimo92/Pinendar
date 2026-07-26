import assert from 'node:assert/strict';

import {
  MANAGEMENT_ACTIVITY,
  compactActivityMeta,
  compactHospitalName,
  historicalActivityCounts,
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
assert.equal(compactHospitalName({ name: 'Hospital Universitari de Girona Dr. Josep Trueta' }), 'Trueta');
assert.equal(compactHospitalName({ name: 'Hospital Santa Caterina-Ias' }), 'Santa Caterina');
assert.equal(compactHospitalName({ name: "Hospital d'Olot i Comarcal de la Garrotxa" }), 'Olot');
assert.equal(compactHospitalName({ name: 'CAP Güell' }), 'CAP Güell');

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

console.log('activity-utils tests passed');
