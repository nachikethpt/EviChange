/* EviChange GIS — Geo-VLM check in "Find changes" (D7 candidate check).
 * Sends selected change regions, one at a time, to POST /api/vlm/check: the backend renders
 * before/after chips in Earth Engine and asks Qwen2.5-VL (on a Colab GPU, see
 * notebooks/EviChange_vlm_server.ipynb) whether it sees real change inside the region's box.
 * The answer is shown next to the detector's change types. "No change" answers flag a region on
 * the map; they never hide or delete it. Loaded BEFORE app.js; see explore.js.
 */
'use strict';

const GV_MAX = 20;   // regions per click, largest first
const GV_SHOW_REJECTED_DEFAULT = false;   // D7: regions the model sees no change in are hidden, not removed. Flip to true to show them dimmed instead.
const gv = { showRejected: GV_SHOW_REJECTED_DEFAULT, status: null, results: new Map(), running: false, stop: false,
  done: 0, total: 0, error: '', chips: null, source: 'sentinel2', planet: null, planetLoading: false,
  planetError: '', beforeMonth: '', afterMonth: '', revision: 0 };
const GV_CHIPS = { rgb: 'True colour', rgb_swir: 'True colour + SWIR', rgb_swir_cir: 'True colour + SWIR + infrared',
  planet_rgb: 'Planet true colour', planet_rgb_nir: 'Planet true colour + NIR' };
const GV_AGREE = {
  agrees:         { icon: '✓', label: 'agrees with the detector', cls: 'supported' },
  partly:         { icon: '≈', label: 'partly agrees on the type', cls: 'uncertain' },
  change_only:    { icon: '✓', label: 'sees change (type not comparable)', cls: 'supported' },
  different_type: { icon: '≠', label: 'sees a different type of change', cls: 'uncertain' },
  disagrees:      { icon: '✗', label: 'sees no change', cls: 'unsupported' },
  unsure:         { icon: '?', label: 'unsure', cls: '' },
  different_period: { icon: '◷', label: 'different dates; not compared with the detector', cls: '' },
};

/** True while a region the model saw no change in should be hidden (it never leaves the data; "Show rejected" brings it back). */
function vlmHidden(id) {
  const r = gv.results.get(id);
  return !gv.showRejected && r?.status === 'checked' && r.comparable !== false && r.verdict === 'no_change';
}

function resetVlmResults() {
  gv.revision++; gv.stop = true; gv.running = false;
  const old = [...gv.results.keys()]; gv.results.clear(); old.forEach(flagRegion); applyFilter();
}

async function loadPlanetCheckMonths() {
  if (gv.planetLoading) return;
  gv.planetLoading = true; gv.planetError = '';
  if (state.panel === 'changes') renderPanel();
  try {
    const r = await fetch('/api/planet/months');
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || r.statusText);
    gv.planet = body;
    const months = body.months.filter(m => m.date).map(m => m.month);
    if (!months.includes(gv.beforeMonth)) gv.beforeMonth = months[0] || '';
    if (!months.includes(gv.afterMonth)) gv.afterMonth = months[months.length - 1] || '';
  } catch (err) { gv.planet = null; gv.planetError = err.message; }
  gv.planetLoading = false;
  if (state.panel === 'changes') renderPanel();
}

function vlmSelectionHtml() {
  if (gv.source !== 'planet') return '';
  return `<p class="muted small">Planet: ${esc(gv.beforeMonth)} → ${esc(gv.afterMonth)}, ${esc(GV_CHIPS[gv.chips] || 'true colour + NIR')}. Change dates in the Find changes list. The detector's dates may differ.</p>`;
}

async function loadVlmStatus() {
  try { gv.status = await (await fetch('/api/vlm/status')).json(); }
  catch (err) { gv.status = { available: false, detail: 'Backend not reachable.' }; }
  if (state.panel === 'changes') renderPanel();
}

