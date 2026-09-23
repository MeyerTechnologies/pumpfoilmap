/**
 * Pump foil DK – Google Apps Script til regnearket med formular-svarene.
 *
 *  1. Når nogen udfylder Google Formen, lægges svaret ind i fanen "Spots" som kladde
 *     ("vis" er ikke markeret). Koordinater findes ud fra Google Maps-link, koordinater eller adresse.
 *  2. Du får en mail med et link direkte til rækken. Sæt flueben i "vis" for at publicere.
 *  3. Ændringsforslag til eksisterende spots gemmes som note på spottets række + mail.
 *
 * Kontaktinfo skrives kun i cellenoter (kommer ikke med, når fanen udgives som CSV).
 *
 * Installation: se README.md → "Formular-scriptet".
 */

const CONFIG = {
  SPOTS_SHEET: 'Spots',
  NOTIFY_EMAIL: '', // tom = den Google-konto der har installeret scriptet
  TIMEZONE: 'Europe/Copenhagen',
  // Spørgsmålenes titler i Google Formen. Ret dem her, hvis du omdøber et spørgsmål.
  QUESTIONS: {
    navn: 'Spot',
    type: 'Hvilken slags opdatering er der tale om',
    placering: 'Placering',
    start: 'Starttype',
    status: 'Er spottet testet?',
    beskrivelse: 'Beskrivelse',
    medier: 'Billeder eller video',
    kontakt: 'Navn eller kontaktinfo',
  },
};

const HEADERS = ['id', 'vis', 'navn', 'status', 'start', 'koordinater', 'beskrivelse', 'medier', 'opdateret', 'note'];
const STATUS_VALUES = ['Virker', 'Ikke testet', 'Virker ikke'];
const START_VALUES = ['Dock', 'Rock', 'Jump', 'Beach', 'Andet'];
const DK = { minLat: 54.4, maxLat: 57.9, minLng: 7.8, maxLng: 15.3 };
const SHOW = /^(true|sand|ja|yes|x|1|✓|✔|☑)$/i;
const DRAFT_COLOR = '#fff4cc';
const CHANGE_COLOR = '#ffe0b2';

// ---------- Menu og installation ----------

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Pumpfoil')
    .addItem('Installer (kør én gang)', 'installer')
    .addItem('Find koordinater for markerede rækker', 'findKoordinaterForMarkerede')
    .addToUi();
}

function installer() {
  const ss = SpreadsheetApp.getActive();
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'handleFormSubmit')
    .forEach((t) => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('handleFormSubmit').forSpreadsheet(ss).onFormSubmit().create();
  klargoerArk_(spotsSheet_());
  SpreadsheetApp.getUi().alert('Klar! Nye formular-svar lægges nu i fanen "Spots" som kladder (gul baggrund).');
}

/** Overskrifter, tjekbokse i "vis", dropdowns for status/start og gul markering af kladder. */
function klargoerArk_(sheet) {
  if (sheet.getLastRow() === 0) sheet.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]);
  const cols = columns_(sheet);
  const missing = HEADERS.filter((h) => !cols[h]);
  if (missing.length) throw new Error(`Fanen "${CONFIG.SPOTS_SHEET}" mangler kolonnerne: ${missing.join(', ')}`);
  sheet.setFrozenRows(1);

  const rows = sheet.getLastRow() - 1;
  const maxRows = sheet.getMaxRows() - 1;
  if (rows > 0) {
    // CSV-import giver tekst ("TRUE"/"SAND") – lav det om til rigtige tjekbokse.
    const vis = sheet.getRange(2, cols.vis, rows, 1);
    const values = vis.getValues().map(([v]) => [v === true || SHOW.test(String(v).trim())]);
    vis.insertCheckboxes();
    vis.setValues(values);
  }
  sheet.getRange(2, cols.koordinater, maxRows, 1).setNumberFormat('@');
  sheet.getRange(2, cols.status, maxRows, 1).setDataValidation(listRule_(STATUS_VALUES));
  sheet.getRange(2, cols.start, maxRows, 1).setDataValidation(listRule_(START_VALUES));

  const idCol = letter_(cols.id), visCol = letter_(cols.vis);
  const rule = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied(`=AND($${idCol}2<>"", $${visCol}2=FALSE)`)
    .setBackground(DRAFT_COLOR)
    .setRanges([sheet.getRange(2, 1, maxRows, sheet.getLastColumn())])
    .build();
  sheet.setConditionalFormatRules([rule]);
}

// ---------- Formular-svar ----------

