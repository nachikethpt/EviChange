/* EviChange GIS — Geo-VLM check in "Find changes" (D7 candidate check).
 * Sends selected change regions, one at a time, to POST /api/vlm/check: the backend renders
 * before/after chips in Earth Engine and asks Qwen2.5-VL (on a Colab GPU, see
 * notebooks/EviChange_vlm_server.ipynb) whether it sees real change inside the region's box.
 * The answer is shown next to the detector's change types. "No change" answers flag a region on
 * the map; they never hide or delete it. Loaded BEFORE app.js; see explore.js.
 */
'use strict';

const GV_MAX = 20;   // regions per click, largest first
const gv = { status: null, results: new Map(), running: false, stop: false, done: 0, total: 0, error: '', chips: null };
const GV_CHIPS = { rgb: 'True colour', rgb_swir: 'True colour + SWIR', rgb_swir_cir: 'True colour + SWIR + infrared' };
const GV_AGREE = {
  agrees:         { icon: '✓', label: 'agrees with the detector', cls: 'supported' },
  partly:         { icon: '≈', label: 'partly agrees on the type', cls: 'uncertain' },
  change_only:    { icon: '✓', label: 'sees change (type not comparable)', cls: 'supported' },
  different_type: { icon: '≠', label: 'sees a different type of change', cls: 'uncertain' },
  disagrees:      { icon: '✗', label: 'sees no change', cls: 'unsupported' },
  unsure:         { icon: '?', label: 'unsure', cls: '' },
};

async function loadVlmStatus() {
  try { gv.status = await (await fetch('/api/vlm/status')).json(); }
  catch (err) { gv.status = { available: false, detail: 'Backend not reachable.' }; }
  if (state.panel === 'changes') renderPanel();
}

function vlmBadge(id) {
  const r = gv.results.get(id); if (!r) return '';
  if (r.status === 'blocked') return '<span class="chip" title="Labelled evaluation site: not checked">🛰 🔒</span>';
  if (r.status === 'error') return `<span class="chip unsupported" title="${esc(r.detail)}">🛰 !</span>`;
  const a = GV_AGREE[r.agreement] || GV_AGREE.unsure;
  return `<span class="chip ${a.cls}" title="Geo-VLM ${esc(a.label)}">🛰 ${a.icon}</span>`;
}

/** Flag regions the VLM sees no change in (darker outline), via feature-state on the change layer. */
function flagRegion(id) {
  const m = explore.meta.get(id), r = gv.results.get(id);
  if (m) map.setFeatureState({ source: CHANGE_ID, id: m.fid }, { vlmNo: r?.verdict === 'no_change' });
}

async function checkRegions(ids) {
  gv.running = true; gv.stop = false; gv.done = 0; gv.total = ids.length; gv.error = '';
  renderPanel();
  for (const id of ids) {
    if (gv.stop) break;
    if (!gv.results.has(id) || gv.results.get(id).status === 'error') {
      try {
        const res = await fetch('/api/vlm/check', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                   body: JSON.stringify({ region_id: id, chips: gv.chips || gv.status?.default_chips }) });
        const body = await res.json();
        if (res.status === 503) { gv.error = body.detail; gv.status = { ...gv.status, available: false, detail: body.detail }; break; }
        gv.results.set(id, res.ok ? body : { status: 'error', detail: body.detail || res.statusText });
      } catch (err) {
        gv.results.set(id, { status: 'error', detail: err.message });
      }
      flagRegion(id);
    }
    gv.done++;
    if (state.panel === 'changes') renderPanel();
  }
  gv.running = false;
  if (state.panel === 'changes') renderPanel();
}

