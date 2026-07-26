export function eligibleUnassignedMemberIds({ members, assignments, date, selectedMemberIds, memberWorksOnDate, isMemberAbsentOnDate }) {
  const activeIds = new Set(members.filter((member) => member.active !== false).map((member) => member.id));
  const realAssignments = assignments.filter((item) => item.date === date && item.type !== 'no_assignment' && activeIds.has(item.memberId));
  if (!realAssignments.length) return new Set();
  const assignedIds = new Set(realAssignments.map((item) => item.memberId));
  return new Set(members
    .filter((member) => member.active !== false)
    .filter((member) => !selectedMemberIds?.size || selectedMemberIds.has(member.id))
    .filter((member) => memberWorksOnDate(member, date))
    .filter((member) => !assignedIds.has(member.id))
    .filter((member) => !isMemberAbsentOnDate(member, date))
    .map((member) => member.id));
}

export function dailyAssignmentLoad({ assignments, agendas, memberId, date }) {
  const loads = Object.fromEntries(
    agendas.map((agenda) => [agenda.id, Number(agenda.loadPercentage || 100)]),
  );
  return assignments
    .filter((item) => item.memberId === memberId && item.date === date)
    .reduce((total, item) => {
      if (item.type === 'no_assignment') return total;
      if (item.type === 'management') return total + 100;
      return total + Number(loads[item.type] || 0);
    }, 0);
}

export function vacanciesForDate({ unfilled, date, selectedAgendaIds }) {
  return unfilled.filter(
    (item) => item.date === date
      && (!selectedAgendaIds?.size || selectedAgendaIds.has(item.type)),
  );
}


export function calendarIncidentsForDate({
  assignments,
  agendas,
  unfilled,
  members,
  date,
  memberWorksOnDate,
  isMemberAbsentOnDate,
}) {
  const activeMemberIds = new Set(
    members.filter((member) => member.active !== false).map((member) => member.id),
  );
  const dateAssignments = assignments.filter(
    (item) => item.date === date && activeMemberIds.has(item.memberId),
  );
  const persistedUnassignedIds = new Set(
    dateAssignments
      .filter((item) => item.type === 'no_assignment')
      .map((item) => item.memberId),
  );
  const inferredUnassignedIds = eligibleUnassignedMemberIds({
    members,
    assignments,
    date,
    memberWorksOnDate,
    isMemberAbsentOnDate,
  });
  const unassignedMemberIds = new Set([
    ...persistedUnassignedIds,
    ...inferredUnassignedIds,
  ]);
  const assignedMemberIds = new Set(
    dateAssignments
      .filter((item) => !['no_assignment', 'management'].includes(item.type))
      .map((item) => item.memberId),
  );
  const partialMemberIds = new Set(
    [...assignedMemberIds].filter(
      (memberId) => dailyAssignmentLoad({ assignments, agendas, memberId, date }) === 50,
    ),
  );
  return {
    vacancies: vacanciesForDate({ unfilled, date }),
    unassignedMemberIds,
    partialMemberIds,
  };
}
