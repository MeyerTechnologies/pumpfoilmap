// Lokal test af Code.gs med et simuleret regneark:  node apps-script/test.mjs
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const HEADERS = ['id', 'vis', 'navn', 'status', 'start', 'koordinater', 'beskrivelse', 'medier', 'opdateret', 'note'];

function fakeSheet(rows) {
  const data = rows.map((r) => [...r]);
  const notes = {}, bg = {}, formats = {};
  const cell = (r, c) => (data[r - 1] || [])[c - 1] ?? '';
  const sheet = {
    data, notes, bg, formats,
    getLastRow: () => data.length,
    getLastColumn: () => Math.max(0, ...data.map((r) => r.length)),
    getMaxRows: () => 1000,
    getSheetId: () => 123,
    getParent: () => ({ getUrl: () => 'https://docs.google.com/spreadsheets/d/TEST' }),
    setFrozenRows() {},
    setConditionalFormatRules() {},
    getRange(r, c, nr = 1, nc = 1) {
      const range = {
        getRow: () => r, getLastRow: () => r + nr - 1,
        getValue: () => cell(r, c),
        getValues: () => Array.from({ length: nr }, (_, i) => Array.from({ length: nc }, (_, j) => cell(r + i, c + j))),
        setValue(v) { return range.setValues([[v]]); },
        setValues(vals) {
          vals.forEach((row, i) => row.forEach((v, j) => {
            while (data.length < r + i) data.push([]);
            data[r + i - 1][c + j - 1] = v;
          }));
          return range;
        },
        setNumberFormat(f) { formats[`${r},${c}`] = f; return range; },
        insertCheckboxes() { return range; },
        setDataValidation() { return range; },
        setNote(n) { notes[`${r},${c}`] = n; return range; },
        getNote: () => notes[`${r},${c}`] || '',
        setBackground(color) { bg[r] = color; return range; },
      };
      return range;
    },
  };
  return sheet;
}

function load({ sheet, geocode = {}, redirects = {} }) {
  const mails = [];
  const ctx = {
    console,
    SpreadsheetApp: {
      getActive: () => ({ getSheetByName: () => sheet, insertSheet: () => sheet, toast() {} }),
      newConditionalFormatRule: () => { const b = { whenFormulaSatisfied: () => b, setBackground: () => b, setRanges: () => b, build: () => ({}) }; return b; },
      newDataValidation: () => { const b = { requireValueInList: () => b, setAllowInvalid: () => b, build: () => ({}) }; return b; },
    },
    LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
    Utilities: { formatDate: () => '2026-09-23' },
    Session: { getEffectiveUser: () => ({ getEmail: () => 'ejer@example.com' }) },
    MailApp: { sendEmail: (to, subject, body) => mails.push({ to, subject, body }) },
    UrlFetchApp: { fetch: (url) => ({ getAllHeaders: () => (redirects[url] ? { Location: redirects[url] } : {}) }) },
    Maps: {
      newGeocoder: () => ({
        setRegion() { return this; }, setLanguage() { return this; },
        geocode: (q) => geocode[q]
          ? { status: 'OK', results: [{ geometry: { location: geocode[q] }, formatted_address: `${q} (adresse)` }] }
          : { status: 'ZERO_RESULTS', results: [] },
      }),
    },
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(new URL('./Code.gs', import.meta.url), 'utf8'), ctx);
  return { ctx, mails };
}

const plain = (x) => JSON.parse(JSON.stringify(x));
const nv = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, [v]]));
let passed = 0;
const test = (name, fn) => { fn(); passed++; console.log(`✓ ${name}`); };

// ---- Rene funktioner ----
const { ctx: f } = load({ sheet: fakeSheet([HEADERS]) });

test('koordinater fra tekst', () => {
  assert.deepEqual(plain(f.parseCoords_('56.1029787, 9.7835161')), { lat: 56.1029787, lng: 9.7835161 });
  assert.deepEqual(plain(f.parseCoords_('56,1029787 9,7835161')), { lat: 56.1029787, lng: 9.7835161 });
  assert.equal(f.parseCoords_('Knudhule Strand'), null);
});

