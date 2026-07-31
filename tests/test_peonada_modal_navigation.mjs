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

console.log('peonada modal navigation regression: ok');
