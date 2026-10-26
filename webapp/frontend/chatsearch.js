/* EviChange GIS — prompted change search in "Find changes" (D7 steps 1 and 2).
 * Step 1: the typed request goes to POST /api/search_spec, where the Geo-VLM turns the sentence
 *   into a validated SearchSpec (filters + optional date windows). Only the sentence is read: the
 *   model never draws or invents a region. If no model is reachable, or its answer is unusable,
 *   the keyword parser (explore.js parseQuery) answers instead, exactly as before.
 * Step 2: a spec that fits the loaded run just filters its regions. A spec that names other dates
 *   shows the proposed run in the chat and waits for the user's OK before POST /api/runs
 *   (Earth Engine time; the area comes from the drawn / searched / loaded area, never from the model).
 * Loaded after geovlm.js, before app.js; called from explore.js askChat and renderChangesPanel.
 */
'use strict';

const CS = { proposals: new Map(), seq: 0, timeoutMs: 30000 };

/** { filter, scope, notes, understood, windows, source, sourceNote } for a typed request. */
async function interpretRequest(text) {
  const fallback = why => ({ ...parseQuery(text), source: 'keyword', sourceNote: why });
  if (!gv.status?.available) return fallback('');           // no model connected: the keyword parser is the normal path
  const thinking = { who: 'bot', html: '<span class="muted">Reading your request with the Geo-VLM…</span>' };
  explore.chat.push(thinking); renderPanel();
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), CS.timeoutMs);
  try {
    const res = await fetch('/api/search_spec', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                  body: JSON.stringify({ prompt: text }), signal: ctl.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) return fallback(`Geo-VLM not available (${body.detail || res.status}): used the keyword parser.`);
    if (body.status !== 'ok') return fallback(`The Geo-VLM's answer could not be used (${body.detail}): used the keyword parser.`);
    return specToQuery(body);
  } catch (err) {
    return fallback(err.name === 'AbortError' ? 'The Geo-VLM took too long: used the keyword parser.' : `Geo-VLM request failed: used the keyword parser.`);
  } finally {
    clearTimeout(timer);
    explore.chat = explore.chat.filter(m => m !== thinking);
  }
}

/** A validated SearchSpec (from the backend) -> the same shape parseQuery returns. */
function specToQuery({ spec, notes = [], model }) {
  const flt = emptyFilter();
  if (spec.change_types) flt.types = new Set(spec.change_types);
  if (spec.locations) flt.locations = new Set(spec.locations);
  flt.minHa = spec.min_ha; flt.maxHa = spec.max_ha; flt.top = spec.top;
  flt.classFrom = spec.class_from; flt.classTo = spec.class_to;
  const windows = spec.before_window && spec.after_window ? { before: spec.before_window, after: spec.after_window } : null;
  const mining = flt.types && flt.types.has('vegetation_loss') && flt.types.has('built_up_increase');
  return {
    filter: flt, scope: spec.scope, windows, source: 'vlm', understood: true,
    notes: [...notes.map(n => `Ignored part of the model's answer: ${n}`),
            ...(mining ? ['Satellite indices cannot confirm mining. Showing vegetation loss and more bare ground, which is what open-pit mining looks like.'] : [])],
    sourceNote: `Read by the Geo-VLM (${model}), then checked against the app's rules. Check the query below.`,
  };
}

// ---------- step 2: does the request need a new run? ----------
const sameWindow = (a, b) => Array.isArray(a) && Array.isArray(b) && a[0] === b[0] && a[1] === b[1];

/** The windows, area and condition of what the map shows now. */
async function loadedAnalysis() {
  if (state.currentRunId) {
    try {
      const s = await (await fetch(`/api/runs/${state.currentRunId}`)).json();
      if (s?.before_window) return { before: s.before_window, after: s.after_window, aoi: s.aoi, condition: s.condition };
    } catch { /* fall through to the region properties */ }
  }
  const p = allRegions()[0]?.properties;
  const split = v => (v && String(v).includes('/')) ? String(v).split('/') : null;
  return { before: split(p?.date_before), after: split(p?.date_after),
           aoi: state.layers.find(l => l.id === 'aoi')?.data.features[0]?.geometry ?? null, condition: 'gated' };
}

/** True when the requested windows are not the ones the loaded regions were computed from. */
async function windowsNeedRun(w) {
  const cur = await loadedAnalysis();
  return !(sameWindow(w.before, cur.before) && sameWindow(w.after, cur.after));
}

const fmtRange = w => `${w[0]} → ${w[1]}`;

