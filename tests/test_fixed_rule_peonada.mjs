import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const stateSource = readFileSync(new URL('../public/state.js', import.meta.url), 'utf8');
const calendarCss = readFileSync(new URL('../public/calendar.css', import.meta.url), 'utf8');

assert.match(appSource, /function fixedRuleOccurrenceLoads/, 'La UI debe calcular la carga por coincidencia real');
assert.match(appSource, /name="rule-peonada-agenda"/, 'La regla debe permitir marcar agendas como peonada');
assert.match(appSource, /peonadaIds\.has\(id\) \? '<em>Peonada<\/em>' : ''/, 'La etiqueta Peonada sólo debe mostrarse en la opción seleccionada');
assert.match(appSource, /fixed-rule-peonada-meta[\s\S]*?loadPercentage[\s\S]*?%/, 'Cada opción debe mostrar su porcentaje de carga');
assert.match(appSource, /ordinaryLoad !== 100/, 'La UI debe exigir exactamente el 100% ordinario');
assert.match(appSource, /peonadaAgendaIds: action === 'all'/, 'El payload debe enviar las peonadas sólo para «todas»');
assert.match(appSource, /\$\{peonada\.has\(id\) \? ' \(P\)' : ''\}/, 'El resumen debe identificar las peonadas');
assert.match(stateSource, /peonadaAgendaIds: Array\.isArray/, 'Las reglas antiguas deben normalizarse sin peonadas');
assert.match(calendarCss, /\.fixed-rule-peonada\{/, 'La selección de peonada debe tener un bloque visual propio');
assert.match(calendarCss, /\.fixed-rule-peonada\{[^}]*rgba\(90,169,255/, 'El bloque debe reutilizar el azul de las peonadas del calendario');

console.log('fixed rule peonada UI regression: ok');
