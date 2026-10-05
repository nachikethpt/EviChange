/* EviChange GIS — ArcGIS Pro-style tools (Phase 7b, decisions.md D8).
 * Index rasters from Earth Engine (b), selection by attributes / location and
 * geoprocessing: buffer, clip, intersect, dissolve (c).
 * Loaded BEFORE app.js, like explore.js: this file only defines functions; app.js calls
 * them, after which map/state/$/esc/... from app.js are in scope.
 * Geoprocessing outputs are new layers: a run's change regions are never modified.
 * The geometry work runs in a Web Worker (geomworker.js + geomops.js); the map stays usable meanwhile.
 */
'use strict';

// ---------- (b) Index rasters ----------
const INDEX_INFO = {
  NDVI:  { short: 'Vegetation (NDVI)', plain: 'Green vegetation is high; bare ground, buildings and water are low.' },
  NDBI:  { short: 'Bare / built-up (NDBI)', plain: 'Bare soil, rock and built surfaces are high; vegetation and water are low.' },
  MNDWI: { short: 'Water (MNDWI)', plain: 'Open water is high; land is low.' },
};
const INDEX_KIND_LABELS = { before: 'Before', after: 'After', change: 'Change (after − before)' };
const gis = { index: 'NDVI', indexKind: 'change', indexBusy: false, indexMsg: '', tool: 'select_attr',
              form: {}, toolMsg: '', toolBusy: false };

function windowLabel(w) { return w.map(d => d.slice(0, 7)).join(' → '); }

async function addIndexLayer(index, kind) {
  const id = `idx-${index}-${kind}`;
  const existing = state.layers.find(l => l.id === id);
  if (existing) { setVisible(existing, true); renderLayerList(); gis.indexMsg = 'That layer is already in Contents; it is switched on.'; return renderPanel(); }
  gis.indexBusy = true; gis.indexMsg = 'Asking Earth Engine for the composites (5–30 s)…'; renderPanel();
  try {
    const res = await fetch(`/api/index_layer?index=${index}&kind=${kind}`);
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || res.statusText);
    const when = kind === 'before' ? windowLabel(body.before_window) : kind === 'after' ? windowLabel(body.after_window)
      : `${windowLabel(body.before_window)} vs ${windowLabel(body.after_window)}`;
    addRasterLayer({
      id, name: `${index} ${kind} (${when})`, visible: true, removable: true,
      source: { type: 'raster', tiles: body.tiles, tileSize: 256,
                attribution: 'Index layers: contains modified Copernicus Sentinel-2 data, processed in Google Earth Engine' },
      legend: { min: body.min, max: body.max, palette: body.palette,
                label: kind === 'change' ? `${index} change` : index,
                note: kind === 'change' ? `The detector flags |change| > ${explore.tIdx}` : null },
    });
    gis.indexMsg = 'Added. It sits below the vector layers; use ▲▼ in Contents to reorder.';
  } catch (err) {
    gis.indexMsg = `Could not add the layer: ${err.message}`;
  }
  gis.indexBusy = false; renderPanel();
}

function renderIndicesPanel(body) {
  const seg = (attr, opts, cur) => `<div class="section seg">${Object.entries(opts).map(([k, v]) =>
    `<button data-${attr}="${k}" class="${cur === k ? 'on' : ''}">${esc(v)}</button>`).join('')}</div>`;
  body.innerHTML = `
    <p>Show the spectral indices the change detector uses, computed in Earth Engine from the same cloud-masked Sentinel-2 composites.</p>
    <div class="pane-subtitle">Index</div>
    ${seg('ix', Object.fromEntries(Object.keys(INDEX_INFO).map(k => [k, k])), gis.index)}
    <p class="muted">${esc(INDEX_INFO[gis.index].short)}: ${esc(INDEX_INFO[gis.index].plain)}</p>
    <div class="pane-subtitle">Show</div>
    ${seg('ik', { before: 'Before', after: 'After', change: 'Change' }, gis.indexKind)}
    <button class="btn primary" id="ixAdd" ${gis.indexBusy ? 'disabled' : ''}>${gis.indexBusy ? 'Working…' : '＋ Add layer'}</button>
    ${gis.indexMsg ? `<p class="muted">${esc(gis.indexMsg)}</p>` : ''}
    <p class="muted small">Needs live data (an Earth Engine analysis) and this computer's Earth Engine login. Demo data has no index layers.</p>`;
  body.querySelectorAll('[data-ix]').forEach(b => b.onclick = () => { gis.index = b.dataset.ix; renderPanel(); });
  body.querySelectorAll('[data-ik]').forEach(b => b.onclick = () => { gis.indexKind = b.dataset.ik; renderPanel(); });
  $('#ixAdd').onclick = () => addIndexLayer(gis.index, gis.indexKind);
}

