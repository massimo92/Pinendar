import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

const root = process.cwd();
const args = parseArgs(process.argv.slice(2));
const cnhPath = resolve(root, args.cnh || 'data/hospitals/sources/cnh-2025.csv');
const pointsPath = resolve(root, 'data/hospitals/sources/btn-hospital-points.json');
const catalogPath = resolve(root, 'data/hospitals/catalog.json');
const areasPath = resolve(root, 'data/hospitals/areas.json');
const cachePath = args.cache || '/tmp/pinendar-hospital-build-cache.json';

const cnhRows = parseCsv(readFileSync(cnhPath, 'utf8'));
const points = args.btn ? extractBtnPoints(resolve(args.btn)) : JSON.parse(readFileSync(pointsPath, 'utf8'));
if (args.btn) writeJson(pointsPath, points);

const pointByCode = new Map(points.map((item) => [String(item.cnhCode), item]));
const checkpoint = existsSync(cachePath) ? JSON.parse(readFileSync(cachePath, 'utf8')) : { geocodes: {}, areas: {} };
checkpoint.geocodes ||= {};
checkpoint.areas ||= {};

const hospitals = cnhRows.filter(isPublicOrMixedHospital).map((row) => {
  const cnhCode = row['Código CNH'];
  const point = pointByCode.get(cnhCode);
  const geocode = point || checkpoint.geocodes[cnhCode] || null;
  return {
    id: cnhCode,
    cnhCode,
    ccnCode: row['Código CCN'],
    name: titleCase(row.Nombre),
    region: row['Comunidad Autónoma'],
    province: row.Provincia,
    municipality: row.Municipio,
    streetAddress: row['Dirección'],
    postcode: row['Código Postal'],
    phone: row['Teléfono'],
    beds: numberOrNull(row['Número de camas instaladas']),
    type: row['Tipo de Centro'],
    dependence: row['Dependencia Funcional'],
    concert: row.Concierto,
    latitude: geocode?.latitude ?? null,
    longitude: geocode?.longitude ?? null,
    coordinateSource: point ? 'IGN-CNIG BTN' : geocode ? 'IGN-CNIG CartoCiudad' : null
  };
});

const missingCoordinates = hospitals.filter((item) => !Number.isFinite(item.latitude) || !Number.isFinite(item.longitude));
let completed = 0;
await pool(missingCoordinates, 6, async (hospital) => {
  const geocode = await geocodeHospital(hospital);
  checkpoint.geocodes[hospital.cnhCode] = geocode;
  if (geocode) {
    hospital.latitude = geocode.latitude;
    hospital.longitude = geocode.longitude;
    hospital.coordinateSource = 'IGN-CNIG CartoCiudad';
  }
  completed += 1;
  if (completed % 15 === 0) writeJson(cachePath, checkpoint);
});
writeJson(cachePath, checkpoint);

const cadastralCandidates = hospitals.filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude) && !isForalTerritory(item));
completed = 0;
await pool(cadastralCandidates, 8, async (hospital) => {
  if (!(hospital.cnhCode in checkpoint.areas)) {
    const feature = await fetchCadastralArea(hospital);
    if (feature !== undefined) checkpoint.areas[hospital.cnhCode] = feature;
  }
  completed += 1;
  if (completed % 20 === 0) writeJson(cachePath, checkpoint);
});
writeJson(cachePath, checkpoint);

const areas = {};
for (const hospital of hospitals) {
  const feature = checkpoint.areas[hospital.cnhCode] || null;
  if (feature) areas[hospital.cnhCode] = feature;
  const properties = feature?.properties;
  hospital.areaAvailable = Boolean(feature);
  hospital.areaM2 = properties?.areaM2 ?? null;
  hospital.cadastralReference = properties?.cadastralReference ?? null;
  hospital.address = [hospital.streetAddress, [hospital.postcode, hospital.municipality].filter(Boolean).join(' '), hospital.province].filter(Boolean).join(', ');
}

const metadata = {
  generatedAt: new Date().toISOString(),
  count: hospitals.length,
  coordinates: hospitals.filter((item) => Number.isFinite(item.latitude)).length,
  cadastralAreas: Object.keys(areas).length,
  sources: [
    { name: 'Catálogo Nacional de Hospitales 2025', owner: 'Ministerio de Sanidad' },
    { name: 'Base Topográfica Nacional', owner: 'IGN-CNIG' },
    { name: 'Geocoder CartoCiudad', owner: 'IGN-CNIG' },
    { name: 'INSPIRE Cadastral Parcels', owner: 'Dirección General del Catastro' }
  ]
};
writeJson(catalogPath, { metadata, hospitals });
writeJson(areasPath, { metadata: { generatedAt: metadata.generatedAt, count: Object.keys(areas).length }, areas });
console.log(JSON.stringify(metadata));