function handleFormSubmit(e) {
  const get = (key) => answer_(e.namedValues, CONFIG.QUESTIONS[key]);
  const sheet = spotsSheet_();
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    if (/ændring|eksisterende/i.test(get('type'))) return registrerAendring_(sheet, get);
    return registrerNytSpot_(sheet, get);
  } finally {
    lock.releaseLock();
  }
}

function registrerNytSpot_(sheet, get) {
  const navn = get('navn');
  const placering = findPlacering_(get('placering'), navn);
  const spot = {
    id: nytId_(sheet, navn),
    vis: false,
    navn,
    status: statusFraSvar_(get('status')),
    start: startFraSvar_(get('start')),
    koordinater: placering.koordinater,
    beskrivelse: get('beskrivelse'),
    medier: links_(get('medier')).join('\n'),
    opdateret: today_(),
    note: ['Fra formularen', placering.note].filter(Boolean).join(' · '),
  };
  const row = appendSpot_(sheet, spot);
  sheet.getRange(row, columns_(sheet).navn).setNote(`Indsendt ${today_()}${get('kontakt') ? ` af ${get('kontakt')}` : ''}`);

  notify_(`Nyt pumpfoil-spot: ${navn || '(uden navn)'}`, [
    `${navn || '(uden navn)'} er lagt ind som kladde i regnearket.`,
    '',
    `Status: ${spot.status} · Start: ${spot.start || '?'}`,
    `Koordinater: ${spot.koordinater || 'MANGLER'}${placering.note ? ` (${placering.note})` : ''}`,
    spot.koordinater ? `Tjek placeringen: ${mapsLink_(spot.koordinater)}` : '',
    '',
    'Beskrivelse:',
    spot.beskrivelse || '(ingen)',
    spot.medier ? `\nMedier:\n${spot.medier}` : '',
    get('kontakt') ? `\nIndsendt af: ${get('kontakt')}` : '',
    '',
    'Godkend ved at sætte flueben i "vis":',
    rowUrl_(sheet, row),
  ]);
  return row;
}

function registrerAendring_(sheet, get) {
  const navn = get('navn');
  const row = findSpotRow_(sheet, navn);
  const tekst = [
    `Ændringsforslag ${today_()}${get('kontakt') ? ` fra ${get('kontakt')}` : ''}:`,
    get('beskrivelse'),
    get('placering') ? `Placering: ${get('placering')}` : '',
    get('status') ? `Status: ${get('status')}` : '',
    get('start') ? `Start: ${get('start')}` : '',
    get('medier') ? `Medier: ${get('medier')}` : '',
  ].filter(Boolean).join('\n');

  if (row) {
    const cell = sheet.getRange(row, columns_(sheet).navn);
    cell.setNote([cell.getNote(), tekst].filter(Boolean).join('\n\n'));
    sheet.getRange(row, 1, 1, sheet.getLastColumn()).setBackground(CHANGE_COLOR);
  }
  notify_(`Ændringsforslag: ${navn || '(uden navn)'}`, [
    row ? `Forslaget er gemt som note på rækken (orange baggrund):` : `Kunne ikke finde et spot der hedder "${navn}" – find det selv i arket:`,
    rowUrl_(sheet, row || 1),
    '',
    tekst,
    '',
    'Fjern den orange baggrund, når du har rettet spottet.',
  ]);
  return row;
}

/** Tilføjer et spot nederst i fanen. Kolonnerne findes via overskrifterne, så rækkefølgen er ligegyldig. */
function appendSpot_(sheet, spot) {
  const cols = columns_(sheet);
  const row = sheet.getLastRow() + 1;
  const values = new Array(sheet.getLastColumn()).fill('');
  Object.keys(spot).forEach((key) => { if (cols[key]) values[cols[key] - 1] = spot[key]; });
  sheet.getRange(row, cols.koordinater).setNumberFormat('@');
  sheet.getRange(row, cols.opdateret).setNumberFormat('@');
  sheet.getRange(row, 1, 1, values.length).setValues([values]);
  sheet.getRange(row, cols.vis).insertCheckboxes();
  return row;
}

// ---------- Menu: find koordinater ----------

