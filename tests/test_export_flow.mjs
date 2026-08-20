import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');

assert.match(source, /data-action="open-export"[\s\S]*?data-export-format="csv"/);
assert.match(source, /function exportRows\(bounds\)[\s\S]*?calendarVacancies\(\)/);
assert.match(source, /function exportModal\(\)[\s\S]*?name="startDate"[\s\S]*?name="endDate"/);
assert.doesNotMatch(source, /També s'exporten les agendes sense persona assignada/);
assert.match(source, /function holidayCalendar\(\)[\s\S]*?data-action="toggle-holiday"/);
assert.match(source, /data-action="toggle-holiday"[\s\S]*?disabled/);
assert.match(source, /const locked = key <= today/);
assert.match(source, /date <= dateKey\(new Date\(\)\)/);
assert.match(source, /function refreshHolidayCalendar\(\)[\s\S]*?outerHTML = holidayCalendar\(\)/);
assert.match(source, /holidays-panel-head[\s\S]*?card-kicker">CALENDARI[\s\S]*?<h2>Festius<\/h2>[\s\S]*?holidays-calendar-wrap/);
assert.match(source, /function generationMissingConditions[\s\S]*?calendarGuards\(\)[\s\S]*?calendarAbsences\(\)/);
assert.match(source, /confirm-generation-conditions/);
assert.match(source, /function generationConditionsWarningModal\(\)[\s\S]*?generation-warning-icon[\s\S]*?Torna enrere/);
assert.match(source, /existingGenerationCondition[\s\S]*?existing-conditions/);

console.log('export and generation safeguards regression: ok');
