// Shoreline change panel (D11, Phases 11/15): the shoreline through time with a slider, the transects
// coloured by how the shoreline moved, and one transect's position series as a chart.
//   yearly  = one tide-averaged shoreline per dry season (Oct-Mar), 2015-16 .. 2025-26 (years.json)
//   monthly = one shoreline per month, Oct 2024 .. Sep 2026 (moves with the tide; shorelines.geojson),
//             with the Planet 3 m shoreline and image of the month where there is one (Oct 2024 .. Sep 2025, planet.json)
// Uses app.js's map, $, esc and alertBox; renderShorelinePanel() is called from renderPanel().

const SHORE_COLORS = { advancing: '#22c55e', retreating: '#ef4444', stable: '#94a3b8', unconfirmed: '#f59e0b', too_few: '#475569' };
const SHORE_TEXT = { advancing: 'advancing (land gained)', retreating: 'retreating (sea moved in)', stable: 'stable',
                     unconfirmed: 'radar moved, optical did not confirm', too_few: 'too few positions' };
const shore = { mode: 'years', labels: [], lines: [], transects: null, idx: 0, ref: true, timer: null,
                tid: null, detail: null, loaded: null,
                planet: null, planetLines: [], planetOn: true, planetImg: false, imgReq: 0 };
const PLANET_COLOR = '#e879f9';

function shoreEnsureLayers() {
  if (map.getSource('shore-tr')) return;
  const empty = { type: 'FeatureCollection', features: [] };
  ['shore-tr', 'shore-ref', 'shore-cur', 'shore-planet'].forEach(id => map.addSource(id, { type: 'geojson', data: empty }));
  map.addLayer({ id: 'shore-tr', type: 'line', source: 'shore-tr', paint: {
    'line-color': ['match', ['get', 'change'], ...Object.entries(SHORE_COLORS).flat(), '#475569'],
    'line-width': ['match', ['get', 'change'], ['advancing', 'retreating'], 3, 'unconfirmed', 2, 1],
    'line-opacity': ['match', ['get', 'change'], 'too_few', 0.25, 0.85] } });
  map.addLayer({ id: 'shore-ref', type: 'line', source: 'shore-ref', paint: {
    'line-color': '#e2e8f0', 'line-width': 1.5, 'line-dasharray': [2, 2], 'line-opacity': 0.8 } });
  map.addLayer({ id: 'shore-cur', type: 'line', source: 'shore-cur', paint: { 'line-color': '#22d3ee', 'line-width': 2.5 } });
  map.addLayer({ id: 'shore-planet', type: 'line', source: 'shore-planet', paint: { 'line-color': PLANET_COLOR, 'line-width': 2 } });
  // the transect whose chart is open
  map.addLayer({ id: 'shore-sel', type: 'line', source: 'shore-tr', filter: ['==', ['get', 'id'], ''], paint: {
    'line-color': '#facc15', 'line-width': 6, 'line-opacity': 0.95 } });
  map.on('click', 'shore-tr', e => { const f = e.features[0]; if (f) shoreSelect(f.properties.id); });
  map.on('mouseenter', 'shore-tr', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'shore-tr', () => { map.getCanvas().style.cursor = ''; });
}

function shoreSetVisible(on) {
  if (!on) shorePlanetImage(null);
  ['shore-tr', 'shore-ref', 'shore-cur', 'shore-planet', 'shore-sel'].forEach(id => {
    if (!map.getLayer(id)) return;
    map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
    if (on) map.moveLayer(id);                      // above the change regions and the other Contents layers
  });
}