function parseArgs(values) {
  const result = {};
  for (let index = 0; index < values.length; index += 2) result[values[index].replace(/^--/, '')] = values[index + 1];
  return result;
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted && char === '"' && text[index + 1] === '"') { field += '"'; index += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === ',' && !quoted) { row.push(field); field = ''; }
    else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && text[index + 1] === '\n') index += 1;
      row.push(field); field = '';
      if (row.some(Boolean)) rows.push(row);
      row = [];
    } else field += char;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const headers = rows.shift().map((value) => value.replace(/^\uFEFF/, ''));
  return rows.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] || ''])));
}

function extractBtnPoints(file) {
  const db = new DatabaseSync(file, { readOnly: true });
  const rows = db.prepare("SELECT id_hos, nombre, geometry FROM btn0590p_ser_ins WHERE tipo_0590 = '04' AND id_hos IS NOT NULL AND id_hos != ''").all();
  db.close();
  return rows.map((row) => {
    const { longitude, latitude } = decodeGpkgPoint(row.geometry);
    return { cnhCode: row.id_hos, name: row.nombre, longitude: round(longitude, 7), latitude: round(latitude, 7) };
  });
}

function decodeGpkgPoint(blob) {
  blob = Buffer.from(blob);
  const flags = blob[3];
  const envelopeValues = [0, 4, 6, 6, 8][(flags >> 1) & 7] || 0;
  const offset = 8 + envelopeValues * 8;
  const wkbLittleEndian = blob[offset] === 1;
  const readDouble = (position) => blob[wkbLittleEndian ? 'readDoubleLE' : 'readDoubleBE'](position);
  return { longitude: readDouble(offset + 5), latitude: readDouble(offset + 13) };
}

async function geocodeHospital(hospital) {
  const queries = [
    `${hospital.name}, ${hospital.municipality}`,
    `${hospital.name}, ${hospital.municipality}, ${hospital.province}`,
    `${hospital.streetAddress}, ${hospital.municipality}`,
    `${hospital.streetAddress}, ${hospital.municipality}, ${hospital.province}`,
    hospital.name
  ];
  for (const query of queries) {
    try {
      const url = new URL('https://www.cartociudad.es/geocoder/api/geocoder/candidates');
      url.searchParams.set('q', query);
      url.searchParams.set('limit', '8');
      const candidates = await fetchJson(url);
      const valid = candidates.filter((item) => validSpainPoint(Number(item.lat), Number(item.lng)));
      if (valid.length) {
        const best = valid.sort((left, right) => candidateScore(right, hospital) - candidateScore(left, hospital))[0];
        return { latitude: round(Number(best.lat), 7), longitude: round(Number(best.lng), 7) };
      }
    } catch {}
  }
  return null;
}

function candidateScore(candidate, hospital) {
  const text = normalized(`${candidate.address || ''} ${candidate.muni || ''} ${candidate.tip_via || ''}`);
  const nameTokens = normalized(hospital.name).split(' ').filter((item) => item.length > 3);
  let score = nameTokens.filter((token) => text.includes(token)).length;
  if (text.includes(normalized(hospital.municipality))) score += 5;
  if (normalized(candidate.tip_via).includes('hospital')) score += 9;
  if (candidate.type === 'toponimo') score += 3;
  if (candidate.postalCode === hospital.postcode) score += 3;
  return score;
}

async function fetchCadastralArea(hospital) {
  for (const delta of [0.000035, 0.0001]) {
    try {
      const url = new URL('https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx');
      for (const [key, value] of Object.entries({ service: 'WFS', version: '2.0.0', request: 'GetFeature', typenames: 'cp:CadastralParcel', srsname: 'EPSG::4326', bbox: `${hospital.latitude - delta},${hospital.longitude - delta},${hospital.latitude + delta},${hospital.longitude + delta}` })) url.searchParams.set(key, value);
      const response = await fetchWithRetry(url);
      const text = await response.text();
      const features = parseCadastralGml(text);
      if (!features.length) continue;
      const containing = features.find((feature) => geometryContains(feature.geometry, hospital.longitude, hospital.latitude));
      const feature = containing || features.sort((left, right) => (left.properties.areaM2 || Infinity) - (right.properties.areaM2 || Infinity))[0];
      feature.properties.hospitalId = hospital.cnhCode;
      return feature;
    } catch {}
  }
  return null;
}

