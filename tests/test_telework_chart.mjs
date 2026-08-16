import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const calendarCss = readFileSync(new URL('../public/calendar.css', import.meta.url), 'utf8');
const teleworkSource = appSource.slice(
  appSource.indexOf('function teleworkBar'),
  appSource.indexOf('function happinessTimeline'),
);

assert.match(teleworkSource, /class="telework-track"/, 'Debe conservar la barra global de teletrabajo');
assert.match(teleworkSource, /balance\.weekdays\.map/, 'Debe renderizar el detalle de lunes a viernes');
assert.match(teleworkSource, /class="telework-weekdays"/, 'Debe añadir el detalle debajo de la barra global');
assert.match(teleworkSource, /class="telework-weekday-track"/, 'Cada día debe replicar el formato de la barra global');
assert.match(teleworkSource, /<b class="team"/, 'La media del equipo debe mostrarse como una marca');
assert.match(calendarCss, /\.telework-weekday-track\{height:5px;/, 'Las barras diarias deben tener poco peso visual');

console.log('telework chart regression: ok');