async function shoreLoad(mode) {
  shoreStop();
  shore.mode = mode; shore.tid = null; shore.detail = null;
  if (map.getLayer('shore-sel')) map.setFilter('shore-sel', ['==', ['get', 'id'], '']);
  const get = async url => { const r = await fetch(url); if (!r.ok) throw new Error((await r.json()).detail || r.statusText); return r.json(); };
  try {
    if (mode === 'years') {
      const [lines, tr] = await Promise.all([get('/api/shoreline/years/lines'), get('/api/shoreline/years/transects')]);
      shore.lines = lines.features; shore.labels = lines.features.map(f => f.properties.season); shore.transects = tr;
    } else {
      const [lines, tr] = await Promise.all([get('/api/shoreline/lines?kind=month'), get('/api/shoreline/transects')]);
      shore.lines = lines.features; shore.labels = lines.features.map(f => f.properties.month); shore.transects = tr;
      if (!shore.planet) {                            // Planet is optional: no planet.json yet = no Planet rows
        try {
          const [pl, plines] = await Promise.all([get('/api/shoreline/planet'), get('/api/shoreline/planet/lines')]);
          shore.planet = pl; shore.planetLines = plines.features;
        } catch (err) { shore.planet = { error: err.message }; shore.planetLines = []; }
      }
    }
  } catch (err) { alertBox(`Shoreline: ${err.message}`); shore.lines = []; shore.labels = []; shore.transects = null; }
  for (let i = 0; i < 1200 && !map.style?._loaded; i++) await new Promise(r => setTimeout(r, 100));   // addSource throws mid-load
  shoreEnsureLayers();
  map.getSource('shore-tr').setData(shore.transects || { type: 'FeatureCollection', features: [] });
  if (shore.loaded === null && shore.transects?.features.length) map.fitBounds(turf.bbox(shore.transects), { padding: 40 });
  shore.loaded = mode;
  shore.idx = Math.max(0, shore.labels.length - 1);
  shoreSetVisible(true);
  shoreShow(shore.idx);
  renderPanel();
}

function shoreShow(i) {
  shore.idx = i;
  const fc = feats => ({ type: 'FeatureCollection', features: feats });
  map.getSource('shore-cur')?.setData(fc(shore.lines[i] ? [shore.lines[i]] : []));
  map.getSource('shore-ref')?.setData(fc(shore.ref && i > 0 && shore.lines[0] ? [shore.lines[0]] : []));
  const lab = document.getElementById('shLabel'); if (lab) lab.textContent = shoreLabel(shore.labels[i]);
  const sl = document.getElementById('shSlider'); if (sl && +sl.value !== i) sl.value = i;
  const ch = document.getElementById('shChart'); if (ch) ch.innerHTML = shoreChart();
  const month = shore.mode === 'months' ? shore.labels[i] : null;
  const pline = month && shore.planetOn ? shore.planetLines.find(f => f.properties.month === month) : null;
  map.getSource('shore-planet')?.setData(fc(pline ? [pline] : []));
  shorePlanetImage(month && shore.planetImg && shorePlanetMonth(month) ? month : null);
  const pn = document.getElementById('shPlanetNote'); if (pn) pn.innerHTML = shorePlanetNote(month);
}

// Planet (D12): one clear day per month, Oct 2024 - Sep 2025 (Feb 2025 not delivered)
function shorePlanetMonth(month) {
  const p = shore.planet;
  if (!p || p.error) return null;
  const i = p.months.indexOf(month);
  return i < 0 ? null : { month, date: p.dates[i] };
}

function shorePlanetNote(month) {
  if (!month) return '';
  const pm = shorePlanetMonth(month);
  if (!pm) return `No Planet image for ${esc(shoreLabel(month))}.`;
  const d = new Date(pm.date).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  const row = shore.planet.compare?.per_month.find(r => r.month === month);
  return `Planet image of <b>${esc(d)}</b>` + (row && row.n ? `: against the radar line this month, median difference ${row.median_abs_m} m over ${row.n} transects.` : '.');
}

async function shorePlanetImage(month) {
  const req = ++shore.imgReq;
  const drop = () => { if (map.getLayer('shore-pimg')) map.removeLayer('shore-pimg'); if (map.getSource('shore-pimg')) map.removeSource('shore-pimg'); };
  if (!month) { drop(); return; }
  try {
    const r = await fetch(`/api/planet/layer?month=${month}&kind=rgb`);
    const t = await r.json();
    if (!r.ok) throw new Error(t.detail || r.statusText);
    if (req !== shore.imgReq) return;               // the slider moved on meanwhile
    drop();
    map.addSource('shore-pimg', { type: 'raster', tiles: t.tiles, tileSize: 256, attribution: t.attribution });
    map.addLayer({ id: 'shore-pimg', type: 'raster', source: 'shore-pimg' }, map.getLayer('shore-tr') ? 'shore-tr' : undefined);
  } catch (err) { if (req === shore.imgReq) { drop(); alertBox(`Planet image: ${err.message}`); } }
}