function vlmBadge(id) {
  const r = gv.results.get(id); if (!r) return '';
  if (r.status === 'blocked') return '<span class="chip" title="Labelled evaluation site: not checked">🛰 🔒</span>';
  if (r.status === 'error') return `<span class="chip unsupported" title="${esc(r.detail)}">🛰 !</span>`;
  if (r.status === 'insufficient_imagery') return '<span class="chip" title="Not enough clear Planet imagery; no model judgement">🛰 ☁</span>';
  const a = GV_AGREE[r.agreement] || GV_AGREE.unsure;
  return `<span class="chip ${a.cls}" title="Geo-VLM ${esc(a.label)}">🛰 ${a.icon}</span>`;
}

/** Flag regions the VLM sees no change in (darker outline), via feature-state on the change layer. */
function flagRegion(id) {
  const m = explore.meta.get(id), r = gv.results.get(id);
  if (m) map.setFeatureState({ source: CHANGE_ID, id: m.fid }, { vlmNo: r?.comparable !== false && r?.verdict === 'no_change' });
}

async function checkRegions(ids) {
  if (gv.running) return;
  const revision = ++gv.revision;
  const request = { run_id: state.currentRunId, source: gv.source, chips: gv.chips ||
    (gv.source === 'planet' ? 'planet_rgb_nir' : gv.status?.default_chips),
    ...(gv.source === 'planet' ? { before_month: gv.beforeMonth, after_month: gv.afterMonth } : {}) };
  gv.running = true; gv.stop = false; gv.done = 0; gv.total = ids.length; gv.error = '';
  renderPanel();
  for (const id of ids) {
    if (gv.stop) break;
    if (!gv.results.has(id) || ['error', 'insufficient_imagery'].includes(gv.results.get(id).status)) {
      try {
        const res = await fetch('/api/vlm/check', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                   body: JSON.stringify({ ...request, region_id: id }) });
        const body = await res.json();
        if (revision !== gv.revision) return;
        if (res.status === 503) { gv.error = body.detail; gv.status = { ...gv.status, available: false, detail: body.detail }; break; }
        gv.results.set(id, res.ok ? body : { status: 'error', detail: body.detail || res.statusText });
      } catch (err) {
        if (revision !== gv.revision) return;
        gv.results.set(id, { status: 'error', detail: err.message });
      }
      flagRegion(id);
      applyFilter();   // a region the model rejects leaves the map and the list now
    }
    gv.done++;
    if (state.panel === 'changes') renderPanel();
  }
  if (revision !== gv.revision) return;
  gv.running = false;
  if (state.panel === 'changes') renderPanel();
}