function parseCadastralGml(text) {
  const blocks = [...text.matchAll(/<cp:CadastralParcel\b[^>]*>([\s\S]*?)<\/cp:CadastralParcel>/g)].map((match) => match[1]);
  return blocks.map((block) => {
    const polygonBlocks = [...block.matchAll(/<gml:PolygonPatch\b[^>]*>([\s\S]*?)<\/gml:PolygonPatch>/g)].map((match) => match[1]);
    const polygons = polygonBlocks.map((polygon) => {
      const exterior = polygon.match(/<gml:exterior\b[^>]*>([\s\S]*?)<\/gml:exterior>/)?.[1];
      const interiors = [...polygon.matchAll(/<gml:interior\b[^>]*>([\s\S]*?)<\/gml:interior>/g)].map((match) => match[1]);
      return [exterior, ...interiors].filter(Boolean).map(parsePosList).filter((ring) => ring.length >= 4);
    }).filter((polygon) => polygon.length);
    const areaM2 = numberOrNull(block.match(/<cp:areaValue\b[^>]*>([^<]+)</)?.[1]);
    const cadastralReference = block.match(/<cp:nationalCadastralReference\b[^>]*>([^<]+)</)?.[1] || null;
    return { type: 'Feature', geometry: { type: 'MultiPolygon', coordinates: polygons }, properties: { cadastralReference, areaM2, source: 'Dirección General del Catastro' } };
  }).filter((feature) => feature.geometry.coordinates.length);
}

function parsePosList(block) {
  const value = block.match(/<gml:posList\b[^>]*>([\s\S]*?)<\/gml:posList>/)?.[1];
  if (!value) return [];
  const numbers = value.trim().split(/\s+/).map(Number);
  const coordinates = [];
  for (let index = 0; index < numbers.length; index += 2) coordinates.push([round(numbers[index + 1], 6), round(numbers[index], 6)]);
  return coordinates;
}

function geometryContains(geometry, longitude, latitude) {
  return geometry.coordinates.some((polygon) => polygon[0] && pointInRing(polygon[0], longitude, latitude) && !polygon.slice(1).some((ring) => pointInRing(ring, longitude, latitude)));
}

function pointInRing(ring, x, y) {
  let inside = false;
  for (let left = 0, right = ring.length - 1; left < ring.length; right = left, left += 1) {
    const [x1, y1] = ring[left];
    const [x2, y2] = ring[right];
    if ((y1 > y) !== (y2 > y) && x < ((x2 - x1) * (y - y1)) / (y2 - y1) + x1) inside = !inside;
  }
  return inside;
}

async function fetchJson(url) {
  const response = await fetchWithRetry(url);
  return response.json();
}

async function fetchWithRetry(url) {
  let lastError;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(25000), headers: { 'user-agent': 'Pinendar hospital catalog builder' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response;
    } catch (error) {
      lastError = error;
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 350 * (attempt + 1)));
    }
  }
  throw lastError;
}

async function pool(items, concurrency, worker) {
  let index = 0;
  await Promise.all(Array.from({ length: concurrency }, async () => {
    while (index < items.length) {
      const current = items[index];
      index += 1;
      await worker(current);
    }
  }));
}

function writeJson(file, value) {
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(value)}\n`);
}

function normalized(value = '') {
  return String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function titleCase(value = '') {
  const titled = value.toLocaleLowerCase('es').replace(/(^|[\s(/'-])([a-záéíóúüñç])/giu, (_, prefix, letter) => `${prefix}${letter.toLocaleUpperCase('es')}`);
  return titled.replace(/\b(De|Del|Dels|La|Las|Les|El|Els|Los|Y|I|E)\b/g, (word, _match, offset) => offset === 0 ? word : word.toLocaleLowerCase('es')).replace(/\bD'/g, "d'");
}

function isForalTerritory(hospital) {
  const value = normalized(`${hospital.region} ${hospital.province}`);
  return /pais vasco|euskadi|navarra|araba|alava|bizkaia|gipuzkoa/.test(value);
}

function isPublicOrMixedHospital(row) {
  const dependence = normalized(row['Dependencia Funcional']);
  const concert = normalized(row.Concierto);
  const publicDependence = /servicios e institutos de salud|public|municipio|ministerio de defensa|diputacion|cabildo|ingesa/.test(dependence);
  const publicNetwork = /red de utilizacion publica|concierto sustitutorio/.test(concert);
  return publicDependence || publicNetwork;
}

function validSpainPoint(latitude, longitude) {
  return Number.isFinite(latitude) && Number.isFinite(longitude) && latitude > 27 && latitude < 44.5 && longitude > -19 && longitude < 5;
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function round(value, decimals) {
  return Math.round(value * 10 ** decimals) / 10 ** decimals;
}