const PLANET_CORROB_TEXT = { confirmed: 'Planet confirms the radar trend', not_confirmed: 'Planet does not confirm the radar trend',
  pending_coverage: 'Planet check pending: no Planet images yet for the last radar quarter (Jul–Sep 2026)',
  tidal_uncertainty: 'Planet check withheld: tidal flat', no_radar_trend: '' };
function shorePlanetCorroboration(c) {
  if (!c || !PLANET_CORROB_TEXT[c.status]) return '';
  const pos = c.positions_m.every(v => v != null) ? ` (Planet ${c.positions_m.map(v => `${v} m`).join(' → ')}${c.shift_m != null ? `, shift ${c.shift_m} m` : ''})` : '';
  return `<p class="muted">${esc(PLANET_CORROB_TEXT[c.status])}${esc(pos)}. Planet months per end quarter: ${c.n.join(' / ')} (2 needed each); single days, no tide correction.</p>`;
}

function shorePlanetSummary() {
  const c = shore.planet?.compare;
  if (!c) return '';
  const line = (label, st) => st && st.n ? `<div>${label}: median ${st.median_abs_m} m, ${Math.round(st.within_20m * 100)} % within 20 m <span class="muted">(${st.n} positions)</span></div>` : '';
  return `<div class="muted" style="margin-top:4px">Planet against radar, same transect and month:</div>
    ${line('dry months (Oct–Mar)', c.dry)}${line('monsoon months (Apr–Sep)', c.monsoon)}${line('Planet dry months vs the 2024-25 yearly line', c.yearly)}`;
}

