import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

globalThis.document = { querySelector: () => null };
const { navTemplate } = await import('../public/views.js');

const index = readFileSync(new URL('../public/index.html', import.meta.url), 'utf8');
const mobileCss = readFileSync(new URL('../public/mobile.css', import.meta.url), 'utf8');

test('loads the smartphone stylesheet after the desktop styles', () => {
  assert.match(index, /calendar\.css[^>]+>\s*<link rel="stylesheet" href="\/mobile\.css/);
});

test('removes the desktop minimum width and provides fixed mobile navigation', () => {
  assert.match(mobileCss, /@media \(max-width: 800px\)/);
  assert.match(mobileCss, /body \{ min-width: 0/);
  assert.match(mobileCss, /\.sidebar \{[\s\S]*position: fixed/);
  assert.match(mobileCss, /env\(safe-area-inset-bottom\)/);
});

test('mobile calendar uses a one-column agenda layout', () => {
  assert.match(mobileCss, /\.calendar-grid, \.calendar-shell\.view-week \.calendar-grid \{[\s\S]*grid-template-columns: 1fr/);
  assert.match(mobileCss, /\.calendar-shell\.view-month \.calendar-day\.outside \{ display: none/);
});

test('navigation exposes icons and current-page semantics', () => {
  const html = navTemplate({ page: 'calendar', language: 'ca', labelFor: (value) => value });
  assert.match(html, /class="nav-icon"><svg/);
  assert.match(html, /aria-label="Calendari"/);
  assert.match(html, /aria-current="page"/);
  assert.match(html, /aria-label="Navegació principal"/);
  assert.doesNotMatch(html, /nav-mobile-label/);
});