// ---------- selection (shared by the tools, the attribute table and the AI report) ----------
function vectorLayers() { return state.layers.filter(l => l.kind === 'vector'); }
function layerById(id) { return state.layers.find(l => l.id === id); }

/** Selected feature ids (__fid). The change layer's selection is state.selected (region ids), which the AI report uses. */
function selectedFids(layer) {
  if (layer.id === CHANGE_ID) return new Set(layer.data.features.filter(f => state.selected.has(f.properties.id)).map(f => f.properties.__fid));
  return layer.selection || new Set();
}

function setSelection(layer, fids) {
  if (layer.id === CHANGE_ID) {
    state.selected = new Set(layer.data.features.filter(f => fids.has(f.properties.__fid)).map(f => f.properties.id));
    syncSelection();
  } else {
    (layer.selection || new Set()).forEach(fid => map.setFeatureState({ source: layer.id, id: fid }, { selected: false }));
    fids.forEach(fid => map.setFeatureState({ source: layer.id, id: fid }, { selected: true }));
    layer.selection = fids;
  }
  if (!$('#tablepane').hidden && state.tableLayerId === layer.id) renderTable();
  if (state.panel === 'report') generateReport();
  if (state.panel === 'charts') renderPanel();
}

function combineSelection(layer, fids, mode) {
  const cur = selectedFids(layer);
  if (mode === 'add') return new Set([...cur, ...fids]);
  if (mode === 'remove') return new Set([...cur].filter(f => !fids.has(f)));
  if (mode === 'subset') return new Set([...cur].filter(f => fids.has(f)));
  return fids;
}

/** Features a tool works on: the selected ones when "selected only" is ticked and there is a selection. */
function toolInput(layer, selectedOnly) {
  const sel = selectedFids(layer);
  return selectedOnly && sel.size ? layer.data.features.filter(f => sel.has(f.properties.__fid)) : layer.data.features;
}

// ---------- background geometry (geomworker.js runs geomops.js) ----------
let geoWorker = null, geoSeq = 0;
const geoJobs = new Map();

/** Runs a geomops.js op in the worker; resolves with its result, reports progress in [0, 1]. */
function geo(op, args, onProgress) {
  if (!geoWorker) {
    geoWorker = new Worker('/static/geomworker.js');
    geoWorker.onmessage = ({ data }) => {
      const job = geoJobs.get(data.id); if (!job) return;
      if (data.progress != null) return job.onProgress?.(data.progress);
      geoJobs.delete(data.id);
      data.error ? job.reject(new Error(data.error)) : job.resolve(data.result);
    };
    geoWorker.onerror = e => {            // the worker died: fail every pending job and start a fresh one next time
      geoJobs.forEach(j => j.reject(new Error(e.message || 'background worker failed')));
      geoJobs.clear(); geoWorker.terminate(); geoWorker = null;
    };
  }
  return new Promise((resolve, reject) => {
    const id = ++geoSeq;
    geoJobs.set(id, { resolve, reject, onProgress });
    geoWorker.postMessage({ id, op, args });
  });
}

// ---------- (c) the tools ----------
const TOOLS = {
  select_attr: { name: 'Select by attributes', group: 'Select' },
  select_loc:  { name: 'Select by location', group: 'Select' },
  buffer:      { name: 'Buffer', group: 'Analyse' },
  clip:        { name: 'Clip', group: 'Analyse' },
  intersect:   { name: 'Intersect', group: 'Analyse' },
  dissolve:    { name: 'Dissolve', group: 'Analyse' },
};
const OPS = { '=': '=', '!=': '≠', '>': '>', '>=': '≥', '<': '<', '<=': '≤', contains: 'contains', empty: 'is empty' };
const RELATIONS = { intersect: 'intersect', within: 'are completely within', within_distance: 'are within a distance of' };
const SEL_MODES = { new: 'New selection', add: 'Add to selection', remove: 'Remove from selection', subset: 'Select from current selection' };

function sqlValue(v, numeric) { return numeric ? String(v) : `'${String(v).replace(/'/g, "''")}'`; }

