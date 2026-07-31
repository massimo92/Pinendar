import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(
  new URL('../public/app.js', import.meta.url),
  'utf8',
);

assert.match(
  appSource,
  /pendingOperation: \{ type: 'assign-vacancy'[\s\S]*?returnModal/,
  'La revisión de una vacante debe conservar la lista de candidatos',
);

assert.match(
  appSource,
  /action === 'return-peonada-review'[\s\S]*?modal\?\.returnModal/,
  'Cancelar la revisión debe volver al modal anterior',
);

assert.match(
  appSource,
  /isReassignment[\s\S]*?minimumPeonadaLoadPercentage[\s\S]*?> 0/,
  'Los cambios sólo deben revisar a quien queda por encima del 100%',
);

assert.match(
  appSource,
  /assignmentActionModal[\s\S]*?open-assignment-exchange[\s\S]*?open-assignment-transfer/,
  'Una persona con varias agendas debe permitir intercambiar o ceder',
);

assert.match(
  appSource,
  /assignment-transfer-form[\s\S]*?pendingOperation: \{ type: 'transfer'/,
  'La cesión debe continuar a la revisión de peonadas cuando haga falta',
);

assert.match(
  appSource,
  /const manualExtraAction = calendarView === 'day'/,
  'La plaza extraordinaria sólo debe ofrecerse en la vista diaria',
);
assert.match(
  appSource,
  /calendar-extra-day-button[\s\S]*?open-manual-extra/,
  'El día debe incluir un botón protegido para crear una plaza extraordinaria',
);
assert.match(
  appSource,
  /\$\{manualExtraAction\}<div class="calendar-incident-badges">/,
  'El botón extraordinario debe ocupar el primer lugar de la cabecera diaria',
);
assert.match(
  appSource,
  /calendar-extra-day-icon[^`]*?>\+<\/span><\/button>/,
  'El botón extraordinario debe mostrar sólo el símbolo más',
);
assert.match(
  appSource,
  /modal-manual-extra[\s\S]*?manual-extra-date-display[\s\S]*?<select name="memberId"[\s\S]*?<select name="agendaId"/,
  'El alta manual debe mostrar fecha fija y selectores de persona y agenda',
);

assert.match(
  appSource,
  /pendingOperation: \{ type: 'extra-assignment'/,
  'Una plaza extraordinaria por encima del 100% debe abrir la revisión de peonadas',
);
assert.match(
  appSource,
  /pending\.type === 'extra-assignment'[\s\S]*?peonadaAssignments/,
  'La revisión de peonadas debe completar la plaza extraordinaria',
);

console.log('peonada modal navigation regression: ok');
