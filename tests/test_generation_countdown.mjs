import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const calendarCss = readFileSync(new URL('../public/calendar.css', import.meta.url), 'utf8');

assert.match(appSource, /data-generation-countdown/, 'El popup debe mostrar la cuenta atrás');
assert.match(appSource, /timeLimitSeconds/, 'La cuenta atrás debe usar el límite real del servidor');
assert.match(appSource, /name="generationTimeLimitMinutes" type="number" min="1" max="30"/, 'El popup debe limitar el tiempo entre uno y treinta minutos');
assert.match(appSource, /timeLimitMinutes: 2/, 'El tiempo predeterminado debe ser de dos minutos');
assert.match(appSource, /timeLimitMinutes: Number\(form\.get\('generationTimeLimitMinutes'\)\)/, 'El límite escogido debe enviarse al servidor');
assert.match(appSource, /clampGenerationTimeLimit\(event\.target\.value\)/, 'El valor visible debe limitarse inmediatamente');
assert.match(appSource, /setInterval\(updateGenerationCountdown/, 'La cuenta atrás debe actualizarse durante la generación');
assert.match(calendarCss, /\.generation-loading-countdown\{/, 'La cuenta atrás debe tener un estilo discreto propio');

console.log('generation countdown regression: ok');
