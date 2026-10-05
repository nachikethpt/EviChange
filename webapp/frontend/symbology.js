/* EviChange GIS — symbology (style a vector layer by an attribute) + per-layer legends.
 * Loaded BEFORE app.js, like explore.js: this file only defines functions; app.js calls
 * them, after which map/state/$/esc/... from app.js are in scope.
 * Methods follow ArcGIS Pro: single symbol, unique values, graduated colours
 * (natural breaks / equal interval / quantile).
 */
'use strict';

const RAMPS = {
  'Yellow – red': ['#fef3c7', '#fdba74', '#ea580c', '#7f1d1d'],
  'Blues':        ['#eff6ff', '#93c5fd', '#2563eb', '#1e3a8a'],
  'Greens':       ['#f0fdf4', '#86efac', '#16a34a', '#14532d'],
  'Viridis':      ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
  'Red – blue (diverging)': ['#b91c1c', '#fca5a5', '#f8fafc', '#93c5fd', '#1d4ed8'],
};
const CATEGORICAL = ['#2563eb', '#ea580c', '#16a34a', '#dc2626', '#9333ea', '#0891b2',
                     '#ca8a04', '#db2777', '#65a30d', '#475569', '#7c3aed', '#0d9488'];
const MAX_CATEGORIES = CATEGORICAL.length, NO_DATA = '#d1d5db', SYM_FILL_OPACITY = 0.6;
const CLASS_METHODS = { jenks: 'Natural breaks (Jenks)', equal: 'Equal interval', quantile: 'Quantile' };
const SYM_METHODS = { default: 'Default', single: 'Single', unique: 'Unique', graduated: 'Graduated' };

