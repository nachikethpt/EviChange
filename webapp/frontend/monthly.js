// Monthly & coast panel (Phases 10 and 12, D11): a month slider over the Oct 2024 - Sep 2026 monthly layers,
// the monthly series as charts (gaps are drawn as gaps, never as zero), one change region's series (click a
// region while the panel is open), and the buildings near the shoreline (strips, monthly built area, new patches).
// Uses app.js's map, $, esc, alertBox, openPanel/renderPanel/closePanel and state; renderMonthlyPanel() is called from renderPanel().

const MONTHLY_LAYERS = { class: 'Land cover (Dynamic World)', water: 'Water (Sentinel-1 radar)', clear: 'Clear-sky share',
                         water_change: 'Water change', class_change: 'Land-cover change' };
const MONTHLY_LAYER_HELP = { class: 'Only months Dynamic World saw clearly (about Oct–Mar); other months are gaps.',
  water: 'Radar sees through cloud, so every month has a water mask.', clear: 'How much of the area was seen without cloud.',
  water_change: 'Water gained / lost against the chosen month.', class_change: 'Pixels whose class differs from the chosen month (clear months only).' };
const DW_COLORS = { water: '#419bdf', trees: '#397d49', grass: '#88b053', flooded_vegetation: '#7a87c6', crops: '#e49635',
                    shrub_and_scrub: '#dfc35a', built: '#c4281b', bare: '#a59b8f', snow_and_ice: '#b39fe1' };
const mon = { summary: null, months: [], idx: 0, layer: 'class', vs: 'base', on: false, region: null, regionId: null,
              coast: null, coastLoaded: false, strips: false, patches: false, req: 0, msg: '' };

const monGet = async url => { const r = await fetch(url); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); return r.json(); };
const monLabel = m => m ? new Date(`${m}-15`).toLocaleDateString(undefined, { month: 'short', year: 'numeric' }) : '–';

async function monthlyLoad() {
  try {
    mon.summary = await monGet('/api/monthly');
    mon.months = mon.summary.months.map(r => r.month);
    mon.idx = Math.min(mon.idx, mon.months.length - 1);
  } catch (err) { mon.summary = { error: err.message }; }
  try { mon.coast = await monGet('/api/coastal/monthly'); mon.seasons = await monGet('/api/coastal/seasons'); } catch (err) { mon.coast = { error: err.message }; }
  mon.coastLoaded = true;
  renderPanel();
  if (mon.months.length) monthlyShow(mon.idx);
}

function monRemoveLayer() {
  if (map.getLayer('mon-raster')) map.removeLayer('mon-raster');
  if (map.getSource('mon-raster')) map.removeSource('mon-raster');
}

async function monthlyShow(i) {
  mon.idx = i;
  const month = mon.months[i], req = ++mon.req;
  const lab = $('#monLabel'); if (lab) lab.textContent = monLabel(month);
  const ch = $('#monChart'); if (ch) ch.innerHTML = monChart();
  monSetMsg('Loading…');
  try {
    const url = `/api/monthly/layer?month=${month}&layer=${mon.layer}${mon.layer.endsWith('_change') ? `&vs=${mon.vs}` : ''}`;
    const t = await monGet(url);
    if (req !== mon.req) return;                       // a newer month was asked for meanwhile
    monRemoveLayer();
    map.addSource('mon-raster', { type: 'raster', tiles: t.tiles, tileSize: 256 });
    map.addLayer({ id: 'mon-raster', type: 'raster', source: 'mon-raster', paint: { 'raster-opacity': 0.75 } },
                 map.getLayer('shore-tr') ? 'shore-tr' : undefined);
    mon.on = true; monSetMsg('');
  } catch (err) {
    if (req !== mon.req) return;
    monRemoveLayer(); mon.on = false;
    monSetMsg(err.message);                            // e.g. "no class data in 2025-06: shown as a gap"
  }
}
function monSetMsg(t) { mon.msg = t; const el = $('#monMsg'); if (el) el.textContent = t; }

