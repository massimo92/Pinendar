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
assert.match(
  calendarCss,
  /\.calendar-guard-banner\{[^}]*min-width:0[^}]*overflow:hidden/,
  'La guardia semanal debe encogerse y recortar su contenido dentro de la celda',
);
assert.match(
  calendarCss,
  /\.calendar-shell\.view-week \.calendar-guard-banner\{display:grid;gap:2px;padding:5px 6px;font-size:10px\}/,
  'La guardia semanal debe usar las mismas dimensiones que los demás eventos',
);
assert.match(
  calendarCss,
  /\.calendar-shell\.view-week \.calendar-guard-banner span,\.calendar-shell\.view-week \.calendar-guard-banner b\{[^}]*max-width:100%[^}]*text-overflow:ellipsis/,
  'Cada línea de la guardia semanal debe truncarse como el resto de eventos',
);
assert.match(
  appSource,
  /\$\$\('\.calendar-filter\[open\]'\)[\s\S]*?!filter\.contains\(event\.target\)[\s\S]*?removeAttribute\('open'\)/,
  'Los filtros de personas y agendas deben cerrarse al pulsar fuera',
);

console.log('calendar toolbar layout regression: ok');
