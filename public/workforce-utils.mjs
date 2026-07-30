const MAX_OBSERVED_WEEKS = 8;
const MIN_OBSERVED_WEEKS = 4;
const MIN_STRUCTURAL_WEEKS = 3;
const MIN_STRUCTURAL_WEEK_SHARE = 0.5;
const MIN_STRUCTURAL_VACANCY_RATE = 0.05;
const MAX_STRUCTURAL_PEAK_SHARE = 0.6;
const MIN_STRUCTURAL_IDLE_RATE = 0.1;

function isoWeek(value) {
  const current = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(current.getTime())) return null;
  const weekday = current.getUTCDay() || 7;
  current.setUTCDate(current.getUTCDate() + 4 - weekday);
  const year = current.getUTCFullYear();
  const yearStart = new Date(Date.UTC(year, 0, 1));
  const number = Math.ceil((((current - yearStart) / 86400000) + 1) / 7);
  return {
    key: `${year}-W${String(number).padStart(2, '0')}`,
    order: current.getTime(),
  };
}

function ratio(numerator, denominator) {
  return denominator ? numerator / denominator : 0;
}

function weekday(value) {
  const current = new Date(`${value}T00:00:00Z`);
  return current.getUTCDay() || 7;
}

function addDays(value, amount) {
  const current = new Date(`${value}T00:00:00Z`);
  current.setUTCDate(current.getUTCDate() + amount);
  return current.toISOString().slice(0, 10);
}

function memberWeek(member, date) {
  const weeks = member.workPattern?.weeks || [];
  if (!weeks.length) {
    return {
      workingDays: member.availableDays || [],
      teleDays: member.teleDays || [],
    };
  }
  const weekNumber = Number(isoWeek(date)?.key.split('-W')[1] || 1);
  const configured = weeks[(weekNumber - 1) % weeks.length] || {};
  return Array.isArray(configured)
    ? { workingDays: configured, teleDays: member.teleDays || [] }
    : {
      workingDays: configured.workingDays || [],
      teleDays: configured.teleDays || [],
    };
}

function activityLoad(item, agendas) {
  const explicit = Number(item.loadPercentage);
  if ([50, 100].includes(explicit)) return explicit / 100;
  const agenda = agendas.find((candidate) => candidate.id === item.type);
  return Number(agenda?.loadPercentage || 100) === 50 ? 0.5 : 1;
}

function memberCanCover(member, vacancy, agendas) {
  if (!(member.allowedTypes || []).includes(vacancy.type)) return false;
  const day = weekday(vacancy.date);
  const week = memberWeek(member, vacancy.date);
  if (!week.workingDays.includes(day)) return false;
  const agenda = agendas.find((candidate) => candidate.id === vacancy.type);
  if (week.teleDays.includes(day) && !agenda?.telematic) return false;
  const rules = (member.fixedRules || []).filter((rule) => Number(rule.weekday) === day);
  if (rules.some((rule) => (rule.forbiddenAgendaIds || []).includes(vacancy.type))) return false;
  const required = rules.flatMap((rule) => (
    rule.requiredAgendaIds?.length ? rule.requiredAgendaIds : rule.type ? [rule.type] : []
  ));
  return !required.length || required.includes(vacancy.type);
}

function temporaryCandidates({ date, assignments, members, absences, guards }) {
  const absentMemberIds = new Set(
    absences
      .filter((item) => item.start <= date && item.end >= date)
      .map((item) => item.memberId),
  );
  guards
    .filter((item) => addDays(item.date, 1) === date)
    .forEach((item) => absentMemberIds.add(item.memberId));
  const assignedMemberIds = new Set(
    assignments.filter((item) => item.date === date).map((item) => item.memberId),
  );
  return members.filter((member) => (
    member.active !== false
    && absentMemberIds.has(member.id)
    && !assignedMemberIds.has(member.id)
  ));
}

function recoverableVacancyLoad({ date, vacancies, assignments, members, absences, guards, agendas }) {
  const candidates = temporaryCandidates({ date, assignments, members, absences, guards });
  if (!candidates.length || !vacancies.length) return 0;
  const items = vacancies.map((vacancy) => ({
    units: Math.round(activityLoad(vacancy, agendas) * 2),
    eligible: candidates
      .map((member, index) => (memberCanCover(member, vacancy, agendas) ? index : -1))
      .filter((index) => index >= 0),
  })).sort((left, right) => right.units - left.units || left.eligible.length - right.eligible.length);
  const capacities = candidates.map(() => 2);
  const memo = new Map();
  const solve = (index) => {
    if (index >= items.length) return 0;
    const key = `${index}:${capacities.join('')}`;
    if (memo.has(key)) return memo.get(key);
    const item = items[index];
    let best = solve(index + 1);
    item.eligible.forEach((candidateIndex) => {
      if (capacities[candidateIndex] < item.units) return;
      capacities[candidateIndex] -= item.units;
      best = Math.max(best, item.units + solve(index + 1));
      capacities[candidateIndex] += item.units;
    });
    memo.set(key, best);
    return best;
  };
  return solve(0) / 2;
}