/** The "Check with Geo-VLM" block of the Find changes list view. */
function vlmSectionHtml(results, matches = results) {
  const n = Math.min(results.length, GV_MAX), st = gv.status;
  const counts = {};
  const rejected = matches.filter(f => { const r = gv.results.get(f.properties.id); return r?.status === 'checked' && r.comparable !== false && r.verdict === 'no_change'; }).length;
  matches.forEach(f => { const r = gv.results.get(f.properties.id); if (r) { const k = r.status === 'checked' ? r.agreement : r.status; counts[k] = (counts[k] || 0) + 1; } });
  const summary = Object.entries(counts).map(([k, v]) =>
    k === 'blocked' ? `🔒 ${v} labelled site${v > 1 ? 's' : ''} skipped` : k === 'error' ? `! ${v} failed` : k === 'insufficient_imagery' ? `☁ ${v} without enough clear imagery`
      : `${GV_AGREE[k]?.icon ?? '?'} ${v} ${GV_AGREE[k]?.label ?? k}`).join(' · ');
  let action;
  if (gv.running) action = `<button class="btn" id="gvStop">Stop</button> <span class="muted">Checking ${gv.done + 1} of ${gv.total}… (≈20–40 s each)</span>`;
  else if (!st) action = '<span class="muted">Connecting…</span>';
  else if (!st.available) action = `<button class="btn" id="gvRetry">Retry connection</button><p class="muted small">${esc(st.detail)}</p>`;
  else action = n ? `<button class="btn primary" id="gvRun">🛰 Check ${n === results.length ? 'these' : `the ${n} largest`} ${n} region${n > 1 ? 's' : ''} with Geo-VLM</button>` : '';
  const planetReady = gv.beforeMonth && gv.afterMonth && gv.beforeMonth < gv.afterMonth && !gv.planetError;
  if (gv.source === 'planet' && st?.available && !gv.running && !planetReady) action = '<p class="muted">Choose two delivered Planet months, before then after.</p>';
  const chips = gv.chips || (gv.source === 'planet' ? 'planet_rgb_nir' : st?.default_chips);
  const chipSets = gv.source === 'planet' ? (st?.planet_chip_sets || ['planet_rgb', 'planet_rgb_nir']) : st?.chip_sets;
  const chipPicker = chipSets ? `<label class="small muted">Images
    <select id="gvChips" ${gv.running ? 'disabled' : ''}>${chipSets.map(c =>
      `<option value="${esc(c)}" ${c === chips ? 'selected' : ''}>${esc(GV_CHIPS[c] || c)}</option>`).join('')}</select></label>` : '';
  const monthPicker = when => `<label class="small muted">${when === 'before' ? 'Before' : 'After'} acquisition
    <select id="gv${when === 'before' ? 'Before' : 'After'}" ${gv.running ? 'disabled' : ''}><option value="">Choose a delivered month</option>
    ${(gv.planet?.months || []).filter(r => r.date).map(r => `<option value="${esc(r.month)}" ${r.month === gv[`${when}Month`] ? 'selected' : ''}>${esc(r.date)} · ${r.clear_share == null ? 'clear share unavailable' : `${Math.round(r.clear_share * 100)}% clear`}</option>`).join('')}</select></label>`;
  return `<div class="section gv"><div class="pane-subtitle">Geo-VLM check ${st?.available ? `<span class="muted">· ${esc(st.model || '')}</span>` : ''}</div>
    <label class="small muted">Source <select id="gvSource" ${gv.running ? 'disabled' : ''}>
      <option value="sentinel2" ${gv.source === 'sentinel2' ? 'selected' : ''}>Sentinel-2 · detector windows</option>
      <option value="planet" ${gv.source === 'planet' ? 'selected' : ''}>Planet · selected acquisition dates (3 m)</option></select></label>
    ${gv.source === 'planet' ? `${monthPicker('before')}${monthPicker('after')}
      <p class="muted small">${gv.planetLoading ? 'Loading delivered months…' : esc(gv.planetError)}
      Planet has no SWIR. Clouds and missing coverage are not change; at least half the box must be clear on both dates.
      Checks outside the detector's date windows are not compared with it and never hide its detections. Imagery © Planet Labs PBC.</p>
      ${gv.planetError ? '<button class="btn" id="gvPlanetRetry">Retry Planet imagery</button>' : ''}` : ''}
    ${chipPicker}
    ${action}
    ${gv.error ? `<p class="chip unsupported">${esc(gv.error)}</p>` : ''}
    ${summary ? `<p class="small">${summary}</p>` : ''}
    ${rejected ? `<p class="small"><b>${rejected} region${rejected > 1 ? 's' : ''} the model sees no change in ${gv.showRejected ? 'shown' : 'hidden'}.</b>
      <button class="linkish" id="gvToggle">${gv.showRejected ? 'Hide rejected' : 'Show rejected'}</button><br>
      <span class="muted">VLM-checked, not validated: it can be wrong, and nothing is deleted.</span></p>` : ''}
    <p class="muted small">The model sees only before/after images, not the detector's numbers, and says whether the outlined box changed. A second look, not validated: on development regions it did no better than chance (D15).
      ${st?.labelled_sites_locked ? 'The 30 labelled evaluation sites are skipped until the Phase 4 prompts are frozen.' : ''}</p></div>`;
}

