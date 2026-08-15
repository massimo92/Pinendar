export const MANAGEMENT_ACTIVITY = Object.freeze({
  id: 'management',
  name: 'Gestió',
  telematic: true,
  loadPercentage: 100,
  color: '#b9d532',
});

export function planningActivities(agendas = []) {
  return agendas.some((item) => item.id === MANAGEMENT_ACTIVITY.id)
    ? [...agendas]
    : [...agendas, MANAGEMENT_ACTIVITY];
}

export function sortByName(items, locale = 'ca') {
  return [...items].sort((left, right) => left.name.localeCompare(
    right.name,
    locale,
    { sensitivity: 'base' },
  ));
}

export function compactActivityMeta(activity) {
  const load = Number(activity.loadPercentage || 100) === 50 ? 'P' : 'C';
  if (activity.id === MANAGEMENT_ACTIVITY.id) return load;
  const shift = activity.shift === 'afternoon' ? 'T' : 'M';
  return `${shift} · ${load}`;
}

export function hospitalInitials(name) {
  const original = String(name || '').trim();
  const words = original.replace(/-Ias$/i, '').match(/\p{L}+/gu) || [];
  const initials = words
    .filter((word) => /^\p{Lu}/u.test(word))
    .map((word) => [...word][0].toLocaleUpperCase('ca'))
    .join('');
  return initials || original;
}

export function compactHospitalName(hospital) {
  return String(hospital?.shortName || '').trim() || hospitalInitials(hospital?.name);
}

export function assignmentExchangePreviewLabels({
  sourceAgenda,
  targetAgenda,
  hospitals = [],
}) {
  const label = (agenda) => {
    const hospital = hospitals.find((item) => item.catalogId === agenda?.hospitalId);
    return `${agenda?.name || '—'} · ${compactHospitalName(hospital) || 'Sense hospital'}`;
  };
  return {
    sourceToTarget: `${label(sourceAgenda)} → ${label(targetAgenda)}`,
    targetToSource: `${label(targetAgenda)} → ${label(sourceAgenda)}`,
  };
}

export function planningActivityGroups({
  agendas,
  hospitals,
  locale = 'ca',
  withoutHospitalLabel = 'Sense hospital',
  otherActivitiesLabel = 'Altres activitats',
}) {
  const hospitalIds = new Set(hospitals.map((hospital) => hospital.catalogId));
  const hospitalGroups = sortByName(hospitals, locale).map((hospital) => ({
    label: hospital.name,
    items: sortByName(
      agendas.filter((item) => item.hospitalId === hospital.catalogId),
      locale,
    ),
  })).filter((group) => group.items.length);
  const withoutHospital = sortByName(
    agendas.filter((item) => !hospitalIds.has(item.hospitalId)),
    locale,
  );
  return [
    ...hospitalGroups,
    ...(withoutHospital.length ? [{ label: withoutHospitalLabel, items: withoutHospital }] : []),
    { label: otherActivitiesLabel, items: [MANAGEMENT_ACTIVITY] },
  ];
}

export function historicalActivityCounts(members, activities, records) {
  const loads = Object.fromEntries(
    activities.map((item) => [item.id, Number(item.loadPercentage || 100) / 100]),
  );
  const counts = Object.fromEntries(
    members.map((member) => [
      member.id,
      Object.fromEntries(activities.map((item) => [item.id, 0])),
    ]),
  );
  records.forEach((record) => {
    (record.assignments || []).forEach((assignment) => {
      if (counts[assignment.memberId]?.[assignment.type] !== undefined) {
        counts[assignment.memberId][assignment.type] += loads[assignment.type];
      }
    });
  });
  return counts;
}