async function proposeRun(r) {
  const cur = await loadedAnalysis();
  const aoi = state.runAoi || cur.aoi, aoiFrom = state.runAoi ? 'the area chosen in ▶ Run pipeline' : 'the area the map shows now';
  const note = r.sourceNote ? `<div class="muted small">${esc(r.sourceNote)}</div>` : '';
  const shows = cur.before ? `The map shows ${esc(fmtRange(cur.before))} vs ${esc(fmtRange(cur.after))}. ` : '';
  const fits = r.filter ? `<br>After the run I will look for ${esc(describeFilter(r.filter, r.scope === 'drawn' ? 'all' : (r.scope || 'all')))}.` : '';
  if (!aoi) {
    explore.chat.push({ who: 'bot', html: `${note}That needs a new run for other dates, but there is no area yet. Choose one in <b>▶ Run pipeline</b> (search a place, use the map view or draw), then ask again.` });
    return;
  }
  const km2 = aoiKm2(aoi);
  if (km2 < AOI_KM2.min || km2 > AOI_KM2.max) {
    explore.chat.push({ who: 'bot', html: `${note}That needs a new run for other dates, but ${aoiFrom} is ${km2.toFixed(1)} km² and a run must be ${AOI_KM2.min}–${AOI_KM2.max} km². Pick another area in <b>▶ Run pipeline</b>.` });
    return;
  }
  const id = `p${++CS.seq}`;
  CS.proposals.set(id, { r, aoi, payload: { aoi, before_window: r.windows.before, after_window: r.windows.after, condition: 'gated' } });
  explore.chat.push({ who: 'bot', html: `${note}<b>This needs a new run.</b> ${shows}You asked for other dates.
    <div class="proposal">Before: ${esc(fmtRange(r.windows.before))}<br>After: ${esc(fmtRange(r.windows.after))}<br>
      Area: ${km2.toFixed(1)} km² (${esc(aoiFrom)})<br>Report condition: gated</div>${fits}
    <div class="muted small">It runs on Earth Engine and takes a few minutes; an identical earlier run is reused from the cache.</div>
    <div class="export-row" data-proposal="${id}"><button class="btn primary" data-act="cs-run">Run it</button><button class="btn" data-act="cs-cancel">Cancel</button></div>` });
}

/** Buttons inside chat messages (proposed runs). The chat is re-rendered as HTML, so the clicks are wired here. */
function wireChatActions(body) {
  body.querySelectorAll('[data-proposal]').forEach(row => {
    const id = row.dataset.proposal;
    row.querySelector('[data-act=cs-run]').onclick = () => confirmProposal(id);
    row.querySelector('[data-act=cs-cancel]').onclick = () => cancelProposal(id);
  });
}

function replaceProposal(id, html) {                       // the buttons give way to what happened
  const m = explore.chat.find(c => c.html.includes(`data-proposal="${id}"`));
  if (m) m.html = m.html.replace(/<div class="export-row" data-proposal="[^"]*">.*?<\/div>/s, html);
  else explore.chat.push({ who: 'bot', html });
  if (state.panel === 'changes') renderPanel();
}

function cancelProposal(id) {
  CS.proposals.delete(id);
  replaceProposal(id, '<div class="muted small">Run cancelled.</div>');
}

async function confirmProposal(id) {
  const prop = CS.proposals.get(id); if (!prop) return;
  CS.proposals.delete(id);
  replaceProposal(id, `<div class="muted small" data-run-status="${id}">Run started…</div>`);
  const say = html => { explore.chat.push({ who: 'bot', html }); explore.chat = explore.chat.slice(-8); if (state.panel === 'changes') renderPanel(); };
  await startRun(prop.payload, {
    onProgress: st => replaceRunStatus(id, `Run ${esc(st.status)} (${Math.round((st.progress || 0) * 100)}%)…`),
    onError: msg => say(`<span class="chip unsupported">The run failed: ${esc(msg)}</span>`),
    onDone: runId => {
      const { filter, scope } = prop.r;
      explore.filter = filter; explore.scope = scope === 'drawn' || scope === 'selection' ? 'all' : (scope || 'all');   // a drawn area or selection belonged to the old regions
      applyFilter();
      const res = currentResults(), total = res.reduce((s, f) => s + f.properties.area_ha, 0);
      say(`<b>Run ${esc(runId)} finished.</b> ` + (res.length
        ? `Found ${res.length} region${res.length > 1 ? 's' : ''}, ${fmtHa(total)} in total, for ${esc(describeFilter(filter, explore.scope))}.`
        : `No regions match ${esc(describeFilter(filter, explore.scope))} in the new dates.`) +
        `<pre class="sql">${esc(filterSql(filter, explore.scope))}</pre>`);
      if (res.length) fitToRegions(res);
    },
  });
}

function replaceRunStatus(id, text) {                   // only this proposal's status line, so a second run doesn't overwrite the first
  const tag = `data-run-status="${id}"`;
  const m = explore.chat.find(c => c.html.includes(tag));
  if (m) m.html = m.html.replace(new RegExp(`<div class="muted small" ${tag}>.*?</div>`, 's'), `<div class="muted small" ${tag}>${text}</div>`);
  if (state.panel === 'changes' && !explore.regionId) renderPanel();
}