function wireVlmSection(results) {
  const ids = results.slice(0, GV_MAX).map(f => f.properties.id);
  const run = $('#gvRun'); if (run) run.onclick = () => checkRegions(ids);
  const stop = $('#gvStop'); if (stop) stop.onclick = () => { gv.stop = true; };
  const pick = $('#gvChips');
  if (pick) pick.onchange = () => {   // results belong to one image set: start over with the new one
    gv.chips = pick.value; resetVlmResults(); renderPanel();
  };
  const source = $('#gvSource'); if (source) source.onchange = () => {
    gv.source = source.value; gv.chips = null; resetVlmResults(); renderPanel();
    if (gv.source === 'planet') loadPlanetCheckMonths();
  };
  ['Before', 'After'].forEach(when => { const el = $(`#gv${when}`); if (el) el.onchange = () => {
    gv[`${when.toLowerCase()}Month`] = el.value; resetVlmResults(); renderPanel();
  }; });
  const planetRetry = $('#gvPlanetRetry'); if (planetRetry) planetRetry.onclick = loadPlanetCheckMonths;
  const tog = $('#gvToggle');
  if (tog) tog.onclick = () => { gv.showRejected = !gv.showRejected; applyFilter(); renderPanel(); };
  const retry = $('#gvRetry'); if (retry) retry.onclick = () => { gv.status = null; gv.error = ''; renderPanel(); loadVlmStatus(); };
}

/** Result block for one region's detail card. */
function vlmCardHtml(id) {
  const r = gv.results.get(id), st = gv.status;
  const button = gv.running || r?.status === 'checked' ? '' : st?.available
    ? `<button class="btn" id="gvOne">🛰 ${r ? 'Try again' : 'Check with Geo-VLM'}</button>`
    : `<p class="muted small">Geo-VLM not connected: ${esc(st?.detail || '…')}</p>`;
  if (!r) return `<div class="section"><div class="pane-subtitle">Geo-VLM check</div>${vlmSelectionHtml()}${button}</div>`;
  if (r.status === 'blocked') return `<div class="section"><div class="pane-subtitle">Geo-VLM check</div><p class="muted">🔒 ${esc(r.detail)}</p></div>`;
  if (r.status === 'error' || r.status === 'insufficient_imagery') return `<div class="section"><div class="pane-subtitle">Geo-VLM check</div>${vlmSelectionHtml()}<p class="chip unsupported">${esc(r.detail)}</p>${button}</div>`;
  const a = GV_AGREE[r.agreement] || GV_AGREE.unsure;
  const names = ts => ts.length ? ts.map(t => t === 'other' ? 'other' : info(t).short).join(' + ') : '—';
  return `<div class="section"><div class="pane-subtitle">Geo-VLM check</div>
    <p><span class="chip ${a.cls}">🛰 ${a.icon} ${esc(a.label)}</span></p>
    <div class="facts">
      <div><span class="muted">Geo-VLM sees</span><b>${esc(r.verdict === 'change' ? names(r.change_types) : r.verdict.replace('_', ' '))}</b></div>
      <div><span class="muted">Detector ${r.comparable === false ? '(different dates)' : 'says'}</span><b>${esc(names(r.detector_types))}</b></div>
    </div>
    <p class="explain">“${esc(r.reason)}”</p>
    ${r.source === 'planet' ? `<p class="muted small">Planet acquisitions ${r.acquisitions.map(a => esc(a.date)).join(' → ')}; box clear shares ${r.box_clear_share.map(v => `${Math.round(v * 100)}%`).join(' / ')}.
      Detector windows: ${r.detector_windows.map(w => esc(w.join(' to '))).join(' → ')}. ${esc(r.attribution)}</p>` : ''}
    <p class="muted small">${esc(r.model)} · ${esc(r.prompt_version)}${r.chips ? ` · ${esc(GV_CHIPS[r.chips] || r.chips)}` : ''}${r.parse_ok ? '' : ' · answer could not be parsed'} · VLM-checked, not validated.</p>
    <details><summary>Raw model answer</summary><pre>${esc(r.raw)}</pre></details>
    ${button}</div>`;
}

function wireVlmCard(id) {
  const b = $('#gvOne');
  if (b) b.onclick = () => { gv.results.delete(id); checkRegions([id]).then(() => { if (explore.regionId === id) renderPanel(); }); };
}