function shoreLabel(l) {
  if (!l) return '–';
  if (shore.mode === 'years') return `dry season ${l} (Oct ${l.slice(0, 4)} – Mar 20${l.slice(5)})`;
  return new Date(`${l}-15`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
}

function shorePlay() {
  if (shore.timer) return shoreStop();
  if (shore.idx >= shore.labels.length - 1) shoreShow(0);
  shore.timer = setInterval(() => {
    if (shore.idx >= shore.labels.length - 1) return shoreStop();
    shoreShow(shore.idx + 1);
  }, shore.mode === 'years' ? 900 : 500);
  const b = document.getElementById('shPlay'); if (b) b.textContent = '❚❚ Pause';
}

function shoreStop() {
  clearInterval(shore.timer); shore.timer = null;
  const b = document.getElementById('shPlay'); if (b) b.textContent = '▶ Play';
}

async function shoreSelect(tid) {
  shore.tid = tid; shore.detail = null;
  if (map.getLayer('shore-sel')) map.setFilter('shore-sel', ['==', ['get', 'id'], tid || '']);
  if (state.panel !== 'shoreline') openPanel('shoreline'); else renderPanel();
  try { shore.detail = await (await fetch(`/api/shoreline/transects/${encodeURIComponent(tid)}`)).json(); }
  catch (err) { shore.detail = { error: err.message }; }
  if (shore.tid === tid) renderPanel();
}

function shoreSeries() {
  const d = shore.detail;
  if (!d || d.error) return null;
  if (shore.mode === 'years') return d.yearly && { stats: d.yearly_stats, pts: d.yearly.map(p => ({ label: p.season, pos: p.pos, opt: p.optical })) };
  const planet = Object.fromEntries((d.planet || []).map(p => [p.month, p.pos]));
  return d.series && { stats: d, pts: d.series.map(p => ({ label: p.month, pos: p.pos, planet: planet[p.month] ?? null })) };
}

function shoreChart() {
  if (!shore.tid) return '<p class="muted">Click a transect on the map (the short lines across the coast) to see how its shoreline moved.</p>';
  if (!shore.detail) return '<p class="muted">Loading…</p>';
  if (shore.detail.error) return `<p class="muted">${esc(shore.detail.error)}</p>`;
  const s = shoreSeries();
  if (!s) return `<p class="muted">Transect ${esc(shore.tid)} is a hidden Phase 14 reference transect: its series stays blind until the reference shorelines are digitised.</p>`;
  const W = 300, H = 150, L = 34, R = 8, T = 10, B = 26;
  const vals = s.pts.flatMap(p => [p.pos, p.opt, p.planet]).filter(v => v !== null && v !== undefined);
  if (!vals.length) return `<p class="muted">No positions on transect ${esc(shore.tid)}.</p>`;
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 20) { const m = (hi + lo) / 2; lo = m - 10; hi = m + 10; }
  const x = i => L + (s.pts.length > 1 ? i / (s.pts.length - 1) : 0.5) * (W - L - R);
  const y = v => T + (hi - v) / (hi - lo) * (H - T - B);
  const path = key => s.pts.map((p, i) => p[key] === null || p[key] === undefined ? null : [x(i), y(p[key])])
    .reduce((acc, pt) => { if (!pt) acc.push([]); else acc[acc.length - 1].push(pt); return acc; }, [[]])
    .filter(r => r.length).map(r => `M${r.map(p => p.map(v => v.toFixed(1)).join(',')).join('L')}`).join('');
  const dots = key => s.pts.map((p, i) => p[key] === null || p[key] === undefined ? '' :
    `<circle cx="${x(i).toFixed(1)}" cy="${y(p[key]).toFixed(1)}" r="${key === 'pos' ? 3 : 2.5}" fill="${{ pos: '#22d3ee', opt: '#f59e0b', planet: PLANET_COLOR }[key]}"><title>${esc(p.label)}: ${p[key]} m</title></circle>`).join('');
  const change = s.stats?.change ?? s.stats?.trend;
  const rate = s.stats?.lrr === null || s.stats?.lrr === undefined ? '–' : `${s.stats.lrr > 0 ? '+' : ''}${s.stats.lrr} m/yr${s.stats.ci95 ? ` ± ${s.stats.ci95}` : ''}`;
  const tick = i => `<text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="${i === 0 ? 'start' : i === s.pts.length - 1 ? 'end' : 'middle'}" font-size="9" fill="currentColor" opacity=".7">${esc(shore.mode === 'years' ? s.pts[i].label.slice(0, 4) : s.pts[i].label.slice(2))}</text>`;
  const ticks = [0, Math.floor((s.pts.length - 1) / 2), s.pts.length - 1].filter((v, i, a) => a.indexOf(v) === i).map(tick).join('');
  return `<div class="section"><b>Transect ${esc(shore.tid)}</b>: <span style="color:${SHORE_COLORS[change] || 'inherit'}">${esc(SHORE_TEXT[change] || change || '–')}</span>, ${esc(rate)}
    <svg viewBox="0 0 ${W} ${H}" width="100%" role="img" style="color:var(--text)">
      <line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="currentColor" opacity=".25" stroke-dasharray="3 3"/>
      <line x1="${x(shore.idx).toFixed(1)}" x2="${x(shore.idx).toFixed(1)}" y1="${T}" y2="${H - B}" stroke="#22d3ee" opacity=".5"/>
      <text x="4" y="${T + 8}" font-size="9" fill="currentColor" opacity=".7">${Math.round(hi)} m</text>
      <text x="4" y="${H - B}" font-size="9" fill="currentColor" opacity=".7">${Math.round(lo)} m</text>
      <path d="${path('opt')}" fill="none" stroke="#f59e0b" stroke-width="1" stroke-dasharray="3 2"/>${dots('opt')}
      <path d="${path('pos')}" fill="none" stroke="#22d3ee" stroke-width="1.5"/>${dots('pos')}
      <path d="${path('planet')}" fill="none" stroke="${PLANET_COLOR}" stroke-width="1" stroke-dasharray="2 2"/>${dots('planet')}${ticks}
    </svg>
    <span class="muted">Shoreline position from the baseline, seaward +. ${shore.mode === 'years'
      ? 'Blue: radar, tide-averaged over each dry season; orange: optical (Sentinel-2, once its surface reflectance covers the area).'
      : 'Blue: radar, one month (moves with the tide, so expect jumps on tidal flats); pink: Planet 3 m, one day that month; the rate above is fitted to the tide-averaged quarters.'}</span>${shore.mode === 'months' ? shorePlanetCorroboration(shore.detail.planet_corroboration) : ''}</div>`;
}