function normalizedDistributionEquity(references, ownLoadFor) {
  const ownComparableTotal = references.reduce((sum, item) => sum + ownLoadFor(item.agenda), 0);
  const referenceTotal = references.reduce((sum, item) => sum + item.peerShare, 0);
  if (!references.length || !ownComparableTotal || !referenceTotal) return null;
  const cells = references.map((item) => {
    const actualShare = ownLoadFor(item.agenda) / ownComparableTotal;
    const expectedShare = item.peerShare / referenceTotal;
    const deviation = actualShare - expectedShare;
    return { ...item, actualShare, expectedShare, deviation, absoluteDeviation: Math.abs(deviation) };
  });
  const distance = Math.min(1, cells.reduce((sum, item) => sum + item.absoluteDeviation, 0) / 2);
  return { cells, distance, score: Math.round((1 - distance) * 100) };
}


export function historicalEquityAnalysis({ members, activities, assignments, scoredMemberIds = null, cutoff = null }) {
  const activityCandidates = activities.filter((item) => !['management', 'gestio', 'no_assignment'].includes(item.id));
  const activityById = Object.fromEntries(activityCandidates.map((item) => [item.id, item]));
  const people = members.filter((member, index, items) => member?.id && items.findIndex((candidate) => candidate.id === member.id) === index);
  const memberById = Object.fromEntries(people.map((member) => [member.id, member]));
  const clinicalAssignments = assignments
    .filter((item) => activityById[item.type] && memberById[item.memberId] && (!cutoff || item.date <= cutoff))
    .map((item) => ({
      ...item,
      load: Number(item.loadPercentage ?? activityById[item.type].loadPercentage ?? 100) / 100,
    }))
    .sort((left, right) => left.date.localeCompare(right.date));
  const clinicalActivities = activityCandidates.filter((item) => clinicalAssignments.some((assignment) => assignment.type === item.id));
  const scoredIds = scoredMemberIds ? new Set(scoredMemberIds) : new Set(people.map((member) => member.id));
  const counts = Object.fromEntries(people.map((member) => [member.id, Object.fromEntries(clinicalActivities.map((item) => [item.id, 0]))]));
  clinicalAssignments.forEach((item) => { counts[item.memberId][item.type] += item.load; });

  const cells = [];
  const memberScores = {};
  const memberDetails = {};
  for (const member of people.filter((item) => scoredIds.has(item.id))) {
    const ownAssignments = clinicalAssignments.filter((item) => item.memberId === member.id);
    if (!ownAssignments.length) { memberScores[member.id] = null; continue; }
    const startDate = ownAssignments[0].date;
    const windowAssignments = clinicalAssignments.filter((item) => item.date >= startDate);
    const windowPeople = people.filter((candidate) => windowAssignments.some((item) => item.memberId === candidate.id));
    const windowCounts = Object.fromEntries(windowPeople.map((candidate) => [candidate.id, Object.fromEntries(clinicalActivities.map((item) => [item.id, 0]))]));
    windowAssignments.forEach((item) => { windowCounts[item.memberId][item.type] += item.load; });
    const windowTotals = Object.fromEntries(windowPeople.map((candidate) => [candidate.id, clinicalActivities.reduce((sum, item) => sum + windowCounts[candidate.id][item.id], 0)]));
    const comparators = windowPeople.filter((candidate) => candidate.id !== member.id && windowTotals[candidate.id] > 0);
    const teamTotal = windowAssignments.reduce((sum, item) => sum + item.load, 0);
    const references = comparators.length ? clinicalActivities.map((agenda) => ({
      agenda,
      peerShare: comparators.reduce(
        (sum, candidate) => sum + windowCounts[candidate.id][agenda.id] / windowTotals[candidate.id],
        0,
      ) / comparators.length,
      peerCount: comparators.length,
    })) : [];
    const distribution = normalizedDistributionEquity(
      references,
      (agenda) => windowCounts[member.id][agenda.id],
    );
    const ownCells = (distribution?.cells || []).map((item) => {
      const { agenda, absoluteDeviation, ...cell } = item;
      const agendaLoad = windowAssignments.filter((item) => item.type === agenda.id).reduce((sum, item) => sum + item.load, 0);
      const historicalWeight = teamTotal ? agendaLoad / teamTotal : 0;
      const result = {
        ...cell,
        member,
        agenda,
        relativeDeviation: absoluteDeviation,
        historicalWeight,
        value: windowCounts[member.id][agenda.id],
      };
      cells.push(result);
      return result;
    });
    memberScores[member.id] = distribution?.score ?? null;
    memberDetails[member.id] = {
      startDate,
      endDate: cutoff || clinicalAssignments.at(-1)?.date || startDate,
      distance: distribution?.distance ?? null,
      cells: ownCells,
    };
  }
  const measuredScores = Object.values(memberScores).filter((value) => value !== null);
  const globalScore = measuredScores.length ? Math.round(measuredScores.reduce((sum, value) => sum + value, 0) / measuredScores.length) : null;
  return { activities: clinicalActivities, assignments: clinicalAssignments, counts, cells, memberScores, memberDetails, globalScore };
}

