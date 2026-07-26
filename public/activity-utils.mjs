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

export function compactHospitalName(hospital) {
  if (hospital?.shortName) return hospital.shortName;
  return String(hospital?.name || '')
    .replace(/^Hospital Universitari de Girona Dr\. Josep\s+/i, '')
    .replace(/^Hospital\s+/i, '')
    .replace(/-Ias$/i, '')
    .replace(/^d['’]/i, '')
    .replace(/\s+i\s+Comarcal.*$/i, '');
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
