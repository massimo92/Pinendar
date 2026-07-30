import assert from 'node:assert/strict';

import { workforceCapacitySignal } from '../public/workforce-utils.mjs';

const mondays = [
  '2027-01-04',
  '2027-01-11',
  '2027-01-18',
  '2027-01-25',
  '2027-02-01',
  '2027-02-08',
  '2027-02-15',
  '2027-02-22',
];
const regularAssignments = mondays.map((date, index) => ({
  id: `clinical-${index}`,
  memberId: 'person-a',
  date,
  type: 'clinical',
}));

const temporary = workforceCapacitySignal({
  assignments: regularAssignments,
  vacancies: [
    { date: '2027-02-08', type: 'clinical' },
    { date: '2027-02-08', type: 'clinical' },
  ],
});
assert.equal(temporary.kind, 'temporary-pressure');
assert.equal(temporary.observedWeeks, 8);
assert.equal(temporary.vacancyWeeks, 1);
assert.equal(temporary.peakWeekShare, 1);

const structural = workforceCapacitySignal({
  assignments: regularAssignments,
  vacancies: mondays.slice(3).map((date) => ({ date, type: 'clinical' })),
});
assert.equal(structural.kind, 'structural-shortage');
assert.equal(structural.vacancyWeeks, 5);

const availableMember = {
  id: 'person-b',
  active: true,
  availableDays: [1],
  allowedTypes: ['clinical'],
  fixedRules: [],
};
const vacationAdjusted = workforceCapacitySignal({
  assignments: regularAssignments,
  vacancies: mondays.slice(3).map((date) => ({ date, type: 'clinical' })),
  members: [availableMember],
  absences: [{
    memberId: 'person-b',
    start: '2027-01-25',
    end: '2027-02-22',
    category: 'vacances',
  }],
});
assert.equal(vacationAdjusted.kind, 'temporary-pressure');
assert.equal(vacationAdjusted.rawVacancyLoad, 5);
assert.equal(vacationAdjusted.adjustedVacancyLoad, 0);
assert.equal(vacationAdjusted.temporaryVacancyLoad, 5);
assert.equal(vacationAdjusted.vacancyWeeks, 0);

const postguardAdjusted = workforceCapacitySignal({
  assignments: regularAssignments,
  vacancies: mondays.slice(3).map((date) => ({ date, type: 'clinical' })),
  members: [availableMember],
  guards: ['2027-01-24', '2027-01-31', '2027-02-07', '2027-02-14', '2027-02-21']
    .map((date) => ({ date, memberId: 'person-b' })),
});
assert.equal(postguardAdjusted.kind, 'temporary-pressure');
assert.equal(postguardAdjusted.adjustedVacancyLoad, 0);
assert.equal(postguardAdjusted.temporaryVacancyLoad, 5);

const incompatibleAbsence = workforceCapacitySignal({
  assignments: regularAssignments,
  vacancies: mondays.slice(3).map((date) => ({ date, type: 'clinical' })),
  members: [{ ...availableMember, allowedTypes: ['other'] }],
  absences: [{ memberId: 'person-b', start: '2027-01-25', end: '2027-02-22' }],
});
assert.equal(incompatibleAbsence.kind, 'structural-shortage');
assert.equal(incompatibleAbsence.adjustedVacancyLoad, 5);

const slack = workforceCapacitySignal({
  assignments: [
    ...regularAssignments,
    ...mondays.slice(0, 5).map((date, index) => ({
      id: `idle-${index}`,
      memberId: 'person-b',
      date,
      type: 'no_assignment',
    })),
  ],
  vacancies: [],
});
assert.equal(slack.kind, 'structural-slack');
assert.equal(slack.idleWeeks, 5);

const insufficient = workforceCapacitySignal({
  assignments: regularAssignments.slice(0, 3),
  vacancies: [],
});
assert.equal(insufficient.kind, 'insufficient-data');

console.log('workforce-utils tests passed');