/** The "Check with Geo-VLM" block of the Find changes list view. */
function vlmSectionHtml(results) {
  const n = Math.min(results.length, GV_MAX), st = gv.status;
  const counts = {};
  results.forEach(f => { const r = gv.results.get(f.properties.id); if (r) { const k = r.status === 'checked' ? r.agreement : r.status; counts[k] = (counts[k] || 0) + 1; } });
  const summary = Object.entries(counts).map(([k, v]) =>
    k === 'blocked' ? `🔒 ${v} labelled site${v > 1 ? 's' : ''} skipped` : k === 'error' ? `! ${v} failed`
      : `${GV_AGREE[k]?.icon ?? '?'} ${v} ${GV_AGREE[k]?.label ?? k}`).join(' · ');
  let action;
  if (gv.running) action = `<button class="btn" id="gvStop">Stop</button> <span class="muted">Checking ${gv.done + 1} of ${gv.total}… (≈20–40 s each)</span>`;
  else if (!st) action = '<span class="muted">Connecting…</span>';
  else if (!st.available) action = `<button class="btn" id="gvRetry">Retry connection</button><p class="muted small">${esc(st.detail)}</p>`;
  else action = n ? `<button class="btn primary" id="gvRun">🛰 Check ${n === results.length ? 'these' : `the ${n} largest`} ${n} region${n > 1 ? 's' : ''} with Geo-VLM</button>` : '';
  const chips = gv.chips || st?.default_chips;
  const chipPicker = st?.available && st.chip_sets ? `<label class="small muted">Images
    <select id="gvChips" ${gv.running ? 'disabled' : ''}>${st.chip_sets.map(c =>
      `<option value="${esc(c)}" ${c === chips ? 'selected' : ''}>${esc(GV_CHIPS[c] || c)}</option>`).join('')}</select></label>` : '';
  return `<div class="section gv"><div class="pane-subtitle">Geo-VLM check ${st?.available ? `<span class="muted">· ${esc(st.model || '')}</span>` : ''}</div>
    ${chipPicker}
    ${action}
    ${gv.error ? `<p class="chip unsupported">${esc(gv.error)}</p>` : ''}
    ${summary ? `<p class="small">${summary}</p>` : ''}
    <p class="muted small">The model sees only before/after images, not the detector's numbers, and says whether the outlined box changed. A second look, not validated: on development regions it did no better than chance (D15).
      ${st?.labelled_sites_locked ? 'The 30 labelled evaluation sites are skipped until the Phase 4 prompts are frozen.' : ''}</p></div>`;
}

function wireVlmSection(results) {
  const ids = results.slice(0, GV_MAX).map(f => f.properties.id);
  const run = $('#gvRun'); if (run) run.onclick = () => checkRegions(ids);
  const stop = $('#gvStop'); if (stop) stop.onclick = () => { gv.stop = true; };
  const pick = $('#gvChips');
  if (pick) pick.onchange = () => {   // results belong to one image set: start over with the new one
    gv.chips = pick.value; const old = [...gv.results.keys()]; gv.results.clear(); old.forEach(flagRegion); renderPanel();
  };
  const retry = $('#gvRetry'); if (retry) retry.onclick = () => { gv.status = null; gv.error = ''; renderPanel(); loadVlmStatus(); };
}

/** Result block for one region's detail card. */
function vlmCardHtml(id) {
  const r = gv.results.get(id), st = gv.status;
  const button = gv.running || r?.status === 'checked' ? '' : st?.available
    ? `<button class="btn" id="gvOne">🛰 ${r ? 'Try again' : 'Check with Geo-VLM'}</button>`
    : `<p class="muted small">Geo-VLM not connected: ${esc(st?.detail || '…')}</p>`;
  if (!r) return `<div class="section"><div class="pane-subtitle">Geo-VLM check</div>${button}</div>`;
  if (r.status === 'blocked') return `<div class="section"><div class="pane-subtitle">Geo-VLM check</div><p class="muted">🔒 ${esc(r.detail)}</p></div>`;
  if (r.status === 'error') return `<div class="section"><div class="pane-subtitle">Geo-VLM check</div><p class="chip unsupported">${esc(r.detail)}</p>${button}</div>`;
  const a = GV_AGREE[r.agreement] || GV_AGREE.unsure;
  const names = ts => ts.length ? ts.map(t => t === 'other' ? 'other' : info(t).short).join(' + ') : '—';
  return `<div class="section"><div class="pane-subtitle">Geo-VLM check</div>
    <p><span class="chip ${a.cls}">🛰 ${a.icon} ${esc(a.label)}</span></p>
    <div class="facts">
      <div><span class="muted">Geo-VLM sees</span><b>${esc(r.verdict === 'change' ? names(r.change_types) : r.verdict.replace('_', ' '))}</b></div>
      <div><span class="muted">Detector says</span><b>${esc(names(r.detector_types))}</b></div>
    </div>
    <p class="explain">“${esc(r.reason)}”</p>
    <p class="muted small">${esc(r.model)} · ${esc(r.prompt_version)}${r.chips ? ` · ${esc(GV_CHIPS[r.chips] || r.chips)}` : ''}${r.parse_ok ? '' : ' · answer could not be parsed'} · VLM-checked, not validated.</p>
    <details><summary>Raw model answer</summary><pre>${esc(r.raw)}</pre></details>
    ${button}</div>`;
}

function wireVlmCard(id) {
  const b = $('#gvOne');
  if (b) b.onclick = () => { gv.results.delete(id); checkRegions([id]).then(() => { if (explore.regionId === id) renderPanel(); }); };
}