export function operationalEquityAnalysis({ members, activities, assignments, scoredMemberIds = null, cutoff = null }) {
  const activityCandidates = activities.filter((item) => !['management', 'gestio', 'no_assignment'].includes(item.id));
  const activityById = Object.fromEntries(activityCandidates.map((item) => [item.id, item]));
  const people = members.filter((member, index, items) => member?.id && items.findIndex((candidate) => candidate.id === member.id) === index);
  const memberById = Object.fromEntries(people.map((member) => [member.id, member]));
  const clinicalAssignments = assignments
    .filter((item) => activityById[item.type] && memberById[item.memberId] && (!cutoff || item.date <= cutoff))
    .map((item) => ({
      ...item,
      load: Number(item.loadPercentage ?? activityById[item.type].loadPercentage ?? 100) / 100,
    }))
    .sort((left, right) => left.date.localeCompare(right.date));
  const scoredIds = scoredMemberIds ? new Set(scoredMemberIds) : new Set(people.map((member) => member.id));
  const memberScores = {};
  const memberDetails = {};

  for (const member of people.filter((item) => scoredIds.has(item.id))) {
    const ownAssignments = clinicalAssignments.filter((item) => item.memberId === member.id);
    if (!ownAssignments.length) { memberScores[member.id] = null; continue; }
    const startDate = ownAssignments[0].date;
    const windowAssignments = clinicalAssignments.filter((item) => item.date >= startDate);
    const windowPeople = people.filter((candidate) => windowAssignments.some((item) => item.memberId === candidate.id));
    const windowCounts = Object.fromEntries(windowPeople.map((candidate) => [candidate.id, Object.fromEntries(activityCandidates.map((item) => [item.id, 0]))]));
    windowAssignments.forEach((item) => { windowCounts[item.memberId][item.type] += item.load; });
    const windowTotals = Object.fromEntries(windowPeople.map((candidate) => [candidate.id, activityCandidates.reduce((sum, item) => sum + windowCounts[candidate.id][item.id], 0)]));
    const feasibleIds = new Set((member.allowedTypes || []).filter((activityId) => activityById[activityId]));
    const references = activityCandidates.flatMap((agenda) => {
      if (!feasibleIds.has(agenda.id)) return [];
      const peers = windowPeople.filter((candidate) => candidate.id !== member.id
        && (candidate.allowedTypes || []).includes(agenda.id)
        && windowTotals[candidate.id] > 0);
      if (!peers.length) return [];
      const peerShare = peers.reduce((sum, candidate) => sum + windowCounts[candidate.id][agenda.id] / windowTotals[candidate.id], 0) / peers.length;
      return [{ agenda, peerShare, peerCount: peers.length }];
    });
    const distribution = normalizedDistributionEquity(
      references,
      (agenda) => windowCounts[member.id][agenda.id],
    );
    if (!distribution) { memberScores[member.id] = null; continue; }
    const cells = distribution.cells.map(({ absoluteDeviation, ...item }) => ({
      ...item,
      deviation: absoluteDeviation,
    }));
    memberScores[member.id] = distribution.score;
    memberDetails[member.id] = {
      startDate,
      endDate: cutoff || clinicalAssignments.at(-1)?.date || startDate,
      distance: distribution.distance,
      cells,
    };
  }

  const measuredScores = Object.values(memberScores).filter((value) => value !== null);
  const globalScore = measuredScores.length ? Math.round(measuredScores.reduce((sum, value) => sum + value, 0) / measuredScores.length) : null;
  const worstScore = measuredScores.length ? Math.min(...measuredScores) : null;
  return { memberScores, memberDetails, globalScore, worstScore };
}