function monSvg(W, H, body) { return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" style="color:var(--text)">${body}</svg>`; }
// Polyline broken at nulls, so a gap is a gap
function monPath(vals, x, y) {
  let d = '', pen = false;
  vals.forEach((v, i) => { if (v === null || v === undefined) { pen = false; return; } d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; });
  return d;
}
function monLine({ months, series, W = 300, H = 120, fmt = v => v, title = '', cur = null }) {
  const L = 38, R = 8, T = 8, B = 22, n = months.length;
  const all = series.flatMap(s => s.vals).filter(v => v !== null && v !== undefined);
  if (!all.length) return '<p class="muted">No values in any month.</p>';
  let lo = Math.min(0, ...all), hi = Math.max(...all); if (hi === lo) hi = lo + 1;
  const x = i => L + (n > 1 ? i / (n - 1) : .5) * (W - L - R), y = v => T + (hi - v) / (hi - lo) * (H - T - B);
  const dots = s => s.vals.map((v, i) => v === null || v === undefined ? '' :
    `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.2" fill="${s.color}"><title>${esc(monLabel(months[i]))}: ${esc(fmt(v))}</title></circle>`).join('');
  const ticks = [0, Math.floor((n - 1) / 2), n - 1].map(i => `<text x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}" font-size="9" fill="currentColor" opacity=".7">${esc(months[i])}</text>`).join('');
  return `<div class="pane-subtitle">${esc(title)}</div>` + monSvg(W, H, `
    <line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}" stroke="currentColor" opacity=".2"/>
    ${cur !== null ? `<line x1="${x(cur).toFixed(1)}" x2="${x(cur).toFixed(1)}" y1="${T}" y2="${H - B}" stroke="#22d3ee" opacity=".6"/>` : ''}
    <text x="4" y="${T + 8}" font-size="9" fill="currentColor" opacity=".7">${esc(fmt(hi))}</text><text x="4" y="${y(0).toFixed(1)}" font-size="9" fill="currentColor" opacity=".7">${esc(fmt(lo))}</text>
    ${series.map(s => `<path d="${monPath(s.vals, x, y)}" fill="none" stroke="${s.color}" stroke-width="1.5"/>${dots(s)}`).join('')}${ticks}`)
    + `<div class="muted">${series.map(s => `<span style="color:${s.color}">●</span> ${esc(s.name)}`).join(' &nbsp; ')}</div>`;
}

function monChart() {
  const rows = mon.summary?.months || [], ms = rows.map(r => r.month);
  if (!rows.length) return '';
  const water = monLine({ months: ms, cur: mon.idx, title: 'Water area per month (ha, radar)', fmt: v => `${Math.round(v)} ha`,
    series: [{ name: 'water', color: '#419bdf', vals: rows.map(r => r.water_ha ?? null) }] });
  const clear = monLine({ months: ms, cur: mon.idx, title: 'Share of the area seen clear', fmt: v => `${Math.round(v * 100)} %`,
    series: [{ name: 'clear share', color: '#94a3b8', vals: rows.map(r => r.clear_share ?? null) }] });
  const r = rows[mon.idx];
  const status = r ? (r.class_status === 'clear' ? `land cover available (${r.dw_images} images)` : 'land cover is a gap this month (too cloudy)') : '';
  return `${water}${clear}<p class="muted">${esc(monLabel(r?.month))}: ${esc(status)}. Water area moves with the tide and the monsoon; read it with the clear-sky share.</p>`;
}

// ---- one change region: its class each month as coloured cells (gaps empty) and its water share ----
async function monthlySelectRegion(id) {
  mon.regionId = id; mon.region = null; renderPanel();
  try { mon.region = await monGet(`/api/monthly/regions/${encodeURIComponent(id)}`); } catch (err) { mon.region = { error: err.message }; }
  if (mon.regionId === id) renderPanel();
}
function monRegionChart() {
  if (!mon.regionId) return '<p class="muted">Click a change region on the map to see its months.</p>';
  if (!mon.region) return '<p class="muted">Loading…</p>';
  if (mon.region.error) return `<p class="muted">${esc(mon.region.error)}</p>`;
  const d = mon.region, n = d.months.length, W = 300, cw = (W - 38 - 8) / n;
  const hiddenClass = (d.class || []).every(c => c === null) && d.class_hidden;
  const cells = (d.class || []).map((c, i) => `<rect x="${(38 + i * cw).toFixed(1)}" y="2" width="${(cw - 1).toFixed(1)}" height="16" fill="${c ? DW_COLORS[c] || '#888' : 'none'}" stroke="${c ? 'none' : 'currentColor'}" stroke-opacity=".25"><title>${esc(monLabel(d.months[i]))}: ${esc(c || 'no clear view (gap)')}</title></rect>`).join('');
  return `<div class="section"><b>Region ${esc(d.id)}</b>
    ${hiddenClass ? '<p class="muted">Classes are hidden here (a labelled Phase 14 site).</p>' : monSvg(W, 22, `<text x="2" y="14" font-size="9" fill="currentColor" opacity=".7">class</text>${cells}`)}
    ${monLine({ months: d.months, cur: mon.idx, title: 'Water share of the region', fmt: v => `${Math.round(v * 100)} %`, H: 90,
      series: [{ name: 'water', color: '#419bdf', vals: d.water }, { name: 'clear', color: '#94a3b8', vals: d.clear }] })}
    <span class="muted">Empty cells are months with no clear view, not "no class".</span></div>`;
}

// ---- buildings near the shoreline (Phase 12) ----
function monCoastEnsure() {
  if (map.getSource('coast-strips')) return;
  ['coast-strips', 'coast-patches'].forEach(id => map.addSource(id, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } }));
  map.addLayer({ id: 'coast-strips', type: 'fill', source: 'coast-strips', paint: {
    'fill-color': ['match', ['get', 'strip'], '0-200', '#f59e0b', '#38bdf8'], 'fill-opacity': 0.25, 'fill-outline-color': '#e2e8f0' } });
  map.addLayer({ id: 'coast-patches', type: 'fill', source: 'coast-patches', paint: { 'fill-color': '#ef4444', 'fill-opacity': 0.7, 'fill-outline-color': '#fff' } });
}
async function monCoastToggle(kind, on) {
  mon[kind] = on;
  monCoastEnsure();
  const [src, url] = kind === 'strips' ? ['coast-strips', '/api/coastal/strips'] : ['coast-patches', '/api/coastal/patches'];
  try { map.getSource(src).setData(on ? await monGet(url) : { type: 'FeatureCollection', features: [] }); } catch (err) { alertBox(`Coast: ${err.message}`); }
}
function monCoastBlock() {
  const c = mon.coast;
  if (!c || c.error) return `<p class="muted">${esc(c?.error || 'No coastal analysis yet.')}</p>`;
  const rows = c.series, ms = rows.map(r => r.month);
  const strip = k => rows.map(r => r.strips[k]?.built_ha ?? null);
  const chg = (mon.seasons?.change || [])[0];
  const lines = chg ? ['0-200', '200-500'].map(k => { const s = chg.strips[k]; return `${k} m: ${s.net_ha > 0 ? '+' : ''}${s.net_ha} ha (+${s.gained_ha} / −${s.lost_ha})`; }) : [];
  return `<div class="section"><label><input type="checkbox" id="monStrips" ${mon.strips ? 'checked' : ''}> strips 0–200 m (orange) and 200–500 m (blue) from the Oct 2024 shoreline</label><br>
    <label><input type="checkbox" id="monPatches" ${mon.patches ? 'checked' : ''}> new built patches (red)</label>
    ${monLine({ months: ms, cur: mon.idx, title: 'Built area in the strips (ha, Dynamic World)', fmt: v => `${Math.round(v)} ha`,
      series: [{ name: '0–200 m', color: '#f59e0b', vals: strip('0-200') }, { name: '200–500 m', color: '#38bdf8', vals: strip('200-500') }] })}
    ${lines.length ? `<p class="muted">Dry season ${esc(chg.from)} → ${esc(chg.to)}, built area: ${lines.map(esc).join('; ')}.</p>` : ''}
    <p class="muted">Months Dynamic World saw on under half of a strip are gaps. Built area from a 10 m classifier is an estimate, not a building count.</p></div>`;
}

