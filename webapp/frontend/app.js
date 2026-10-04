/* EviChange GIS — frontend (plain JavaScript, no build step).
 * Sections: 1 tile sources · 2 map + basemap · 3 layer registry + Contents pane
 * 4 identify/popups · 5 attribute table · 6 sketch (measure + draw) · 7 swipe
 * 8 AI report panel · 9 add data · 10 panel/toolbar wiring · 11 start-up
 * The change explorer (change-type colours/icons, "Find changes" panel, region card) is in explore.js.
 */
'use strict';

// ---------- 1. Tile sources (basemaps + imagery) ----------
function s2cloudless(year) {
  const layer = year === 2016 ? 's2cloudless_3857' : `s2cloudless-${year}_3857`;
  return {
    name: `Sentinel-2 ${year} (cloudless)`,
    tiles: [`https://tiles.maps.eox.at/wmts/1.0.0/${layer}/default/g/{z}/{y}/{x}.jpg`],
    maxzoom: 15,
    attribution: `Sentinel-2 cloudless ${year} by <a href="https://s2maps.eu" target="_blank">EOX IT Services GmbH</a> (contains modified Copernicus Sentinel data ${year})`,
  };
}
const TILES = {
  s2_2018: s2cloudless(2018),
  s2_2022: s2cloudless(2022),
  osm: { name: 'Streets (OpenStreetMap)', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], maxzoom: 19,
         attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors' },
  topo: { name: 'Topographic (OpenTopoMap)', tiles: ['a', 'b', 'c'].map(s => `https://${s}.tile.opentopomap.org/{z}/{x}/{y}.png`), maxzoom: 17,
          attribution: '© OpenStreetMap contributors, SRTM · style © <a href="https://opentopomap.org" target="_blank">OpenTopoMap</a> (CC-BY-SA)' },
};
const BASEMAPS = ['s2_2022', 's2_2018', 'osm', 'topo', 'none'];
const HOME = { center: [107.31, 21.04], zoom: 11.3 };

