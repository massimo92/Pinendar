import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const appSource = readFileSync(
  new URL('../public/app.js', import.meta.url),
  'utf8',
);

assert.match(
  appSource,
  /function guardInlineImpact/,
  'Debe existir una representación reutilizable del impacto dentro del formulario',
);

assert.match(
  appSource,
  /function guardImpactActivityName[\s\S]*?no_assignment[\s\S]*?Sense assignació/,
  'El impacto debe identificar Sin asignación sin llamarlo Agenda eliminada',
);

assert.match(
  appSource,
  /data-action="open-calendar-guard"/,
  'Las guardias del calendario deben ser clicables',
);

assert.match(
  appSource,
  /function guardActionModal/,
  'Al pulsar una guardia debe ofrecer cesión o intercambio',
);

assert.match(
  appSource,
  /selectedCalendarIssueFilters = new Set/,
  'Los filtros de incidencias del calendario deben permitir selección múltiple',
);

assert.match(
  appSource,
  /selectedCalendarIssueFilters\.has\(kind\)/,
  'Cada filtro debe mantener su estado activo de forma independiente',
);

const historySource = appSource.slice(
  appSource.indexOf('function historyPage'),
  appSource.indexOf('function activeGuards'),
);

assert.doesNotMatch(
  historySource,
  /Propostes registrades|Agenda més desviada|Dins del marge ±20%|Gestió a la proposta/,
  'El histórico sólo debe conservar el KPI global de equilibrio',
);

assert.match(
  appSource,
  /data-happiness-series[\s\S]*?happiness-chart-tooltip/,
  'El gráfico de felicidad debe permitir resaltar series y mostrar valores',
);

assert.match(
  appSource,
  /data-happiness-legend-name[\s\S]*?is-selected/,
  'La leyenda de felicidad debe permitir filtrar varias series',
);

assert.match(
  appSource,
  /data-happiness-legend-name[\s\S]*?is-previewed/,
  'La leyenda debe previsualizar la línea al pasar el ratón o el foco',
);

assert.match(
  appSource,
  /orderedFairnessAgendas[\s\S]*?right\.valueCount - left\.valueCount[\s\S]*?localeCompare/,
  'Las columnas de equilibrio deben ordenar primero las agendas con más valores y desempatar alfabéticamente',
);

assert.match(
  appSource,
  /name="periodMode"[\s\S]*?generationStartDate[\s\S]*?generationEndDate/,
  'La generación debe permitir escoger un mes o un período manual',
);
assert.match(
  appSource,
  /generationPeriodError[\s\S]*?mateix mes/,
  'La generación personalizada debe permanecer dentro del mismo mes natural',
);

const customDateHandlerSource = appSource.slice(
  appSource.indexOf("if (modal?.type === 'generation' && ['generationStartDate'"),
  appSource.indexOf('if (event.target.dataset.calendarFilterAll)'),
);
assert.doesNotMatch(
  customDateHandlerSource,
  /render\(\)/,
  'Escribir una fecha personalizada no debe reconstruir el modal ni perder el foco',
);

assert.match(
  appSource,
  /function guardCessionModal[\s\S]*?guardInlineImpact\(modal\.preview[\s\S]*?<textarea name="note"/,
  'La cesión debe mostrar el impacto antes de la nota',
);

assert.match(
  appSource,
  /function guardExchangeModal[\s\S]*?guardInlineImpact\(modal\.preview[\s\S]*?<textarea name="note"/,
  'El intercambio debe mostrar el impacto antes de la nota',
);

assert.match(
  appSource,
  /refreshGuardOperationPreview/,
  'Seleccionar una persona debe actualizar automáticamente el impacto',
);

assert.doesNotMatch(
  appSource,
  /modal = \{ type: 'guard-impact'/,
  'Cesión e intercambio no deben abrir una vista intermedia',
);

assert.doesNotMatch(
  appSource,
  /name="secondDate"/,
  'El intercambio con Exterior no debe pedir una nueva fecha',
);

assert.match(
  appSource,
  /guard-fixed-date[\s\S]*?type="hidden" name="date"/,
  'La fecha de una cesión existente debe mostrarse como dato fijo',
);

console.log('guard inline impact regression: ok');