export function workforceCapacitySignal({
  assignments = [],
  vacancies = [],
  members = [],
  absences = [],
  guards = [],
  agendas = [],
}) {
  const ordinaryAssignments = assignments.filter((item) => !item.extra);
  const weekOrder = new Map();
  [...ordinaryAssignments, ...vacancies].forEach((item) => {
    const week = isoWeek(item.date);
    if (week) weekOrder.set(week.key, week.order);
  });
  const selectedWeeks = [...weekOrder]
    .sort((left, right) => left[1] - right[1])
    .slice(-MAX_OBSERVED_WEEKS)
    .map(([key]) => key);
  const selectedWeekSet = new Set(selectedWeeks);
  const inWindow = (item) => {
    const week = isoWeek(item.date);
    return week && selectedWeekSet.has(week.key);
  };
  const windowAssignments = ordinaryAssignments.filter(inWindow);
  const windowVacancies = vacancies.filter(inWindow);
  const clinicalAssignments = windowAssignments.filter(
    (item) => !['management', 'no_assignment'].includes(item.type),
  );
  const vacanciesByDate = new Map();
  windowVacancies.forEach((item) => {
    if (!vacanciesByDate.has(item.date)) vacanciesByDate.set(item.date, []);
    vacanciesByDate.get(item.date).push(item);
  });
  const adjustedVacanciesByWeek = new Map();
  let rawVacancyLoad = 0;
  let temporaryVacancyLoad = 0;
  vacanciesByDate.forEach((dailyVacancies, date) => {
    const dailyLoad = dailyVacancies.reduce(
      (total, item) => total + activityLoad(item, agendas),
      0,
    );
    const recoverable = Math.min(dailyLoad, recoverableVacancyLoad({
      date,
      vacancies: dailyVacancies,
      assignments: windowAssignments,
      members,
      absences,
      guards,
      agendas,
    }));
    const adjustedLoad = Math.max(0, dailyLoad - recoverable);
    rawVacancyLoad += dailyLoad;
    temporaryVacancyLoad += recoverable;
    if (adjustedLoad > 0) {
      const key = isoWeek(date).key;
      adjustedVacanciesByWeek.set(key, (adjustedVacanciesByWeek.get(key) || 0) + adjustedLoad);
    }
  });
  const adjustedVacancyLoad = Math.max(0, rawVacancyLoad - temporaryVacancyLoad);
  const idleAssignments = windowAssignments.filter((item) => item.type === 'no_assignment');
  const idleWeeks = new Set(idleAssignments.map((item) => isoWeek(item.date).key));
  const personDays = new Set(
    windowAssignments
      .filter((item) => item.memberId && item.date)
      .map((item) => `${item.memberId}:${item.date}`),
  );
  const idlePersonDays = new Set(
    idleAssignments.map((item) => `${item.memberId}:${item.date}`),
  );
  const observedWeeks = selectedWeeks.length;
  const vacancyWeeks = adjustedVacanciesByWeek.size;
  const clinicalAssignmentLoad = clinicalAssignments.reduce(
    (total, item) => total + activityLoad(item, agendas),
    0,
  );
  const vacancyRate = ratio(
    adjustedVacancyLoad,
    clinicalAssignmentLoad + rawVacancyLoad,
  );
  const vacancyWeekShare = ratio(vacancyWeeks, observedWeeks);
  const peakWeekShare = ratio(
    Math.max(0, ...adjustedVacanciesByWeek.values()),
    adjustedVacancyLoad,
  );
  const idleRate = ratio(idlePersonDays.size, personDays.size);
  const idleWeekShare = ratio(idleWeeks.size, observedWeeks);

  let kind = 'balanced';
  if (observedWeeks < MIN_OBSERVED_WEEKS) {
    kind = 'insufficient-data';
  } else if (
    adjustedVacancyLoad > 0
    && vacancyWeeks >= MIN_STRUCTURAL_WEEKS
    && vacancyWeekShare >= MIN_STRUCTURAL_WEEK_SHARE
    && vacancyRate >= MIN_STRUCTURAL_VACANCY_RATE
    && peakWeekShare < MAX_STRUCTURAL_PEAK_SHARE
  ) {
    kind = 'structural-shortage';
  } else if (rawVacancyLoad > 0) {
    kind = 'temporary-pressure';
  } else if (
    idleRate >= MIN_STRUCTURAL_IDLE_RATE
    && idleWeekShare >= MIN_STRUCTURAL_WEEK_SHARE
  ) {
    kind = 'structural-slack';
  }

  return {
    kind,
    observedWeeks,
    rawVacancyCount: windowVacancies.length,
    rawVacancyLoad,
    vacancyCount: adjustedVacancyLoad,
    adjustedVacancyLoad,
    temporaryVacancyLoad,
    vacancyWeeks,
    vacancyRate,
    vacancyWeekShare,
    peakWeekShare,
    idlePersonDays: idlePersonDays.size,
    idleWeeks: idleWeeks.size,
    idleRate,
  };
}