/** The WHERE clause shown to the user, like ArcGIS Pro shows the SQL it runs. */
function attrExpression(f) {
  if (f.op === 'empty') return `${f.field} IS NULL`;
  if (f.op === 'contains') return `${f.field} LIKE '%${String(f.value).replace(/'/g, "''")}%'`;
  return `${f.field} ${f.op === '!=' ? '<>' : f.op} ${sqlValue(f.value, f.numeric)}`;
}

function attrTest(f) {
  const want = f.numeric ? parseFloat(f.value) : String(f.value);
  return p => {
    const v = p[f.field];
    if (f.op === 'empty') return v == null || v === '';
    if (v == null || typeof v === 'object') return false;
    if (f.op === 'contains') return String(v).toLowerCase().includes(String(f.value).toLowerCase());
    const x = f.numeric ? +v : String(v);
    return { '=': x === want, '!=': x !== want, '>': x > want, '>=': x >= want, '<': x < want, '<=': x <= want }[f.op];
  };
}

function runSelectByAttributes(fm) {
  const layer = layerById(fm.layer);
  const fields = layerFields(layer);
  const spec = { ...fm, numeric: fields.get(fm.field) === 'number' };
  if (spec.op !== 'empty' && (fm.value === '' || (spec.numeric && !Number.isFinite(parseFloat(fm.value)))))
    throw new Error(spec.numeric ? `${fm.field} is numeric: enter a number.` : 'Enter a value.');
  const test = attrTest(spec);
  const hits = new Set(layer.data.features.filter(f => test(f.properties)).map(f => f.properties.__fid));
  const sel = combineSelection(layer, hits, fm.mode);
  setSelection(layer, sel);
  return { msg: `${sel.size} of ${layer.data.features.length} features selected in “${layer.name}”.`, sql: `WHERE ${attrExpression(spec)}` };
}

async function runSelectByLocation(fm, progress) {
  const target = layerById(fm.layer), source = layerById(fm.source);
  const { fids } = await geo('selectByLocation', { targets: target.data.features, shapes: toolInput(source, fm.sourceSelected),
                                                   relation: fm.relation, distance: +fm.distance, units: fm.units }, progress);
  const sel = combineSelection(target, new Set(fids), fm.mode);
  setSelection(target, sel);
  const rel = fm.relation === 'within_distance' ? `are within ${fm.distance} ${fm.units} of` : RELATIONS[fm.relation];
  return { msg: `${sel.size} of ${target.data.features.length} features selected in “${target.name}”.`,
           sql: `features of “${target.name}” that ${rel} “${source.name}”${fm.sourceSelected && selectedFids(source).size ? ' (selected features)' : ''}` };
}

function addOutput(name, feats, note) {
  if (!feats.length) throw new Error('The tool produced no features.');
  const layer = addVectorLayer({ id: `gp-${Date.now()}`, name, data: turf.featureCollection(feats), removable: true });
  zoomTo(layer);
  return `Created “${name}” with ${feats.length} feature${feats.length > 1 ? 's' : ''}.${note ? ' ' + note : ''}`;
}

function overlayNote(r) {
  return [r.lines && `${r.lines} line feature(s) kept whole where they cross.`,
          r.skipped && `${r.skipped} feature(s) with invalid geometry skipped.`].filter(Boolean).join(' ');
}

async function runBuffer(fm, progress) {
  const layer = layerById(fm.layer), d = +fm.distance;
  if (!Number.isFinite(d) || d === 0) throw new Error('Enter a non-zero distance (negative shrinks polygons).');
  const r = await geo('buffer', { feats: toolInput(layer, fm.selected), distance: d, units: fm.units, dissolve: !!fm.dissolve }, progress);
  return addOutput(`${layer.name} — buffer ${d} ${fm.units}`, r.features);
}

async function runOverlay(fm, progress, op) {
  const layer = layerById(fm.layer), other = layerById(fm.other);
  const polys = toolInput(other, fm.otherSelected).filter(isPoly);
  if (!polys.length) throw new Error(`“${other.name}” has no polygons to ${op === 'clip' ? 'clip by' : 'intersect with'}.`);
  const r = await geo(op, { feats: toolInput(layer, fm.selected), polys, prefix: other.id }, progress);
  return addOutput(`${layer.name} — ${op} ${other.name}`, r.features, overlayNote(r));
}