/** Markér rækker, hvor "koordinater" er tom eller indeholder et Google Maps-link/adresse, og kør denne. */
function findKoordinaterForMarkerede() {
  const sheet = spotsSheet_();
  const cols = columns_(sheet);
  const range = sheet.getActiveRange();
  let fundet = 0, fejl = 0;
  for (let row = Math.max(2, range.getRow()); row <= range.getLastRow(); row++) {
    const cell = sheet.getRange(row, cols.koordinater);
    const current = String(cell.getValue()).trim();
    if (parseCoords_(current) && !/https?:\/\//.test(current)) continue;
    const navn = String(sheet.getRange(row, cols.navn).getValue()).trim();
    const placering = findPlacering_(current, navn);
    if (!placering.koordinater) { fejl++; continue; }
    cell.setNumberFormat('@').setValue(placering.koordinater);
    if (placering.note) sheet.getRange(row, cols.note).setValue(placering.note);
    fundet++;
  }
  SpreadsheetApp.getActive().toast(`Fandt koordinater for ${fundet} række(r)${fejl ? `, ${fejl} kunne ikke findes` : ''}.`, 'Pumpfoil');
}

// ---------- Placering ----------

/**
 * Finder koordinater ud fra (i prioriteret rækkefølge):
 * Google Maps-link (også korte maps.app.goo.gl-links) → koordinater i teksten → adresse/stednavn → spottets navn.
 * Returnerer { koordinater: '56.1029787, 9.7835161' | '', note: '' }.
 */
function findPlacering_(tekst, navn) {
  tekst = String(tekst || '').trim();
  const url = (tekst.match(/https?:\/\/\S+/) || [])[0];
  if (url) {
    const fuldUrl = /goo\.gl|g\.co\//.test(url) ? resolveRedirects_(url) : url;
    const fraLink = coordsFromMapsUrl_(fuldUrl);
    if (fraLink) return result_(fraLink, '');
    const sted = placeNameFromMapsUrl_(fuldUrl);
    if (sted) {
      const geo = geocode_(sted);
      if (geo) return result_(geo, `fundet ud fra stednavnet i linket – tjek placeringen`);
    }
  }
  const direkte = parseCoords_(tekst.replace(/https?:\/\/\S+/g, ''));
  if (direkte) return result_(direkte, '');

  const soeg = tekst.replace(/https?:\/\/\S+/g, '').trim() || String(navn || '').trim();
  if (soeg) {
    const geo = geocode_(soeg);
    if (geo) return result_(geo, `fundet ud fra "${soeg}" (${geo.adresse}) – tjek placeringen`);
  }
  return { koordinater: '', note: 'Mangler koordinater – indsæt dem fra Google Maps' };
}

function result_(pos, note) {
  const udenforDK = pos.lat < DK.minLat || pos.lat > DK.maxLat || pos.lng < DK.minLng || pos.lng > DK.maxLng;
  return {
    koordinater: `${pos.lat.toFixed(7)}, ${pos.lng.toFixed(7)}`,
    note: [note, udenforDK ? 'OBS: ligger uden for Danmark?' : ''].filter(Boolean).join(' · '),
  };
}

/** "56.1029787, 9.7835161" (som Google Maps kopierer) eller dansk decimalkomma "56,1029787 9,7835161". */
function parseCoords_(tekst) {
  const s = String(tekst || '');
  let m = s.match(/-?\d{1,3}\.\d+/g);
  if (!m || m.length < 2) m = (s.match(/-?\d{1,3},\d+/g) || []).map((x) => x.replace(',', '.'));
  if (!m || m.length < 2) return null;
  const lat = Number(m[0]), lng = Number(m[1]);
  return Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? { lat, lng } : null;
}

function coordsFromMapsUrl_(url) {
  let s = String(url || '');
  try { s = decodeURIComponent(s); } catch (err) { /* behold som den er */ }
  const patterns = [
    /!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/,                                    // selve nålen på et sted
    /[?&](?:q|query|ll|destination|center)=(-?\d+\.\d+),\s*\+?(-?\d+\.\d+)/,
    /\/(?:search|place|dir)\/(-?\d+\.\d+),\s*\+?(-?\d+\.\d+)/,
    /@(-?\d+\.\d+),(-?\d+\.\d+)/,                                         // kortets midte
  ];
  for (const re of patterns) {
    const m = s.match(re);
    if (m) return { lat: Number(m[1]), lng: Number(m[2]) };
  }
  return null;
}

function placeNameFromMapsUrl_(url) {
  const m = String(url || '').match(/\/maps\/place\/([^/@?]+)/) || String(url || '').match(/[?&]q=([^&]+)/);
  if (!m) return '';
  try { return decodeURIComponent(m[1].replace(/\+/g, ' ')).trim(); } catch (err) { return m[1]; }
}

function resolveRedirects_(url) {
  try {
    for (let i = 0; i < 5; i++) {
      const res = UrlFetchApp.fetch(url, { followRedirects: false, muteHttpExceptions: true });
      const headers = res.getAllHeaders();
      const next = headers.Location || headers.location;
      if (!next) break;
      url = Array.isArray(next) ? next[0] : next;
    }
  } catch (err) {
    console.warn('Kunne ikke følge link', url, err);
  }
  return url;
}

function geocode_(query) {
  const q = /danmark|denmark/i.test(query) ? query : `${query}, Danmark`;
  const res = Maps.newGeocoder().setRegion('dk').setLanguage('da').geocode(q);
  if (res.status !== 'OK' || !res.results.length) return null;
  const top = res.results[0];
  return { lat: top.geometry.location.lat, lng: top.geometry.location.lng, adresse: top.formatted_address };
}

// ---------- Hjælpere ----------

function statusFraSvar_(svar) {
  const s = String(svar || '').toLowerCase();
  if (!s || s.includes('ikke test') || s.includes('utestet')) return 'Ikke testet';
  if (s.includes('ikke')) return 'Virker ikke';
  if (s.includes('virk') || s.includes('fung') || s.includes('ja')) return 'Virker';
  return 'Ikke testet';
}

function startFraSvar_(svar) {
  const s = String(svar || '').toLowerCase();
  if (s.includes('dock') || s.includes('bro')) return 'Dock';
  if (s.includes('rock') || s.includes('sten')) return 'Rock';
  if (s.includes('jump') || s.includes('løb')) return 'Jump';
  if (s.includes('beach') || s.includes('strand')) return 'Beach';
  return s ? 'Andet' : '';
}

function answer_(namedValues, title) {
  const norm = (t) => String(t || '').toLowerCase().replace(/[?:*]/g, '').replace(/\s+/g, ' ').trim();
  const wanted = norm(title);
  const key = Object.keys(namedValues || {}).find((k) => norm(k) === wanted)
    || Object.keys(namedValues || {}).find((k) => norm(k).startsWith(wanted));
  return key ? [].concat(namedValues[key]).join(', ').trim() : '';
}

function links_(tekst) {
  return String(tekst || '').match(/https?:\/\/[^\s,]+/g) || [];
}

function slug_(tekst) {
  return String(tekst || '').toLowerCase()
    .replace(/æ/g, 'ae').replace(/ø/g, 'oe').replace(/å/g, 'aa')
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'spot';
}

function nytId_(sheet, navn) {
  const cols = columns_(sheet);
  const rows = sheet.getLastRow() - 1;
  const ids = new Set(rows > 0 ? sheet.getRange(2, cols.id, rows, 1).getValues().map(([v]) => String(v)) : []);
  const base = slug_(navn);
  let id = base, i = 2;
  while (ids.has(id)) id = `${base}-${i++}`;
  return id;
}

function findSpotRow_(sheet, navn) {
  const cols = columns_(sheet);
  const rows = sheet.getLastRow() - 1;
  if (!navn || rows < 1) return null;
  const names = sheet.getRange(2, cols.navn, rows, 1).getValues().map(([v]) => slug_(v));
  const wanted = slug_(navn);
  let i = names.indexOf(wanted);
  if (i < 0) i = names.findIndex((n) => n && (n.includes(wanted) || wanted.includes(n)));
  return i < 0 ? null : i + 2;
}

function spotsSheet_() {
  const ss = SpreadsheetApp.getActive();
  return ss.getSheetByName(CONFIG.SPOTS_SHEET) || ss.insertSheet(CONFIG.SPOTS_SHEET);
}

function columns_(sheet) {
  const lastCol = sheet.getLastColumn();
  if (!lastCol) return {};
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const cols = {};
  headers.forEach((h, i) => { const k = String(h).trim().toLowerCase(); if (k && !cols[k]) cols[k] = i + 1; });
  return cols;
}

function listRule_(values) {
  return SpreadsheetApp.newDataValidation().requireValueInList(values, true).setAllowInvalid(true).build();
}

function letter_(col) {
  let s = '';
  for (let n = col; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}

function today_() {
  return Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd');
}

function mapsLink_(koordinater) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(koordinater.replace(/\s/g, ''))}`;
}

function rowUrl_(sheet, row) {
  return `${sheet.getParent().getUrl()}#gid=${sheet.getSheetId()}&range=A${row}`;
}

function notify_(subject, lines) {
  const to = CONFIG.NOTIFY_EMAIL || Session.getEffectiveUser().getEmail();
  MailApp.sendEmail(to, subject, lines.join('\n').replace(/\n{3,}/g, '\n\n').trim());
}