function renderMonthlyPanel(body) {
  if (!mon.coastLoaded) { body.innerHTML = '<p class="muted">Loading monthly layers…</p>'; monthlyLoad(); return; }
  if (mon.summary?.error) { body.innerHTML = `<p class="muted">${esc(mon.summary.error)}</p>`; return; }
  const n = mon.months.length;
  body.innerHTML = `
    <div class="section"><div class="pane-subtitle">Layer</div>
      <select id="monLayer" style="width:100%">${Object.entries(MONTHLY_LAYERS).map(([k, v]) => `<option value="${k}" ${k === mon.layer ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>
      <p class="muted">${esc(MONTHLY_LAYER_HELP[mon.layer])}</p>
      ${mon.layer.endsWith('_change') ? `<div class="seg"><button data-vs="base" class="${mon.vs === 'base' ? 'on' : ''}">vs first month</button><button data-vs="prev" class="${mon.vs === 'prev' ? 'on' : ''}">vs previous month</button></div>` : ''}
      <div class="pane-subtitle" id="monLabel">${esc(monLabel(mon.months[mon.idx]))}</div>
      <input type="range" id="monSlider" min="0" max="${n - 1}" step="1" value="${mon.idx}" style="width:100%">
      <div style="display:flex;justify-content:space-between" class="muted"><span>${esc(mon.months[0])}</span><span>${esc(mon.months[n - 1])}</span></div>
      <div class="muted" id="monMsg">${esc(mon.msg)}</div></div>
    <div id="monChart">${monChart()}</div>
    <div class="pane-subtitle">Change region</div>${monRegionChart()}
    <div class="pane-subtitle">Buildings near the shoreline</div>${monCoastBlock()}
    <button class="btn" id="monHide">Hide monthly layers</button>`;
  $('#monLayer').onchange = e => { mon.layer = e.target.value; renderPanel(); monthlyShow(mon.idx); };
  body.querySelectorAll('[data-vs]').forEach(b => b.onclick = () => { mon.vs = b.dataset.vs; renderPanel(); monthlyShow(mon.idx); });
  let t = null;
  $('#monSlider').oninput = e => { const i = +e.target.value; mon.idx = i; $('#monLabel').textContent = monLabel(mon.months[i]); $('#monChart').innerHTML = monChart();
                                   clearTimeout(t); t = setTimeout(() => monthlyShow(i), 250); };     // one tile request when the slider rests
  const s = $('#monStrips'); if (s) s.onchange = e => monCoastToggle('strips', e.target.checked);
  const p = $('#monPatches'); if (p) p.onchange = e => monCoastToggle('patches', e.target.checked);
  $('#monHide').onclick = () => { mon.req++; monRemoveLayer(); mon.on = false;
    ['coast-strips', 'coast-patches'].forEach(id => map.getLayer(id) && map.removeLayer(id)); ['coast-strips', 'coast-patches'].forEach(id => map.getSource(id) && map.removeSource(id));
    mon.strips = mon.patches = false; closePanel(); };
  if (mon.on === false && !mon.msg) monthlyShow(mon.idx);
}