export function historicalEquityTimeline({ members, activities, assignments, resolution = 'day' }) {
  const activityCandidates = activities.filter((item) => !['management', 'gestio', 'no_assignment'].includes(item.id));
  const activityById = Object.fromEntries(activityCandidates.map((item) => [item.id, item]));
  const people = members.filter((member, index, items) => member?.id && items.findIndex((candidate) => candidate.id === member.id) === index);
  const memberById = Object.fromEntries(people.map((member) => [member.id, member]));
  const clinicalAssignments = assignments
    .filter((item) => activityById[item.type] && memberById[item.memberId])
    .map((item) => ({ ...item, load: Number(item.loadPercentage ?? activityById[item.type].loadPercentage ?? 100) / 100 }))
    .sort((left, right) => left.date.localeCompare(right.date));
  const clinicalActivities = activityCandidates.filter((item) => clinicalAssignments.some((assignment) => assignment.type === item.id));
  const allDates = [...new Set(clinicalAssignments.map((item) => item.date))];
  const dates = resolution === 'month'
    ? [...new Map(allDates.map((date) => [date.slice(0, 7), date])).values()]
    : allDates;
  const sampledDates = new Set(dates);
  const assignmentsByDate = new Map(allDates.map((date) => [date, clinicalAssignments.filter((item) => item.date === date)]));
  const zeroVector = () => Object.fromEntries(clinicalActivities.map((item) => [item.id, 0]));
  const windows = {};
  const series = Object.fromEntries(people.map((member) => [member.id, []]));
  const average = [];
  const scoreWindow = (memberId) => {
    const windowCounts = windows[memberId];
    const totals = Object.fromEntries(people.map((member) => [member.id, clinicalActivities.reduce((sum, item) => sum + windowCounts[member.id][item.id], 0)]));
    const ownTotal = totals[memberId] || 0;
    const comparators = people.filter((member) => member.id !== memberId && totals[member.id] > 0);
    if (!ownTotal || !comparators.length) return null;
    const references = clinicalActivities.map((agenda) => ({
      agenda,
      peerShare: comparators.reduce(
        (sum, member) => sum + windowCounts[member.id][agenda.id] / totals[member.id],
        0,
      ) / comparators.length,
    }));
    return normalizedDistributionEquity(
      references,
      (agenda) => windowCounts[memberId][agenda.id],
    )?.score ?? null;
  };
  for (const date of allDates) {
    const dailyAssignments = assignmentsByDate.get(date) || [];
    const starters = [...new Set(dailyAssignments.map((item) => item.memberId))].filter((memberId) => !windows[memberId]);
    starters.forEach((memberId) => { windows[memberId] = Object.fromEntries(people.map((member) => [member.id, zeroVector()])); });
    for (const item of dailyAssignments) {
      Object.values(windows).forEach((windowCounts) => { windowCounts[item.memberId][item.type] += item.load; });
    }
    if (!sampledDates.has(date)) continue;
    const scores = [];
    for (const member of people) {
      if (!windows[member.id]) continue;
      const score = scoreWindow(member.id);
      if (score === null) continue;
      scores.push(score);
      series[member.id].push({ date, value: score / 100 });
    }
    if (scores.length) average.push({ date, value: scores.reduce((sum, value) => sum + value, 0) / scores.length / 100 });
  }
  return { people: people.filter((member) => series[member.id].length), dates, series, average, min: 0, max: 1 };
}
