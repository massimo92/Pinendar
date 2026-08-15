import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');
const calendarCss = readFileSync(new URL('../public/calendar.css', import.meta.url), 'utf8');
const toolbarSource = appSource.slice(
  appSource.indexOf('<section class="calendar-toolbar card">'),
  appSource.indexOf('<section class="calendar-shell card'),
);

assert.match(
  toolbarSource,
  /calendar-navigation[\s\S]*?view-switch[\s\S]*?calendar-nav[\s\S]*?calendar-controls[\s\S]*?calendar-filters/,
  'El selector de vista debe estar encima de la navegación del período',
);
assert.match(
  calendarCss,
  /\.calendar-navigation \.view-switch\{width:100%\}/,
  'El selector debe equilibrarse con el ancho del bloque de navegación',
);
assert.match(
  calendarCss,
  /\.calendar-navigation\{[^}]*width:max-content/,
  'Selector y navegación deben compartir su longitud horizontal real',
);
assert.match(
  calendarCss,
  /\.view-switch\{[^}]*gap:6px/,
  'Día, semana y mes deben tener separación visual',
);
const calendarCellSource = appSource.slice(
  appSource.indexOf('function calendarCell'),
  appSource.indexOf('function alphabetically'),
);
assert.doesNotMatch(
  calendarCellSource,
  /badge\('(vacancy|unassigned)'/,
  'Ninguna celda diaria debe repetir los filtros superiores de vacantes o personas sin agenda',
);
assert.match(
  calendarCellSource,
  /badge\('partial'/,
  'La incidencia parcial debe conservar su indicador porque no tiene filtro superior',
);

console.log('calendar toolbar layout regression: ok');
