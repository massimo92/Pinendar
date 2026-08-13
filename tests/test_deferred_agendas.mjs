import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const apiSource = readFileSync(new URL('../public/api.js', import.meta.url), 'utf8');

assert.match(
  appSource,
  /deferredOriginDate[\s\S]*?calendar-deferred-marker[\s\S]*?>D<\/i>/,
  'El calendario debe distinguir las asignaciones diferidas con una D',
);
assert.match(
  appSource,
  /deferredOptions[\s\S]*?movements[\s\S]*?apply-deferred/,
  'La vacante debe mostrar primero las propuestas diferidas y sus movimientos',
);
assert.match(
  appSource,
  /action === 'apply-deferred'[\s\S]*?api\.deferVacancy/,
  'La propuesta diferida debe requerir confirmación explícita',
);
assert.match(
  appSource,
  /Diferida:[\s\S]*?'Data origen'/,
  'El CSV debe incluir la marca diferida y la fecha de origen',
);
assert.match(apiSource, /deferVacancy:[\s\S]*?\/defer/);

console.log('deferred agendas UI regression: ok');