test('koordinater fra Google Maps-links', () => {
  const place = 'https://www.google.com/maps/place/Knudhule+Strand/@56.1,9.7,15z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d56.1029787!4d9.7835161';
  assert.deepEqual(plain(f.coordsFromMapsUrl_(place)), { lat: 56.1029787, lng: 9.7835161 }, 'nålen (!3d/!4d) vinder over kortets midte');
  assert.deepEqual(plain(f.coordsFromMapsUrl_('https://maps.google.com/?q=56.16,10.21')), { lat: 56.16, lng: 10.21 });
  assert.deepEqual(plain(f.coordsFromMapsUrl_('https://www.google.com/maps/search/56.1629,+10.2039?entry=tts')), { lat: 56.1629, lng: 10.2039 });
  assert.deepEqual(plain(f.coordsFromMapsUrl_('https://www.google.com/maps/@56.2,10.1,12z')), { lat: 56.2, lng: 10.1 });
  assert.equal(f.placeNameFromMapsUrl_('https://www.google.com/maps/place/Egå+Marina/'), 'Egå Marina');
});

test('status og starttype fra svar', () => {
  assert.equal(f.statusFraSvar_('Ja, det virker'), 'Virker');
  assert.equal(f.statusFraSvar_('Ikke testet'), 'Ikke testet');
  assert.equal(f.statusFraSvar_('Ja, men det virker ikke'), 'Virker ikke');
  assert.equal(f.statusFraSvar_(''), 'Ikke testet');
  assert.equal(f.startFraSvar_('Dockstart'), 'Dock');
  assert.equal(f.startFraSvar_('Beachstart'), 'Beach');
  assert.equal(f.startFraSvar_(''), '');
});

test('spørgsmål matches selvom titlen har "?" eller "*"', () => {
  assert.equal(f.answer_({ 'Er spottet testet? *': ['Ja, det virker'] }, 'Er spottet testet?'), 'Ja, det virker');
  assert.equal(f.answer_({ 'Hvilken slags opdatering er der tale om?': ['Nyt spot'] }, 'Hvilken slags opdatering er der tale om'), 'Nyt spot');
  assert.equal(f.answer_({}, 'Placering'), '');
});

test('id er unikt og uden æøå', () => {
  assert.equal(f.slug_('Egå Marina (Roklubben)'), 'egaa-marina-roklubben');
  const sheet = fakeSheet([HEADERS, ['knudhule-badebro', true, 'Knudhule badebro']]);
  const { ctx } = load({ sheet });
  assert.equal(ctx.nytId_(sheet, 'Knudhule Badebro'), 'knudhule-badebro-2');
});

// ---- Hele flowet ----
test('nyt spot med kort Google Maps-link → kladde + mail, kontaktinfo kun i note', () => {
  const sheet = fakeSheet([HEADERS, ['knudhule-badebro', true, 'Knudhule badebro', 'Virker', 'Dock', '56.1029787, 9.7835161']]);
  const { ctx, mails } = load({
    sheet,
    redirects: { 'https://maps.app.goo.gl/abc': 'https://www.google.com/maps/place/Ry+Roklub/@56.09,9.76,17z/data=!3d56.0901!4d9.7612' },
  });
  const row = ctx.handleFormSubmit({ namedValues: nv({
    'Spot': 'Ry Roklub',
    'Hvilken slags opdatering er der tale om': 'Nyt spot',
    'Placering': 'https://maps.app.goo.gl/abc',
    'Starttype': 'Dockstart',
    'Er spottet testet?': 'Ja, det virker',
    'Beskrivelse': 'Fin lav bro.',
    'Billeder eller video': 'https://youtu.be/abcdefghijk',
    'Navn eller kontaktinfo': 'Hanne, 12345678',
  }) });
  assert.equal(row, 3);
  const r = Object.fromEntries(HEADERS.map((h, i) => [h, sheet.data[2][i]]));
  assert.equal(r.id, 'ry-roklub');
  assert.equal(r.vis, false);
  assert.equal(r.status, 'Virker');
  assert.equal(r.start, 'Dock');
  assert.equal(r.koordinater, '56.0901000, 9.7612000');
  assert.equal(r.medier, 'https://youtu.be/abcdefghijk');
  assert.ok(!JSON.stringify(sheet.data).includes('12345678'), 'kontaktinfo må ikke stå i cellerne (de udgives)');
  assert.match(sheet.notes['3,3'], /Hanne, 12345678/);
  assert.equal(mails.length, 1);
  assert.match(mails[0].subject, /Ry Roklub/);
  assert.match(mails[0].body, /range=A3/);
});