async function runDissolve(fm, progress) {
  const layer = layerById(fm.layer);
  const polys = toolInput(layer, fm.selected).filter(isPoly);
  if (!polys.length) throw new Error('Dissolve works on polygons; this layer has none.');
  const r = await geo('dissolve', { polys, field: fm.field || null }, progress);
  return addOutput(`${layer.name} — dissolve${fm.field ? ` by ${fm.field}` : ''}`, r.features);
}

const RUNNERS = {
  select_attr: runSelectByAttributes, select_loc: runSelectByLocation, buffer: runBuffer,
  clip: (fm, p) => runOverlay(fm, p, 'clip'), intersect: (fm, p) => runOverlay(fm, p, 'intersect'), dissolve: runDissolve,
};

// ---------- Geoprocessing panel ----------
function toolDefaults(tool, layers) {
  const first = layers[0]?.id, second = (layers[1] || layers[0])?.id;
  const base = { layer: first, selected: false, mode: 'new' };
  return {
    select_attr: { ...base, field: null, op: '>', value: '' },
    select_loc: { ...base, source: second, relation: 'intersect', distance: 500, units: 'meters', sourceSelected: false },
    buffer: { ...base, distance: 500, units: 'meters', dissolve: false },
    clip: { ...base, other: second, otherSelected: false },
    intersect: { ...base, other: second, otherSelected: false },
    dissolve: { ...base, field: '' },
  }[tool];
}

