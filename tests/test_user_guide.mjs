import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const guideSource = appSource.slice(
  appSource.indexOf('function guidePage()'),
  appSource.indexOf('function activeGuards()'),
);

for (const expected of [
  'Cobertura de Gestió',
  'Equilibri operatiu',
  'Poliment final',
  'd’1 a 30 minuts',
  'Pot haver-hi diverses persones de guàrdia',
  'Ha de fer totes',
  'Activitat per regles fixes',
  'Els diferits conserven la data original',
]) {
  assert.match(guideSource, new RegExp(expected), `La guía debe explicar: ${expected}`);
}

assert.equal(
  (guideSource.match(/\[g\('(Cobertura presencial|Cobertura de Gestió|Cobertura telemàtica|Equilibri operatiu|Poliment final)'/g) || []).length,
  5,
  'La jerarquía visible del generador debe resumirse en cinco bloques',
);

assert.doesNotMatch(
  guideSource,
  /No se supera la carga diaria: una agenda completa o dos agendas parciales diferentes/,
  'La guía no debe conservar el antiguo límite absoluto del 100%',
);

console.log('user guide regression: ok');