const state = {
  basemap: 's2_2022',
  layers: [],               // index 0 = top of the map
  panel: null,              // which right-hand panel is open
  sketch: null,             // active measure/draw session
  swipe: { on: false, left: 's2_2018', right: 's2_2022', x: null, map: null },
  selected: new Set(),      // selected change-region ids for the AI report
  condition: 'gated',
  threshold: 0.5,
  tableLayerId: null,
};
const $ = sel => document.querySelector(sel);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---------- 2. Map + basemap ----------
const map = new maplibregl.Map({
  container: 'map',
  style: { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#dfe3e8' } }] },
  center: HOME.center, zoom: HOME.zoom,
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl(), 'top-right');
map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
window.evimap = map; // handy for debugging in the browser console

function rasterSource(key) {
  const t = TILES[key];
  return { type: 'raster', tiles: t.tiles, tileSize: 256, maxzoom: t.maxzoom, attribution: t.attribution };
}

function setBasemap(key) {
  if (map.getLayer('basemap')) map.removeLayer('basemap');
  if (map.getSource('basemap')) map.removeSource('basemap');
  state.basemap = key;
  if (key !== 'none') {
    map.addSource('basemap', rasterSource(key));
    const above = map.getStyle().layers[1];            // keep basemap directly above the background
    map.addLayer({ id: 'basemap', type: 'raster', source: 'basemap' }, above ? above.id : undefined);
  }
  if (state.panel === 'basemap') renderPanel();
}

// ---------- 3. Layer registry + Contents pane ----------
const PALETTE = ['#2563eb', '#9333ea', '#db2777', '#0891b2', '#65a30d', '#ea580c'];
let userLayerCount = 0;

function addRasterLayer({ id, name, tileKey, visible = false }) {
  map.addSource(id, rasterSource(tileKey));
  map.addLayer({ id, type: 'raster', source: id, layout: { visibility: visible ? 'visible' : 'none' } });
  state.layers.unshift({ id, name, kind: 'raster', mapLayers: [id], visible, opacity: 1, removable: false });
  applyOrder();
}

function addVectorLayer({ id, name, data, style = 'auto', visible = true, removable = false }) {
  data.features.forEach((f, i) => { f.properties = { ...(f.properties || {}), __fid: i }; });
  map.addSource(id, { type: 'geojson', data, promoteId: '__fid' });
  const vis = { visibility: visible ? 'visible' : 'none' };
  const hl = ['any', ['boolean', ['feature-state', 'selected'], false], ['boolean', ['feature-state', 'hl'], false]];
  const mapLayers = [];
  const add = spec => { map.addLayer({ ...spec, source: id, layout: { ...vis, ...(spec.layout || {}) } }); mapLayers.push(spec.id); };
  let base = {};
  if (style === 'change_type') {
    const paint = changeTypePaint(hl);
    base = { fill: paint.fill['fill-opacity'] };
    add({ id: `${id}-fill`, type: 'fill', paint: paint.fill });
    add({ id: `${id}-line`, type: 'line', paint: paint.line });
  } else if (style === 'confidence') {
    base = { fill: 0.55 };
    add({ id: `${id}-fill`, type: 'fill', paint: {
      'fill-color': ['interpolate', ['linear'], ['get', 'mean_conf'], 0.3, '#fde68a', 0.6, '#f97316', 0.9, '#b91c1c'],
      'fill-opacity': base.fill } });
    add({ id: `${id}-line`, type: 'line', paint: {
      'line-color': ['case', hl, '#22d3ee', '#7f1d1d'], 'line-width': ['case', hl, 3.5, 1.2] } });
  } else if (style === 'outline') {
    add({ id: `${id}-line`, type: 'line', paint: { 'line-color': '#5eead4', 'line-width': 2, 'line-dasharray': [3, 2] } });
  } else {
    const color = PALETTE[userLayerCount++ % PALETTE.length];
    base = { fill: 0.3 };
    add({ id: `${id}-fill`, type: 'fill', filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': color, 'fill-opacity': base.fill } });
    add({ id: `${id}-line`, type: 'line', filter: ['!=', ['geometry-type'], 'Point'], paint: {
      'line-color': ['case', hl, '#22d3ee', color], 'line-width': ['case', hl, 3.5, 1.5] } });
    add({ id: `${id}-pt`, type: 'circle', filter: ['==', ['geometry-type'], 'Point'], paint: {
      'circle-color': color, 'circle-radius': ['case', hl, 7, 4.5], 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
  }
  state.layers.unshift({ id, name, kind: 'vector', mapLayers, visible, opacity: 1, removable, data, base });
  applyOrder();
  renderTableLayerOptions();
  return state.layers[0];
}

function applyOrder() {
  // move bottom-most first, so the first entry in state.layers ends on top
  [...state.layers].reverse().forEach(l => l.mapLayers.forEach(ml => map.moveLayer(ml)));
  ['sketch-fill', 'sketch-line', 'sketch-pts'].forEach(id => map.getLayer(id) && map.moveLayer(id));
  renderLayerList();
}

function setVisible(layer, on) {
  layer.visible = on;
  layer.mapLayers.forEach(ml => map.setLayoutProperty(ml, 'visibility', on ? 'visible' : 'none'));
  if (layer.id === CHANGE_ID) refreshMarkers();
}

function setOpacity(layer, op) {
  layer.opacity = op;
  layer.mapLayers.forEach(ml => {
    const type = map.getLayer(ml).type;
    if (type === 'raster') map.setPaintProperty(ml, 'raster-opacity', op);
    if (type === 'fill') map.setPaintProperty(ml, 'fill-opacity', (layer.base.fill ?? 0.4) * op);
    if (type === 'line') map.setPaintProperty(ml, 'line-opacity', op);
    if (type === 'circle') map.setPaintProperty(ml, 'circle-opacity', op);
  });
}

function zoomTo(layer) {
  if (layer.kind === 'vector' && layer.data.features.length) map.fitBounds(turf.bbox(layer.data), { padding: 60, maxZoom: 15 });
  else map.flyTo(HOME);
}

function removeLayer(layer) {
  layer.mapLayers.forEach(ml => map.removeLayer(ml));
  map.removeSource(layer.id);
  state.layers = state.layers.filter(l => l !== layer);
  renderLayerList();
  renderTableLayerOptions();
}

function moveLayer(layer, delta) {
  const i = state.layers.indexOf(layer), j = i + delta;
  if (j < 0 || j >= state.layers.length) return;
  [state.layers[i], state.layers[j]] = [state.layers[j], state.layers[i]];
  applyOrder();
}

function renderLayerList() {
  const list = $('#layerList');
  list.innerHTML = '';
  state.layers.forEach(layer => {
    const el = document.createElement('div');
    el.className = 'layer';
    el.innerHTML = `
      <div class="layer-row">
        <input type="checkbox" id="chk-${layer.id}" ${layer.visible ? 'checked' : ''}>
        <label for="chk-${layer.id}" title="${esc(layer.name)}">${esc(layer.name)}</label>
        <span class="kind">${layer.kind}</span>
      </div>
      <div class="layer-tools">
        <input type="range" min="0" max="1" step="0.05" value="${layer.opacity}" title="Transparency">
        <button class="icon" data-a="zoom" title="Zoom to layer">🔍</button>
        <button class="icon" data-a="up" title="Move up">▲</button>
        <button class="icon" data-a="down" title="Move down">▼</button>
        ${layer.removable ? '<button class="icon" data-a="remove" title="Remove layer">🗑</button>' : ''}
      </div>`;
    el.querySelector('input[type=checkbox]').onchange = e => setVisible(layer, e.target.checked);
    el.querySelector('input[type=range]').oninput = e => setOpacity(layer, +e.target.value);
    el.querySelectorAll('button[data-a]').forEach(b => b.onclick = () => ({
      zoom: () => zoomTo(layer), up: () => moveLayer(layer, -1), down: () => moveLayer(layer, 1), remove: () => removeLayer(layer),
    })[b.dataset.a]());
    list.appendChild(el);
  });
}

// ---------- 4. Identify / popups ----------
const CHANGE_ID = 'change';
function visibleVectorMapLayers() {
  return state.layers.filter(l => l.kind === 'vector' && l.visible).flatMap(l => l.mapLayers);
}
function layerOfMapLayer(mapLayerId) { return state.layers.find(l => l.mapLayers.includes(mapLayerId)); }

function propsTable(props) {
  return '<table class="popup-table">' + Object.entries(props).filter(([k]) => k !== '__fid')
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</td></tr>`).join('') + '</table>';
}

map.on('click', e => {
  if (state.sketch) return; // sketch tool handles clicks
  const feats = map.queryRenderedFeatures(e.point, { layers: visibleVectorMapLayers() });
  const hit = feats[0];
  // In AI-report mode, clicking a change region selects it (Shift = add to selection)
  if (state.panel === 'report' && hit && layerOfMapLayer(hit.layer.id)?.id === CHANGE_ID) {
    const rid = hit.properties.id;
    if (!e.originalEvent.shiftKey) state.selected.clear();
    state.selected.has(rid) && e.originalEvent.shiftKey ? state.selected.delete(rid) : state.selected.add(rid);
    syncSelection(); generateReport();
    return;
  }
  // Otherwise clicking a change region opens its detail card (explore.js)
  if (hit && layerOfMapLayer(hit.layer.id)?.id === CHANGE_ID) return openRegion(hit.properties.id);
  const html = hit
    ? `<strong>${esc(layerOfMapLayer(hit.layer.id)?.name)}</strong>${propsTable(hit.properties)}`
    : `<strong>Location</strong><br>Lon ${e.lngLat.lng.toFixed(5)}, Lat ${e.lngLat.lat.toFixed(5)}`;
  new maplibregl.Popup({ maxWidth: '320px' }).setLngLat(e.lngLat).setHTML(html).addTo(map);
});
map.on('mousemove', e => {
  $('#statusbar').textContent = `Lon ${e.lngLat.lng.toFixed(5)}  Lat ${e.lngLat.lat.toFixed(5)}  ·  Zoom ${map.getZoom().toFixed(1)}`;
  if (!state.sketch) {
    const over = map.queryRenderedFeatures(e.point, { layers: visibleVectorMapLayers() }).length > 0;
    map.getCanvas().style.cursor = over ? 'pointer' : '';
  }
});

function syncSelection() {
  const layer = state.layers.find(l => l.id === CHANGE_ID);
  if (!layer) return;
  layer.data.features.forEach(f => map.setFeatureState({ source: CHANGE_ID, id: f.properties.__fid }, { selected: state.selected.has(f.properties.id) }));
}

// ---------- 5. Attribute table ----------
function renderTableLayerOptions() {
  const sel = $('#tableLayer');
  const vectors = state.layers.filter(l => l.kind === 'vector');
  sel.innerHTML = vectors.map(l => `<option value="${l.id}">${esc(l.name)}</option>`).join('');
  if (!vectors.some(l => l.id === state.tableLayerId)) state.tableLayerId = vectors[0]?.id ?? null;
  sel.value = state.tableLayerId ?? '';
  if (!$('#tablepane').hidden) renderTable();
}
let hlFeature = null;
function renderTable() {
  const layer = state.layers.find(l => l.id === state.tableLayerId);
  const table = $('#attrTable');
  if (!layer) { table.innerHTML = '<tr><td class="muted">No vector layers</td></tr>'; $('#tableCount').textContent = ''; return; }
  const feats = layer.data.features;
  const cols = [...new Set(feats.flatMap(f => Object.keys(f.properties)))].filter(k => k !== '__fid');
  $('#tableCount').textContent = `${feats.length} features`;
  table.innerHTML = `<thead><tr>${cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>` +
    feats.slice(0, 2000).map((f, i) => `<tr data-i="${i}">${cols.map(c => {
      const v = f.properties[c]; return `<td>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</td>`; }).join('')}</tr>`).join('') + '</tbody>';
  table.querySelectorAll('tbody tr').forEach(tr => tr.onclick = () => {
    table.querySelectorAll('tr.sel').forEach(r => r.classList.remove('sel'));
    tr.classList.add('sel');
    const f = feats[+tr.dataset.i];
    if (hlFeature && map.getSource(hlFeature.source)) map.setFeatureState(hlFeature, { hl: false });
    hlFeature = { source: layer.id, id: f.properties.__fid };
    map.setFeatureState(hlFeature, { hl: true });
    map.fitBounds(turf.bbox(f), { padding: 80, maxZoom: 15 });
  });
}
$('#tableLayer').onchange = e => { state.tableLayerId = e.target.value; renderTable(); };
function toggleTable(force) {
  const pane = $('#tablepane');
  pane.hidden = force === undefined ? !pane.hidden : !force;
  if (!pane.hidden) renderTable();
  document.querySelector('[data-tool=table]').classList.toggle('active', !pane.hidden);
  setTimeout(() => { map.resize(); state.swipe.map?.resize(); }, 0);
}
$('#tableClose').onclick = () => toggleTable(false);

// ---------- 6. Sketch: measure + draw ----------
function ensureSketchLayers() {
  if (map.getSource('sketch')) return;
  map.addSource('sketch', { type: 'geojson', data: turf.featureCollection([]) });
  map.addLayer({ id: 'sketch-fill', type: 'fill', source: 'sketch', filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': '#22d3ee', 'fill-opacity': 0.2 } });
  map.addLayer({ id: 'sketch-line', type: 'line', source: 'sketch', filter: ['!=', ['geometry-type'], 'Point'], paint: { 'line-color': '#0891b2', 'line-width': 2.5, 'line-dasharray': [2, 1] } });
  map.addLayer({ id: 'sketch-pts', type: 'circle', source: 'sketch', filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 4, 'circle-color': '#fff', 'circle-stroke-color': '#0891b2', 'circle-stroke-width': 2 } });
}

function startSketch(mode, purpose) {
  ensureSketchLayers();
  state.sketch = { mode, purpose, coords: [], cursor: null, done: false };
  map.doubleClickZoom.disable();
  map.getCanvas().style.cursor = 'crosshair';
  showHint(mode === 'line' ? 'Click to add points · double-click to finish · Esc to cancel'
                           : 'Click to add corners · double-click to close the area · Esc to cancel');
  updateSketch();
}

function sketchGeometry(includeCursor = true) {
  const s = state.sketch; if (!s) return null;
  const pts = includeCursor && s.cursor && !s.done ? [...s.coords, s.cursor] : [...s.coords];
  if (s.mode === 'line') return pts.length >= 2 ? turf.lineString(pts) : null;
  if (pts.length >= 3) return turf.polygon([[...pts, pts[0]]]);
  return pts.length === 2 ? turf.lineString(pts) : null;
}

function updateSketch() {
  const s = state.sketch;
  const feats = s ? s.coords.map(c => turf.point(c)) : [];
  const g = sketchGeometry();
  if (g) feats.push(g);
  map.getSource('sketch')?.setData(turf.featureCollection(feats));
  if (state.panel === 'measure' || state.panel === 'draw') renderPanel();
}

function stopSketch(clear = true) {
  state.sketch = null;
  map.doubleClickZoom.enable();
  map.getCanvas().style.cursor = '';
  showHint(null);
  if (clear) map.getSource('sketch')?.setData(turf.featureCollection([]));
}

map.on('click', e => {
  const s = state.sketch; if (!s || s.done) return;
  s.coords.push([e.lngLat.lng, e.lngLat.lat]);
  updateSketch();
});
map.on('mousemove', e => { const s = state.sketch; if (s && !s.done) { s.cursor = [e.lngLat.lng, e.lngLat.lat]; updateSketch(); } });
map.on('dblclick', e => {
  const s = state.sketch; if (!s || s.done) return;
  e.preventDefault();
  // a double-click also fired two clicks: drop the duplicate last vertex
  const n = s.coords.length;
  if (n >= 2 && turf.distance(s.coords[n - 1], s.coords[n - 2], { units: 'meters' }) < 1) s.coords.pop();
  const need = s.mode === 'line' ? 2 : 3;
  if (s.coords.length < need) return;
  s.done = true; s.cursor = null;
  map.doubleClickZoom.enable(); map.getCanvas().style.cursor = ''; showHint(null);
  updateSketch();
  if (s.purpose === 'draw') analyseDrawnArea();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape' && state.sketch) { stopSketch(); renderPanel(); } });

function fmtLen(m) { return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m.toFixed(0)} m`; }
function fmtArea(m2) { return m2 >= 1e6 ? `${(m2 / 1e6).toFixed(2)} km² (${(m2 / 1e4).toFixed(0)} ha)` : `${(m2 / 1e4).toFixed(2)} ha (${m2.toFixed(0)} m²)`; }

function measureText() {
  const g = sketchGeometry(); if (!g) return '<span class="muted">Click on the map to start.</span>';
  if (g.geometry.type === 'LineString') return `<b>Length:</b> ${fmtLen(turf.length(g, { units: 'kilometers' }) * 1000)}`;
  return `<b>Area:</b> ${fmtArea(turf.area(g))}<br><b>Perimeter:</b> ${fmtLen(turf.length(turf.polygonToLine(g), { units: 'kilometers' }) * 1000)}`;
}

function analyseDrawnArea() {
  setDrawnArea(sketchGeometry(false));   // explore.js: breakdown of every change inside the area
  state.selected = new Set(explore.drawnIds);
  syncSelection();
  openPanel('changes');
}

function showHint(text) { const h = $('#hint'); h.hidden = !text; h.textContent = text || ''; }

// ---------- 7. Swipe ----------
function swipeOn() {
  const sw = state.swipe; sw.on = true;
  // left image: temporary layer in the main map, just above the basemap
  if (map.getLayer('swipe-left')) map.removeLayer('swipe-left');
  if (map.getSource('swipe-left')) map.removeSource('swipe-left');
  map.addSource('swipe-left', rasterSource(sw.left));
  const firstOp = map.getStyle().layers.find(l => !['bg', 'basemap'].includes(l.id));
  map.addLayer({ id: 'swipe-left', type: 'raster', source: 'swipe-left' }, firstOp?.id);
  // right image: a second map drawn on top and clipped
  const right = { version: 8, sources: { r: rasterSource(sw.right) }, layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#dfe3e8' } }, { id: 'r', type: 'raster', source: 'r' }] };
  const change = state.layers.find(l => l.id === CHANGE_ID);
  if (change) {
    right.sources.c = { type: 'geojson', data: change.data };
    right.layers.push({ id: 'c', type: 'line', source: 'c', paint: { 'line-color': '#f97316', 'line-width': 1.5 } });
  }
  $('#swipeMap').hidden = false; $('#swipeHandle').hidden = false;
  if (!sw.map) {
    sw.map = new maplibregl.Map({ container: 'swipeMap', style: right, interactive: false, attributionControl: false,
                                  center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() });
  } else { sw.map.setStyle(right); sw.map.resize(); }
  syncSwipe();
  if (sw.x === null) sw.x = $('#mapwrap').clientWidth / 2;
  setSwipeX(sw.x);
}
function swipeOff() {
  const sw = state.swipe; sw.on = false;
  $('#swipeMap').hidden = true; $('#swipeHandle').hidden = true;
  if (map.getLayer('swipe-left')) map.removeLayer('swipe-left');
  if (map.getSource('swipe-left')) map.removeSource('swipe-left');
}
function syncSwipe() {
  const m = state.swipe.map; if (!m || !state.swipe.on) return;
  m.jumpTo({ center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() });
}
function setSwipeX(x) {
  const w = $('#mapwrap').clientWidth;
  x = Math.max(0, Math.min(w, x));
  state.swipe.x = x;
  $('#swipeMap').style.clipPath = `inset(0 0 0 ${x}px)`;
  $('#swipeHandle').style.left = `${x}px`;
}
map.on('move', syncSwipe);
(() => {
  const h = $('#swipeHandle');
  h.addEventListener('pointerdown', e => { h.setPointerCapture(e.pointerId); h.dragging = true; });
  h.addEventListener('pointermove', e => { if (h.dragging) setSwipeX(e.clientX - $('#mapwrap').getBoundingClientRect().left); });
  h.addEventListener('pointerup', () => { h.dragging = false; });
})();
window.addEventListener('resize', () => { state.swipe.map?.resize(); if (state.swipe.on) setSwipeX(state.swipe.x); });

// ---------- 8. AI report panel ----------
let reportCache = {};
async function fetchReport(condition) {
  const ids = [...state.selected].sort();
  const key = `${condition}|${ids.join(',')}`;
  if (reportCache[key]) return reportCache[key];
  const res = await fetch('/api/report', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                           body: JSON.stringify({ region_ids: ids, condition }) });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (reportCache[key] = await res.json());
}

async function generateReport() {
  if (state.panel !== 'report') return;
  renderPanel();
  const out = $('#reportOut'); if (!out) return;
  if (!state.selected.size) { out.innerHTML = '<p class="muted">No change regions selected.</p>'; return; }
  out.innerHTML = '<p class="muted">Generating…</p>';
  try {
    if (state.condition === 'compare') {
      const reps = await Promise.all(['template', 'ungated', 'gated'].map(fetchReport));
      out.innerHTML = compareHtml(reps);
    } else {
      out.innerHTML = reportHtml(await fetchReport(state.condition));
    }
  } catch (err) { out.innerHTML = `<p class="chip unsupported">Error: ${esc(err.message)}</p>`; }
}

function gated(c) { return c.stated_conf !== null && c.stated_conf !== undefined && c.stated_conf < state.threshold; }

function reportHtml(r) {
  const shown = r.claims.filter(c => !gated(c));
  const withheld = r.claims.length - shown.length;
  const cnt = v => shown.filter(c => c.verdict === v).length;
  let h = `<div class="section chips">
      <span class="chip supported">${cnt('supported')} supported</span>
      <span class="chip unsupported">${cnt('unsupported')} unsupported</span>
      <span class="chip uncertain">${cnt('uncertain')} uncertain</span>
      ${withheld ? `<span class="chip">${withheld} withheld by threshold</span>` : ''}
    </div>`;
  if (r.condition === 'ungated') h += '<p class="muted">Ungated claims have no confidence, so the threshold cannot filter them.</p>';
  h += '<div class="section"><div class="pane-subtitle">Claims</div>' + r.claims.map(c => `
    <div class="claim ${c.verdict} ${gated(c) ? 'hidden-by-gate' : ''}">
      <div>${esc(c.text)}</div>
      <div class="meta"><span class="chip">${esc(c.level)}</span> <span class="chip ${c.verdict}">${c.verdict}</span>
        ${c.evidence_ref?.length ? ` · evidence: ${c.evidence_ref.map(esc).join(', ')}` : ' · no evidence cited'}
        ${c.stated_conf != null ? ` · conf ${(+c.stated_conf).toFixed(2)}` : ''}
        ${gated(c) ? ' · <b>withheld (below threshold)</b>' : ''}</div>
      ${c.verdict_note ? `<div class="meta muted">${esc(c.verdict_note)}</div>` : ''}
    </div>`).join('') + '</div>';
  if (r.abstain.length) h += '<div class="section"><div class="pane-subtitle">Abstained (model declined to claim)</div>' +
    r.abstain.map(a => `<div class="abstain"><b>${esc(a.topic)}</b><br><span class="muted">${esc(a.reason)}</span></div>`).join('') + '</div>';
  if (r.raw_output) h += `<details><summary>Raw model text</summary><p>${esc(r.raw_output)}</p></details>`;
  h += `<details><summary>Evidence sent to the model</summary><pre>${esc(JSON.stringify(r.evidence, null, 2))}</pre></details>`;
  h += `<p class="muted">Model: ${esc(r.model)}</p>`;
  return h;
}

function compareHtml(reps) {
  const row = r => {
    const shown = r.claims.filter(c => !gated(c));
    const n = v => shown.filter(c => c.verdict === v).length;
    return `<tr><td>${r.condition}</td><td>${shown.length}</td><td>${n('supported')}</td><td>${n('unsupported')}</td><td>${n('uncertain')}</td><td>${r.abstain.length}</td></tr>`;
  };
  return `<table class="cmp"><thead><tr><th>Condition</th><th>Claims</th><th>✔</th><th>✘</th><th>?</th><th>Abstain</th></tr></thead>
    <tbody>${reps.map(row).join('')}</tbody></table>
    <p class="muted">✔ supported · ✘ unsupported (hallucination) · ? uncertain. Counts use the current threshold.
    The research question: does <b>gated</b> keep ✘ near zero while still making useful claims?</p>`;
}

// ---------- 9. Add data ----------
$('#fileInput').onchange = async e => {
  const file = e.target.files[0]; e.target.value = '';
  if (!file) return;
  try {
    let fc;
    if (file.name.toLowerCase().endsWith('.zip')) {
      const out = await shp(await file.arrayBuffer());
      fc = turf.featureCollection((Array.isArray(out) ? out : [out]).flatMap(o => o.features));
    } else {
      const j = JSON.parse(await file.text());
      fc = j.type === 'FeatureCollection' ? j : j.type === 'Feature' ? turf.featureCollection([j]) : turf.featureCollection([turf.feature(j)]);
    }
    fc.features = fc.features.filter(f => f && f.geometry);
    if (!fc.features.length) throw new Error('No features with geometry found.');
    const layer = addVectorLayer({ id: `user-${Date.now()}`, name: file.name, data: fc, removable: true });
    zoomTo(layer);
  } catch (err) {
    alertBox(`Could not load "${file.name}": ${err.message}. Supported: GeoJSON (.geojson/.json) or a zipped shapefile (.zip, WGS84 or with a .prj).`);
  }
};
function alertBox(msg) { showHint(msg); setTimeout(() => showHint(null), 6000); }

// ---------- 10. Panels + toolbar ----------
const PANEL_TITLES = { basemap: 'Basemap gallery', measure: 'Measure', draw: 'Draw area to analyse', swipe: 'Swipe compare',
                       changes: 'Find changes', report: 'AI change report' };

function openPanel(name) {
  if (state.panel === name) return renderPanel();
  closePanel(false);
  state.panel = name;
  $('#panel').hidden = false;
  if (name === 'measure') startSketch('line', 'measure');
  if (name === 'draw') startSketch('polygon', 'draw');
  if (name === 'swipe') swipeOn();
  syncToolbar();
  setTimeout(() => { map.resize(); state.swipe.map?.resize(); if (state.swipe.on) setSwipeX(state.swipe.x); }, 0);
  if (name === 'report') generateReport(); else renderPanel();
}
function closePanel(resize = true) {
  // keep a finished drawn area visible when moving on to the change panel or report; clear everything else
  if (state.sketch) stopSketch(!(state.panel === 'draw' && state.sketch.done));
  else if (state.panel === 'measure' || (resize && ['report', 'changes'].includes(state.panel))) map.getSource('sketch')?.setData(turf.featureCollection([]));
  if (state.panel === 'changes') { destroyCardMaps(); highlightRegion(null); }
  if (state.swipe.on) swipeOff();
  state.panel = null;
  $('#panel').hidden = true;
  syncToolbar();
  if (resize) setTimeout(() => { map.resize(); state.swipe.map?.resize(); }, 0);
}
$('#panelClose').onclick = () => closePanel();

function syncToolbar() {
  document.querySelectorAll('#toolbar button').forEach(b => {
    const t = b.dataset.tool;
    b.classList.toggle('active', t === state.panel || (t === 'table' && !$('#tablepane').hidden));
  });
}

function renderPanel() {
  const name = state.panel; if (!name) return;
  $('#panelTitle').textContent = PANEL_TITLES[name];
  const body = $('#panelBody');
  if (name === 'basemap') {
    body.innerHTML = `<div class="basemaps">${BASEMAPS.map(k =>
      `<button data-k="${k}" class="${state.basemap === k ? 'on' : ''}">${k === 'none' ? 'No basemap' : esc(TILES[k].name)}</button>`).join('')}</div>
      <p class="muted">Sentinel-2 cloudless mosaics by EOX (non-commercial licence for 2018+ — fine for research, keep the attribution).</p>`;
    body.querySelectorAll('button').forEach(b => b.onclick = () => setBasemap(b.dataset.k));
  }
  if (name === 'measure') {
    const mode = state.sketch?.mode ?? 'line';
    body.innerHTML = `<div class="section seg"><button data-m="line" class="${mode === 'line' ? 'on' : ''}">Distance</button>
      <button data-m="polygon" class="${mode === 'polygon' ? 'on' : ''}">Area</button></div>
      <div class="section">${state.sketch ? measureText() : '<span class="muted">Finished.</span>'}</div>
      <button class="btn" id="mNew">New measurement</button>`;
    body.querySelectorAll('[data-m]').forEach(b => b.onclick = () => startSketch(b.dataset.m, 'measure'));
    $('#mNew').onclick = () => startSketch(mode, 'measure');
  }
  if (name === 'draw') {
    body.innerHTML = `<p>Draw a polygon on the map. When you double-click to close it, you get a breakdown of every change inside it, by type, with the AI report one click away.</p>
      <div class="section">${state.sketch ? measureText() : ''}</div>
      <button class="btn" id="dNew">Start again</button>`;
    $('#dNew').onclick = () => startSketch('polygon', 'draw');
  }
  if (name === 'swipe') {
    const opts = sel => ['s2_2018', 's2_2022', 'osm', 'topo'].map(k => `<option value="${k}" ${sel === k ? 'selected' : ''}>${esc(TILES[k].name)}</option>`).join('');
    body.innerHTML = `<div class="section"><label>Left side<br><select id="swL">${opts(state.swipe.left)}</select></label></div>
      <div class="section"><label>Right side<br><select id="swR">${opts(state.swipe.right)}</select></label></div>
      <p class="muted">Drag the white bar on the map. Orange outlines = change regions.</p>`;
    $('#swL').onchange = e => { state.swipe.left = e.target.value; swipeOn(); };
    $('#swR').onchange = e => { state.swipe.right = e.target.value; swipeOn(); };
  }
  if (name === 'changes') renderChangesPanel(body);
  if (name === 'report') {
    const ids = [...state.selected].sort();
    body.innerHTML = `
      ${state.liveData
        ? '<div class="demo-banner" style="background:var(--ok-bg);color:var(--ok);border-color:#bbe5c7;">Live data — from the multi-agent pipeline or Person 1\'s real export.</div>'
        : '<div class="demo-banner">DEMO data — run <code>agents/run_demo.py</code> or import Person 1\'s export to see real data here. Claims come from <code>backend/report.py</code>; Person 2 plugs the Qwen notebook code in there.</div>'}
      <div class="section"><div class="pane-subtitle">Selected change regions</div>
        <div class="chips">${ids.length ? ids.map(i => `<span class="chip">${esc(i)}</span>`).join('') : '<span class="muted">none</span>'}</div>
        <p class="muted">Click a coloured region on the map (Shift+click to add more) or use ✎ Draw area.</p>
        <button class="btn" id="rAll">Select all</button> <button class="btn" id="rClear">Clear</button></div>
      <div class="section seg" id="rCond">${['template', 'ungated', 'gated', 'compare'].map(c =>
        `<button data-c="${c}" class="${state.condition === c ? 'on' : ''}">${c[0].toUpperCase() + c.slice(1)}</button>`).join('')}</div>
      <div class="section"><label>Confidence threshold: <b id="thrVal">${state.threshold.toFixed(2)}</b>
        <input type="range" id="thr" min="0" max="1" step="0.05" value="${state.threshold}" style="width:100%"></label>
        <span class="muted">Claims below this confidence are withheld (abstain).</span></div>
      <div id="reportOut"></div>`;
    $('#rAll').onclick = () => { state.selected = new Set(state.layers.find(l => l.id === CHANGE_ID)?.data.features.map(f => f.properties.id) ?? []); syncSelection(); generateReport(); };
    $('#rClear').onclick = () => { state.selected.clear(); syncSelection(); generateReport(); };
    body.querySelectorAll('[data-c]').forEach(b => b.onclick = () => { state.condition = b.dataset.c; generateReport(); });
    $('#thr').oninput = e => { state.threshold = +e.target.value; $('#thrVal').textContent = state.threshold.toFixed(2); rerenderReportOnly(); };
  }
}
let thrTimer = null;
function rerenderReportOnly() { clearTimeout(thrTimer); thrTimer = setTimeout(async () => {
  const out = $('#reportOut'); if (!out || !state.selected.size) return;
  if (state.condition === 'compare') out.innerHTML = compareHtml(await Promise.all(['template', 'ungated', 'gated'].map(fetchReport)));
  else out.innerHTML = reportHtml(await fetchReport(state.condition));
}, 60); }

document.querySelectorAll('#toolbar button').forEach(b => b.onclick = () => {
  const t = b.dataset.tool;
  if (t === 'add') return $('#fileInput').click();
  if (t === 'table') return toggleTable();
  if (state.panel === t) return closePanel();
  openPanel(t);
});

// ---------- 11. Start-up ----------
map.on('load', async () => {
  setBasemap(state.basemap);
  addRasterLayer({ id: 'img-2018', name: 'Sentinel-2 2018 (before)', tileKey: 's2_2018', visible: false });
  addRasterLayer({ id: 'img-2022', name: 'Sentinel-2 2022 (after)', tileKey: 's2_2022', visible: false });
  try {
    const health = await (await fetch('/api/health')).json();
    state.liveData = !!health.live_data;
  } catch (err) { state.liveData = false; }
  try {
    await loadChangeTypes();
    const defs = await (await fetch('/api/layers')).json();
    for (const d of defs) {
      const data = await (await fetch(d.url)).json();
      if (d.id === CHANGE_ID) annotateRegions(data);   // colour + icon by change type instead of confidence
      addVectorLayer({ id: d.id, name: d.name, data, style: d.id === CHANGE_ID ? 'change_type' : d.style });
    }
    initExplorer();
  } catch (err) { alertBox(`Could not load layers from the backend: ${err.message}`); }
  window.eviReady = true;
});
