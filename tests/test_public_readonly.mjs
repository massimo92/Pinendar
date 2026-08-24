import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

globalThis.document = { querySelector: () => null };
const { headerTemplate, navTemplate, shellTemplate } = await import('../public/views.js');

test('public navigation only exposes calendar and history', () => {
  const html = navTemplate({ page: 'calendar', language: 'ca', labelFor: (value) => value, publicAccess: true });

  assert.match(html, /data-page="calendar"/);
  assert.match(html, /data-page="history"/);
  assert.doesNotMatch(html, /data-page="guards"|data-page="team"|data-page="setup"/);
  assert.match(html, /només lectura/);
});

test('public header has no account or mutation controls', () => {
  const html = headerTemplate({ title: 'Calendari', subtitle: '', actions: '<button>Genera</button>', language: 'ca', account: { username: 'secret' }, publicAccess: true });

  assert.match(html, /Només lectura/);
  assert.doesNotMatch(html, /Genera|secret|logout|open-public-link|open-recovery-code/);
});

test('public shell marks the page for read-only behavior', () => {
  assert.match(shellTemplate({ navigation: '', view: '', modal: '', publicAccess: true }), /public-readonly/);
});

test('public calendar removes mutation controls and makes events inert', () => {
  const source = fs.readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');

  assert.match(source, /No es pot modificar ni generar contingut/);
  assert.match(source, /button\.calendar-event/);
  assert.match(source, /button\.replaceWith\(replacement\)/);
  assert.match(source, /isPublicAccess\(\).*calendar-event/);
  assert.match(source, /if \(isPublicAccess\(\)\) \{ event\.preventDefault\(\); return; \}/);
});

test('owner sharing dialog supports copy, native share, QR, and regeneration', () => {
  const source = fs.readFileSync(new URL('../public/app.js', import.meta.url), 'utf8');

  for (const action of ['copy-public-link', 'share-public-link', 'share-public-qr', 'regenerate-public-link']) {
    assert.match(source, new RegExp(`data-action="${action}"`));
  }
  assert.match(source, /new window\.QRCode/);
});
