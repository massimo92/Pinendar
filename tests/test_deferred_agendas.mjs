import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const apiSource = readFileSync(new URL('../public/api.js', import.meta.url), 'utf8');
const indexSource = readFileSync(new URL('../public/index.html', import.meta.url), 'utf8');
const calendarSource = readFileSync(new URL('../public/calendar.css', import.meta.url), 'utf8');

assert.match(
  appSource,
  /deferredOriginDate[\s\S]*?calendar-deferred-marker[\s\S]*?>D<\/i>/,
  'El calendario debe distinguir las asignaciones diferidas con una D',
);
assert.match(
  appSource,
  /assignment-origin-detail[\s\S]*?deferredOriginDate/,
  'El popup debe mostrar la fecha original de una agenda diferida',
);
const compactAssignmentSource = appSource.slice(
  appSource.indexOf('const html = `<button class="calendar-event assignment'),
  appSource.indexOf('return eventEntry(html, hospital);'),
);
assert.doesNotMatch(
  compactAssignmentSource,
  /calendar-deferred-origin/,
  'La fecha original no debe ocupar espacio junto al nombre en el evento compacto',
);
assert.match(
  appSource,
  /deferredOptions[\s\S]*?deferred-option[\s\S]*?data-action="apply-deferred"[\s\S]*?deferred-option-target/,
  'La vacante debe mostrar propuestas diferidas como tarjetas completas con fecha destino',
);
assert.match(
  appSource,
  /const destinationName = destination\?\.name \|\| '—'[\s\S]*?deferred-option-target/,
  'La tarjeta diferida debe titularse con la persona destino',
);
assert.doesNotMatch(
  appSource.slice(appSource.indexOf('function vacancyAssignmentModal'), appSource.indexOf('function peonadaReviewModal')),
  /farà l’agenda diferida/,
  'La tarjeta no debe repetir la persona destino en una frase adicional',
);
assert.doesNotMatch(
  appSource.slice(appSource.indexOf('function vacancyAssignmentModal'), appSource.indexOf('function peonadaReviewModal')),
  /Confirma la diferida|class="button small"/,
  'La tarjeta diferida no debe contener un botón interno de confirmación',
);
assert.match(
  appSource,
  /action === 'apply-deferred'[\s\S]*?api\.deferVacancy/,
  'La propuesta diferida debe requerir confirmación explícita',
);
assert.match(
  appSource,
  /selectableDates[\s\S]*?data-action="select-deferred-date"[\s\S]*?const personOptions[\s\S]*?class="assignment-choice"/,
  'La vacante debe permitir elegir primero la fecha y después una persona con la tarjeta común',
);
assert.match(
  appSource,
  /personOptions[\s\S]*?currentLoadPercentage[\s\S]*?fairnessWorstDeltaBasisPoints/,
  'Las personas deben ordenarse por carga y después por equidad',
);
assert.match(
  appSource,
  /event\.target\.dataset\.targetDate !== modal\.payload\?\.date[\s\S]*?targetMemberId[\s\S]*?PEONADA_REVIEW_REQUIRED[\s\S]*?type: 'defer-vacancy'/,
  'El diferido con sobrecarga debe abrir la revisión normal de peonadas',
);
assert.match(
  appSource,
  /agendaItem\?\.telematic[\s\S]*?vacancy-date-section/,
  'El selector de fecha sólo debe mostrarse para agendas telemáticas',
);
assert.match(
  calendarSource,
  /calendar-event\.deferred[\s\S]*?#b78cff[\s\S]*?deferred-date-option\.active\.is-deferred[\s\S]*?#b78cff/,
  'La selección de una fecha futura debe reutilizar el lila de las agendas diferidas',
);
assert.match(
  calendarSource,
  /deferred-date-option\.active\{[\s\S]*?var\(--brand\)[\s\S]*?active\.is-deferred/,
  'La fecha original debe resaltarse en verde y una fecha diferida en lila',
);
assert.match(
  appSource,
  /dateTypeLabel = isOrigin \? 'Original' : 'Diferida'[\s\S]*?Carga ya asignada[\s\S]*?vacancy-peonada-status/,
  'Las fechas deben indicar su tipo y las personas deben mostrar la carga previa con estados de igual peso',
);
assert.doesNotMatch(
  appSource.slice(appSource.indexOf('function vacancyAssignmentModal'), appSource.indexOf('function peonadaReviewModal')),
  /vacancy-date-context/,
  'El selector no debe repetir la fecha diferida en un aviso adicional',
);
assert.match(
  appSource,
  /pending\.type === 'defer-vacancy'[\s\S]*?api\.deferVacancy[\s\S]*?peonadaAssignments/,
  'La revisión debe reenviar las peonadas elegidas al diferido',
);
assert.match(
  appSource,
  /Diferida:[\s\S]*?'Data origen'/,
  'El CSV debe incluir la marca diferida y la fecha de origen',
);
assert.match(apiSource, /deferVacancy:[\s\S]*?\/defer/);
assert.match(
  appSource,
  /deferredOptions[\s\S]*?apply-member-deferred[\s\S]*?targetMemberId/,
  'La persona sin asignación debe poder adoptar directamente una vacante telemática anterior',
);
assert.match(
  appSource,
  /<button type="button" class="deferred-option"[\s\S]*?data-action="apply-member-deferred"[\s\S]*?deferred-option-title/,
  'La tarjeta diferida completa debe ser el control de selección',
);
assert.doesNotMatch(
  appSource.slice(appSource.indexOf('const deferredRows'), appSource.indexOf('const deferredSection')),
  /class="button small"/,
  'La tarjeta diferida no debe contener un segundo botón interno',
);
assert.match(
  appSource,
  /Assigna una agenda diferida/,
  'El popup debe explicar que permite asignar una agenda diferida',
);
assert.match(
  appSource,
  /No es mourà ni s’afegirà cap altra activitat/,
  'El flujo inverso debe dejar claro que no reorganiza ninguna otra agenda',
);
assert.match(
  indexSource,
  /calendar\.css\?v=101/,
  'Los estilos de agendas diferidas deben invalidar la versión CSS anterior',
);

console.log('deferred agendas UI regression: ok');