test('gammel formular uden placering → geokoder spottets navn', () => {
  const sheet = fakeSheet([HEADERS]);
  const { ctx } = load({ sheet, geocode: { 'Grenå Lagune, Danmark': { lat: 56.4035, lng: 10.9208 } } });
  ctx.handleFormSubmit({ namedValues: nv({ 'Spot': 'Grenå Lagune', 'Hvilken slags opdatering er der tale om': 'Nyt spot', 'Beskrivelse': 'Flydebro' }) });
  const r = sheet.data[1];
  assert.equal(r[5], '56.4035000, 10.9208000');
  assert.equal(r[3], 'Ikke testet');
  assert.match(r[9], /tjek placeringen/);
});

test('ukendt sted → tom koordinat og tydelig note', () => {
  const sheet = fakeSheet([HEADERS]);
  const { ctx, mails } = load({ sheet });
  ctx.handleFormSubmit({ namedValues: nv({ 'Spot': 'Hemmeligt sted', 'Hvilken slags opdatering er der tale om': 'Nyt spot', 'Beskrivelse': '?' }) });
  assert.equal(sheet.data[1][5], '');
  assert.match(sheet.data[1][9], /Mangler koordinater/);
  assert.match(mails[0].body, /MANGLER/);
});

test('ændringsforslag → note + orange række, ingen ny række', () => {
  const sheet = fakeSheet([HEADERS, ['egaa-marina-roklubben', true, 'Egå Marina (Roklubben)', 'Virker', 'Dock', '56.2, 10.2']]);
  const { ctx, mails } = load({ sheet });
  const row = ctx.handleFormSubmit({ namedValues: nv({
    'Spot': 'Egå Marina', 'Hvilken slags opdatering er der tale om': 'Ændring til eksisterende spot',
    'Beskrivelse': 'Broen er flyttet 20 m mod nord', 'Navn eller kontaktinfo': 'Ole',
  }) });
  assert.equal(row, 2);
  assert.equal(sheet.data.length, 2);
  assert.match(sheet.notes['2,3'], /Broen er flyttet/);
  assert.equal(sheet.bg[2], '#ffe0b2');
  assert.match(mails[0].subject, /Ændringsforslag/);
});

test('indmelding fra kortet finder spottet via id i klammer', () => {
  const sheet = fakeSheet([HEADERS,
    ['tange-soebad', true, 'Tange Søbad', 'Virker ikke', 'Dock', '56.33, 9.57'],
    ['fussing-soe', true, 'Fussing Sø', 'Ikke testet', 'Dock', '56.47, 9.84']]);
  const { ctx, mails } = load({ sheet });
  const row = ctx.handleFormSubmit({ namedValues: nv({
    'Spot': 'Fussing Sø [fussing-soe]', 'Hvilken slags opdatering er der tale om': 'Ændring til eksisterende spot',
    'Beskrivelse': 'Indmeldt fra kortet: Virker – prøvet på stedet\n\nLav bro, 2 m dybt', 'Navn eller kontaktinfo': '',
  }) });
  assert.equal(row, 3);
  assert.match(sheet.notes['3,3'], /Virker – prøvet på stedet/);
  assert.match(mails[0].subject, /Fussing Sø \[fussing-soe\]/);
});

console.log(`\n${passed} tests bestået`);