function renderToolsPanel(body) {
  const layers = vectorLayers();
  if (!layers.length) { body.innerHTML = '<p class="muted">No vector layers. Add data first.</p>'; return; }
  const fm = gis.form[gis.tool] || (gis.form[gis.tool] = toolDefaults(gis.tool, layers));
  ['layer', 'source', 'other'].forEach(k => { if (k in fm && !layerById(fm[k])) fm[k] = layers[0].id; });
  const layer = layerById(fm.layer), fields = layerFields(layer);
  if (gis.tool === 'select_attr' && !fields.has(fm.field)) fm.field = pickField(fields, 'number', ['area_ha']) ?? [...fields.keys()][0] ?? null;

  const opt = (v, label, sel) => `<option value="${esc(v)}" ${sel ? 'selected' : ''}>${esc(label)}</option>`;
  const layerSel = (key, label) => `<label>${label}<br><select data-f="${key}">${layers.map(l => opt(l.id, l.name, l.id === fm[key])).join('')}</select></label>`;
  const selOnly = (key, lyrKey) => { const n = selectedFids(layerById(fm[lyrKey])).size;
    return n ? `<label class="check"><input type="checkbox" data-f="${key}" ${fm[key] ? 'checked' : ''}> Use the ${n} selected features only</label>` : ''; };
  const units = `<select data-f="units">${['meters', 'kilometers'].map(u => opt(u, u, u === fm.units)).join('')}</select>`;
  const modeSel = `<label>Selection type<br><select data-f="mode">${Object.entries(SEL_MODES).map(([k, v]) => opt(k, v, k === fm.mode)).join('')}</select></label>`;

  let form = '';
  if (gis.tool === 'select_attr') {
    const numeric = fields.get(fm.field) === 'number';
    const values = [...new Set(layer.data.features.map(f => f.properties[fm.field]).filter(v => v != null && typeof v !== 'object'))].slice(0, 200);
    form = layerSel('layer', 'Layer') + modeSel + `
      <div class="sym-grid">
        <label>Field<br><select data-f="field">${[...fields.keys()].map(k => opt(k, k, k === fm.field)).join('')}</select></label>
        <label>Operator<br><select data-f="op">${Object.entries(OPS).filter(([k]) => numeric ? k !== 'contains' : true).map(([k, v]) => opt(k, v, k === fm.op)).join('')}</select></label>
      </div>
      ${fm.op === 'empty' ? '' : `<label>Value<br><input data-f="value" list="gpValues" value="${esc(fm.value)}" ${numeric ? 'inputmode="decimal"' : ''} autocomplete="off">
        <datalist id="gpValues">${values.map(v => `<option value="${esc(v)}">`).join('')}</datalist></label>`}`;
  }
  if (gis.tool === 'select_loc') form = layerSel('layer', 'Select features from') + modeSel + `
      <label>Relationship<br><select data-f="relation">${Object.entries(RELATIONS).map(([k, v]) => opt(k, `that ${v}`, k === fm.relation)).join('')}</select></label>
      ${fm.relation === 'within_distance' ? `<label>Distance<br><input data-f="distance" type="number" value="${esc(fm.distance)}"> ${units}</label>` : ''}
      ${layerSel('source', 'Selecting features')}${selOnly('sourceSelected', 'source')}`;
  if (gis.tool === 'buffer') form = layerSel('layer', 'Input layer') + selOnly('selected', 'layer') + `
      <label>Distance<br><input data-f="distance" type="number" value="${esc(fm.distance)}"> ${units}</label>
      <label class="check"><input type="checkbox" data-f="dissolve" ${fm.dissolve ? 'checked' : ''}> Dissolve all buffers into one</label>`;
  if (gis.tool === 'clip' || gis.tool === 'intersect') form = layerSel('layer', 'Input layer') + selOnly('selected', 'layer') +
      layerSel('other', gis.tool === 'clip' ? 'Clip by (polygons)' : 'Intersect with (polygons)') + selOnly('otherSelected', 'other');
  if (gis.tool === 'dissolve') form = layerSel('layer', 'Input layer') + selOnly('selected', 'layer') + `
      <label>Dissolve field (optional)<br><select data-f="field">${opt('', '(none: merge everything)', !fm.field)}${[...fields.keys()].map(k => opt(k, k, k === fm.field)).join('')}</select></label>`;

  const isSelect = TOOLS[gis.tool].group === 'Select';
  const selCount = selectedFids(layer).size;
  body.innerHTML = `
    <div class="section"><label>Tool<br><select id="gpTool">${['Select', 'Analyse'].map(g => `<optgroup label="${g}">${
      Object.entries(TOOLS).filter(([, t]) => t.group === g).map(([k, t]) => opt(k, t.name, k === gis.tool)).join('')}</optgroup>`).join('')}</select></label></div>
    <div class="section sym-controls gp-form">${form}</div>
    <div class="section card-actions">
      <button class="btn primary" id="gpRun" ${gis.toolBusy ? 'disabled' : ''}>${gis.toolBusy ? 'Running…' : 'Run'}</button>
      ${isSelect && selCount ? `<button class="btn" id="gpClear">Clear selection (${selCount})</button><button class="btn" id="gpExport">Selection → new layer</button>` : ''}
    </div>
    ${gis.toolMsg ? `<div class="section gp-result">${gis.toolMsg}</div>` : ''}
    <p class="muted small">Outputs are new layers in Contents: the change regions themselves are never changed.
      ${layer.id === CHANGE_ID && isSelect ? 'Selected change regions also go to the ✦ AI report.' : ''}</p>`;

  $('#gpTool').onchange = e => { gis.tool = e.target.value; gis.toolMsg = ''; renderPanel(); };
  body.querySelectorAll('[data-f]').forEach(el => {
    const k = el.dataset.f;
    const rerender = ['layer', 'field', 'op', 'relation', 'source', 'other'].includes(k) || el.type === 'checkbox';
    el[el.tagName === 'SELECT' || el.type === 'checkbox' ? 'onchange' : 'oninput'] = () => {
      fm[k] = el.type === 'checkbox' ? el.checked : el.value;
      if (k === 'layer') { fm.selected = false; if ('field' in fm) fm.field = gis.tool === 'dissolve' ? '' : null; }
      if (rerender) renderPanel();
    };
  });
  $('#gpRun').onclick = () => runTool();
  const c = $('#gpClear'); if (c) c.onclick = () => { setSelection(layer, new Set()); gis.toolMsg = ''; renderPanel(); };
  const x = $('#gpExport'); if (x) x.onclick = () => {
    const feats = toolInput(layer, true).map(f => turf.feature(f.geometry, cleanProps(f.properties)));
    gis.toolMsg = esc(addOutput(`${layer.name} — selection`, feats)); renderPanel();
  };
}

async function runTool() {
  gis.toolBusy = true; gis.toolMsg = ''; renderPanel();
  const t0 = performance.now();
  const progress = p => { const b = $('#gpRun'); if (b && gis.toolBusy) b.textContent = `Running… ${Math.round(p * 100)}%`; };
  try {
    const r = await RUNNERS[gis.tool](gis.form[gis.tool], progress);
    const secs = ((performance.now() - t0) / 1000).toFixed(1);
    gis.toolMsg = typeof r === 'string' ? `${esc(r)} <span class="muted">(${secs} s)</span>`
      : `${esc(r.msg)}<pre class="sql">${esc(r.sql)}</pre>`;
  } catch (err) {
    gis.toolMsg = `<span class="chip unsupported">Error</span> ${esc(err.message)}`;
  }
  gis.toolBusy = false; renderPanel();
}