function renderShorelinePanel(body) {
  if (shore.loaded !== shore.mode) { body.innerHTML = '<p class="muted">Loading shorelines…</p>'; shoreLoad(shore.mode); return; }
  const counts = {};
  (shore.transects?.features || []).forEach(f => { const c = f.properties.change ?? 'too_few'; counts[c] = (counts[c] || 0) + 1; });
  const n = shore.labels.length;
  body.innerHTML = `
    <div class="section seg"><button data-m="years" class="${shore.mode === 'years' ? 'on' : ''}">Yearly 2015–2026</button>
      <button data-m="months" class="${shore.mode === 'months' ? 'on' : ''}">Monthly 2024–2026</button></div>
    ${n ? `<div class="section"><div class="pane-subtitle" id="shLabel">${esc(shoreLabel(shore.labels[shore.idx]))}</div>
      <input type="range" id="shSlider" min="0" max="${n - 1}" step="1" value="${shore.idx}" style="width:100%">
      <div style="display:flex;justify-content:space-between" class="muted"><span>${esc(shore.labels[0])}</span><span>${esc(shore.labels[n - 1])}</span></div>
      <button class="btn" id="shPlay">${shore.timer ? '❚❚ Pause' : '▶ Play'}</button>
      <label style="margin-left:8px"><input type="checkbox" id="shRef" ${shore.ref ? 'checked' : ''}> show the first ${shore.mode === 'years' ? 'season' : 'month'} (dashed)</label></div>`
      : '<p class="muted">No shorelines to show.</p>'}
    <div class="section"><div class="pane-subtitle">Transects, by change ${shore.mode === 'years' ? 'over the ten dry seasons' : 'over the 24 months'}</div>
      ${Object.keys(SHORE_COLORS).filter(k => counts[k]).map(k =>
        `<div><span style="display:inline-block;width:18px;height:3px;background:${SHORE_COLORS[k]};vertical-align:middle;margin-right:6px"></span>${esc(SHORE_TEXT[k])}: <b>${counts[k]}</b></div>`).join('')}
      <p class="muted">${shore.mode === 'years' ? 'Each season is one tide-averaged radar shoreline (Sentinel-1, Oct–Mar); a change needs a rate whose 95 % CI excludes 0, confirmed by the optical shoreline.'
        : 'Monthly lines move with the tide (several m); the rate comes from the tide-averaged quarters.'}</p></div>
    ${shore.mode === 'months' && shore.planet && !shore.planet.error ? `<div class="section"><div class="pane-subtitle">Planet 3 m (one clear day a month, Oct 2024 – Sep 2025)</div>
      <label><input type="checkbox" id="shPlanetOn" ${shore.planetOn ? 'checked' : ''}> <span style="display:inline-block;width:18px;height:3px;background:${PLANET_COLOR};vertical-align:middle"></span> Planet shoreline</label>
      <label style="margin-left:8px"><input type="checkbox" id="shPlanetImg" ${shore.planetImg ? 'checked' : ''}> Planet image</label>
      <p id="shPlanetNote" class="muted">${shorePlanetNote(shore.labels[shore.idx])}</p>${shorePlanetSummary()}
      <p class="muted">Imagery © Planet Labs PBC.</p></div>` : ''}
    <div id="shChart">${shoreChart()}</div>
    <button class="btn" id="shHide">Hide shoreline layers</button>`;
  body.querySelectorAll('[data-m]').forEach(b => b.onclick = () => { if (b.dataset.m !== shore.mode) { shore.mode = b.dataset.m; renderPanel(); } });
  const sl = $('#shSlider'); if (sl) sl.oninput = e => { shoreStop(); shoreShow(+e.target.value); };
  const pl = $('#shPlay'); if (pl) pl.onclick = shorePlay;
  const rf = $('#shRef'); if (rf) rf.onchange = e => { shore.ref = e.target.checked; shoreShow(shore.idx); };
  const po = $('#shPlanetOn'); if (po) po.onchange = e => { shore.planetOn = e.target.checked; shoreShow(shore.idx); };
  const pi = $('#shPlanetImg'); if (pi) pi.onchange = e => { shore.planetImg = e.target.checked; shoreShow(shore.idx); };
  $('#shHide').onclick = () => { shoreStop(); shoreSetVisible(false); closePanel(); };
  shoreSetVisible(true);
}