// ---------- colours + numbers ----------
function hexToRgb(h) { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function rgbToHex(c) { return '#' + c.map(v => Math.round(v).toString(16).padStart(2, '0')).join(''); }

/** k colours evenly spaced along a ramp. */
function rampColors(name, k) {
  const stops = RAMPS[name].map(hexToRgb);
  return Array.from({ length: k }, (_, i) => {
    const t = k === 1 ? stops.length - 1 : i / (k - 1) * (stops.length - 1);
    const j = Math.min(Math.floor(t), stops.length - 2), f = t - j;
    return rgbToHex(stops[j].map((v, c) => v + (stops[j + 1][c] - v) * f));
  });
}
function fmtNum(n) { return Math.abs(n) >= 100 ? Math.round(n).toLocaleString() : String(+n.toPrecision(3)); }

// ---------- fields + classification ----------
/** Map of field name -> 'number' | 'string' (mixed types count as string; arrays/objects skipped). */
function layerFields(layer) {
  const fields = new Map();
  layer.data.features.forEach(f => Object.entries(f.properties).forEach(([k, v]) => {
    if (k.startsWith('__') || v == null || typeof v === 'object') return;
    const t = typeof v === 'number' ? 'number' : 'string';
    fields.set(k, fields.has(k) && fields.get(k) !== t ? 'string' : t);
  }));
  return fields;
}

/** Upper bound of each class, ascending (the last one is the maximum). */
function classBreaks(values, k, method) {
  const v = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return [];
  const min = v[0], max = v[v.length - 1];
  if (min === max) return [max];
  let b;
  if (method === 'equal') b = Array.from({ length: k }, (_, i) => min + (max - min) * (i + 1) / k);
  else if (method === 'quantile') b = Array.from({ length: k }, (_, i) => v[Math.min(v.length - 1, Math.ceil(v.length * (i + 1) / k) - 1)]);
  else b = jenks(v, k);
  b[b.length - 1] = max;
  return [...new Set(b)];
}

/** Jenks natural breaks on sorted values. O(k·n²), so large layers are sampled to 1000 values. */
function jenks(v, k) {
  if (v.length > 1000) v = Array.from({ length: 1000 }, (_, i) => v[Math.floor(i * v.length / 1000)]);
  const n = v.length; k = Math.min(k, n);
  const lower = Array.from({ length: n + 1 }, () => new Array(k + 1).fill(0));
  const vari = Array.from({ length: n + 1 }, () => new Array(k + 1).fill(Infinity));
  for (let j = 1; j <= k; j++) { lower[1][j] = 1; vari[1][j] = 0; }
  for (let l = 2; l <= n; l++) {
    let s1 = 0, s2 = 0, w = 0, va = 0;
    for (let m = 1; m <= l; m++) {
      const i3 = l - m + 1, val = v[i3 - 1];
      s1 += val; s2 += val * val; w++;
      va = s2 - s1 * s1 / w;
      const i4 = i3 - 1;
      if (i4 !== 0) for (let j = 2; j <= k; j++) {
        if (vari[l][j] >= va + vari[i4][j - 1]) { lower[l][j] = i3; vari[l][j] = va + vari[i4][j - 1]; }
      }
    }
    lower[l][1] = 1; vari[l][1] = va;
  }
  const breaks = new Array(k); breaks[k - 1] = v[n - 1];
  for (let j = k, kk = n; j >= 2; j--) { breaks[j - 2] = v[lower[kk][j] - 2]; kk = lower[kk][j] - 1; }
  return breaks;
}

// ---------- symbology -> MapLibre colour expression + legend ----------
function defaultSym(layer) {
  return { method: 'default', field: null, classes: 5, classMethod: 'jenks', ramp: 'Yellow – red', color: layer.color || '#2563eb' };
}
function symActive(layer) { return !!layer?.sym && layer.sym.method !== 'default'; }

/** { color: expression, legend: [{color, label, count}] } for the layer's style, or null for the default style. */
function symbologyFor(layer) {
  const s = layer.sym; if (!symActive(layer)) return null;
  const feats = layer.data.features, get = f => f.properties[s.field];
  if (s.method === 'single') return { color: s.color, legend: [{ color: s.color, label: 'All features', count: feats.length }] };

  if (s.method === 'unique') {
    const counts = new Map();
    feats.forEach(f => { const v = get(f); if (v == null || typeof v === 'object') return; counts.set(String(v), (counts.get(String(v)) || 0) + 1); });
    const vals = [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const top = vals.slice(0, MAX_CATEGORIES);
    const rest = vals.slice(MAX_CATEGORIES).reduce((n, [, c]) => n + c, 0);
    const missing = feats.length - vals.reduce((n, [, c]) => n + c, 0);
    const legend = top.map(([v, c], i) => ({ color: CATEGORICAL[i], label: v, count: c }));
    if (rest) legend.push({ color: NO_DATA, label: `Other (${vals.length - MAX_CATEGORIES} values)`, count: rest });
    if (missing) legend.push({ color: NO_DATA, label: 'No value', count: missing });
    const color = top.length ? ['match', ['to-string', ['get', s.field]], ...top.flatMap(([v], i) => [v, CATEGORICAL[i]]), NO_DATA] : NO_DATA;
    return { color, legend };
  }

  // graduated colours: classes are upper-bound inclusive, as in ArcGIS Pro
  const nums = feats.map(get).filter(v => typeof v === 'number' && Number.isFinite(v));
  const ub = classBreaks(nums, s.classes, s.classMethod);
  if (!ub.length) return { color: NO_DATA, legend: [{ color: NO_DATA, label: 'No numeric values', count: feats.length }] };
  const colors = rampColors(s.ramp, ub.length);
  const th = ub.slice(0, -1).map(b => b + Math.abs(b) * 1e-9 + 1e-12);   // step() switches at >=, so nudge past each upper bound
  const step = th.length ? ['step', ['get', s.field], colors[0], ...th.flatMap((t, i) => [t, colors[i + 1]])] : colors[0];
  const color = ['case', ['==', ['typeof', ['get', s.field]], 'number'], step, NO_DATA];
  const counts = new Array(ub.length).fill(0);
  nums.forEach(x => counts[th.filter(t => x >= t).length]++);
  const lo = nums.reduce((m, x) => Math.min(m, x), Infinity);
  const legend = ub.map((b, i) => ({ color: colors[i], label: `${fmtNum(i ? ub[i - 1] : lo)} – ${fmtNum(b)}`, count: counts[i] }));
  if (nums.length < feats.length) legend.push({ color: NO_DATA, label: 'No value', count: feats.length - nums.length });
  return { color, legend };
}

/** Repaint the layer's map layers from layer.sym (the default style restores the original paint). */
function applySymbology(layer) {
  const sym = symbologyFor(layer);
  const hl = ['any', ['boolean', ['feature-state', 'selected'], false], ['boolean', ['feature-state', 'hl'], false]];
  layer.mapLayers.forEach(ml => {
    const type = map.getLayer(ml).type;
    if (!sym) return Object.entries(layer.origPaint[ml]).forEach(([p, v]) => map.setPaintProperty(ml, p, v));
    if (type === 'fill') map.setPaintProperty(ml, 'fill-color', sym.color);
    if (type === 'line') map.setPaintProperty(ml, 'line-color', ['case', hl, '#22d3ee', sym.color]);
    if (type === 'circle') map.setPaintProperty(ml, 'circle-color', sym.color);
  });
  layer.base.fill = sym ? SYM_FILL_OPACITY : layer.origBaseFill;
  setOpacity(layer, layer.opacity);
  if (layer.id === CHANGE_ID) { refreshMarkers(); renderLegend(); }   // type icons + type legend only match the default style
  renderLayerList();
}

// ---------- legends ----------
function legendRows(rows) {
  return rows.map(r => `<div class="sym-row"><span class="sym-swatch" style="background:${r.color}"></span>
    <span class="sym-label" title="${esc(r.label)}">${esc(r.label)}</span>${r.count != null ? `<span class="muted">${r.count}</span>` : ''}</div>`).join('');
}

/** Small legend shown under each vector layer in Contents. */
function layerLegendHtml(layer) {
  if (layer.kind === 'raster') return rasterLegendHtml(layer.legend);
  const sym = symbologyFor(layer);
  if (sym) return `<div class="muted small">${esc(layer.sym.method === 'single' ? 'Single symbol' : layer.sym.field)}</div>` + legendRows(sym.legend);
  if (layer.style === 'change_type') return '<div class="muted small">Coloured by change type (legend below)</div>';
  if (layer.style === 'confidence') return '<div class="muted small">mean_conf</div><div class="sym-ramp" style="background:linear-gradient(90deg,#fde68a,#f97316,#b91c1c)"></div><div class="sym-ramp-labels muted small"><span>0.3</span><span>0.9</span></div>';
  if (layer.style === 'outline') return '<div class="sym-row"><span class="sym-swatch outline"></span><span class="sym-label">Outline</span></div>';
  return legendRows([{ color: layer.color, label: 'All features', count: layer.data.features.length }]);
}

/** Colour ramp + range for a raster layer (index layers from gistools.js). */
function rasterLegendHtml(lg) {
  return `<div class="muted small">${esc(lg.label)}</div>
    <div class="sym-ramp" style="background:linear-gradient(90deg,${lg.palette.join(',')})"></div>
    <div class="sym-ramp-labels muted small"><span>≤ ${lg.min}</span><span>≥ ${lg.max}</span></div>
    ${lg.note ? `<div class="muted small">${esc(lg.note)}</div>` : ''}`;
}

// ---------- Symbology panel ----------
function openSymbology(layer) { state.symLayerId = layer.id; openPanel('symbology'); }

function pickField(fields, type, preferred) {
  const names = [...fields].filter(([, t]) => !type || t === type).map(([k]) => k);
  return preferred.find(p => names.includes(p)) ?? names[0] ?? null;
}

function renderSymbologyPanel(body) {
  const vectors = state.layers.filter(l => l.kind === 'vector');
  if (!vectors.length) { body.innerHTML = '<p class="muted">No vector layers to style. Add data first.</p>'; return; }
  const layer = vectors.find(l => l.id === state.symLayerId) || vectors[0];
  state.symLayerId = layer.id;
  const s = layer.sym || (layer.sym = defaultSym(layer));
  const fields = layerFields(layer);
  const numeric = [...fields].filter(([, t]) => t === 'number').map(([k]) => k);
  const opt = (v, label, sel) => `<option value="${esc(v)}" ${sel ? 'selected' : ''}>${esc(label)}</option>`;
  const fieldSelect = names => `<label>Field<br><select id="symField">${names.map(f => opt(f, f, f === s.field)).join('')}</select></label>`;

  let controls = '';
  if (s.method === 'default') controls = `<p class="muted">The layer's original style${layer.style === 'change_type' ? ' (colour + icon by change type)' : ''}.</p>`;
  if (s.method === 'single') controls = `<label>Colour <input type="color" id="symColor" value="${s.color}"></label>`;
  if (s.method === 'unique') controls = fieldSelect([...fields.keys()]) +
    `<p class="muted">Up to ${MAX_CATEGORIES} most common values get their own colour; the rest are grey.</p>`;
  if (s.method === 'graduated') controls = fieldSelect(numeric) + `
    <div class="sym-grid">
      <label>Method<br><select id="symClassMethod">${Object.entries(CLASS_METHODS).map(([k, v]) => opt(k, v, k === s.classMethod)).join('')}</select></label>
      <label>Classes<br><select id="symClasses">${[2, 3, 4, 5, 6, 7, 8, 9].map(n => opt(n, n, n === s.classes)).join('')}</select></label>
    </div>
    <label>Colour ramp<br><select id="symRamp">${Object.keys(RAMPS).map(r => opt(r, r, r === s.ramp)).join('')}</select></label>
    <div class="sym-ramp" style="background:linear-gradient(90deg,${RAMPS[s.ramp].join(',')})"></div>`;

  const sym = symbologyFor(layer);
  body.innerHTML = `
    <div class="section"><label>Layer<br><select id="symLayer">${vectors.map(l => opt(l.id, l.name, l === layer)).join('')}</select></label></div>
    <div class="section seg">${Object.entries(SYM_METHODS).map(([k, v]) =>
      `<button data-sm="${k}" class="${s.method === k ? 'on' : ''}" ${k === 'graduated' && !numeric.length || k === 'unique' && !fields.size ? 'disabled' : ''}>${v}</button>`).join('')}</div>
    <div class="section sym-controls">${controls}</div>
    ${sym ? `<div class="section"><div class="pane-subtitle">Legend</div>${legendRows(sym.legend)}</div>` : ''}
    <p class="muted small">Styling only changes how the layer is drawn. The data, the AI report and the change search are unchanged.</p>`;

  const update = patch => { Object.assign(s, patch); applySymbology(layer); renderPanel(); };
  $('#symLayer').onchange = e => { state.symLayerId = e.target.value; renderPanel(); };
  body.querySelectorAll('[data-sm]').forEach(b => b.onclick = () => {
    const m = b.dataset.sm, patch = { method: m };
    if (m === 'unique' && !fields.has(s.field)) patch.field = pickField(fields, 'string', ['primary_type', 'location', 'name']) ?? pickField(fields, null, []);
    if (m === 'graduated' && fields.get(s.field) !== 'number') patch.field = pickField(fields, 'number', ['area_ha', 'mean_conf']);
    update(patch);
  });
  const on = (sel, ev, fn) => { const el = $(sel); if (el) el[ev] = fn; };
  on('#symField', 'onchange', e => update({ field: e.target.value }));
  on('#symColor', 'onchange', e => update({ color: e.target.value }));   // not oninput: re-rendering would close the picker
  on('#symClassMethod', 'onchange', e => update({ classMethod: e.target.value }));
  on('#symClasses', 'onchange', e => update({ classes: +e.target.value }));
  on('#symRamp', 'onchange', e => update({ ramp: e.target.value }));
}
