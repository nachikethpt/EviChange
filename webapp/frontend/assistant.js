/* EviChange GIS — map assistant (D9, Phase 7c): typed requests become validated tool actions.
 *
 * "make the AOI purple, 95% transparent", "buffer the change regions by 500 m and dissolve it",
 * "clip the change regions to the study area", "show the NDVI change", "export the selected change
 * regions as CSV", "undo".
 *
 * parseActions() is a keyword parser (no model): it returns the steps of a request, each checked
 * against the layers that exist, or null when the text isn't an action (the chat then searches
 * change regions as before). When the parser doesn't understand a request that looks like an action
 * (ACTION_HINT), the Geo-VLM is asked (POST /api/assistant/plan, agents/assistant_plan.py): it makes
 * the same step objects, which go through the same validateStep() and run the same way. Actions only call the app's own tools: the
 * change regions are never edited, geoprocessing outputs are new layers (D8), and nothing here
 * starts an Earth Engine run (D7: runs need a drawn area and a confirmation).
 *
 * Loaded before app.js like explore.js: it only defines functions; the runner uses map/state/... at
 * call time. The parser is pure, so tests/test_assistant.py runs it under node.
 */
'use strict';

const ASSIST_COLORS = {
  red: '#dc2626', orange: '#ea580c', yellow: '#facc15', green: '#16a34a', blue: '#2563eb', purple: '#9333ea',
  violet: '#7c3aed', pink: '#db2777', cyan: '#06b6d4', teal: '#0d9488', brown: '#92400e', black: '#111827',
  white: '#ffffff', grey: '#6b7280', gray: '#6b7280',
};
const ASSIST_INDEX_KINDS = { change: 'change', difference: 'change', delta: 'change', before: 'before', after: 'after' };
const LAYER_ALIASES = [
  [/^(?:the\s+)?(?:detected\s+)?(?:change(?:s|\s+regions?)?|regions?|detections?)$/, 'change'],
  [/^(?:the\s+)?(?:aoi|study\s+area|area\s+of\s+interest)$/, 'aoi'],
];
const LAST_REF = /^(?:it|that|this|them|the\s+(?:result|output|new\s+layer|last\s+layer))$/;
const STEP_SPLIT = /\s*(?:;|,?\s+and\s+then\s+|,?\s+then\s+|,\s*and\s+(?=(?:buffer|clip|intersect|dissolve|make|colou?r|paint|style|export|download|zoom|show|add)\b)|\s+and\s+(?=(?:buffer|clip|intersect|dissolve|make|colou?r|paint|style|export|download|zoom|show)\b))\s*/i;
const UNITS = /^(m|meters?|metres?|km|kilomet(?:er|re)s?)$/;

/** Layer id for a phrase: aliases first, then the layer whose name contains all the phrase's words. */
function resolveLayer(phrase, layers) {
  const p = phrase.trim().toLowerCase().replace(/\s+layer$/, '').replace(/^the\s+/, '');
  if (LAST_REF.test(p) || LAST_REF.test(`the ${p}`)) return { ref: 'last' };
  for (const [re, id] of LAYER_ALIASES) if (re.test(p) && layers.some(l => l.id === id)) return { id };
  const words = p.split(/\s+/).filter(Boolean);
  const hits = layers.filter(l => words.every(w => l.name.toLowerCase().includes(w)));
  if (hits.length === 1) return { id: hits[0].id };
  if (hits.length > 1) return { error: `“${p}” matches ${hits.length} layers: ${hits.map(l => `“${l.name}”`).join(', ')}. Use more of the name.` };
  return { error: `No layer called “${p}”. Layers: ${layers.map(l => `“${l.name}”`).join(', ')}.` };
}

function parseColor(word) {
  const w = word.toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(w)) return w;
  return ASSIST_COLORS[w] || null;
}

/** One step from one clause, or null when the clause is not an action. */
function parseStep(clause, layers) {
  const c = clause.trim().replace(/[.!]+$/, '');
  const lc = c.toLowerCase();
  let m;
  if (/^undo$/.test(lc)) return { action: 'undo' };
  if ((m = lc.match(/^(?:make|colou?r|paint|style|set|turn)\s+(.+?)\s+(?:to\s+|in\s+)?(#[0-9a-f]{6}|[a-z]+)(?:\s*,?\s*(?:and\s+)?(\d{1,3})\s*%\s*(transparent|transparency|opaque|opacity))?$/))
      && parseColor(m[2])) {
    const step = { action: 'style_layer', layer: m[1], color: parseColor(m[2]) };
    if (m[3]) step.opacity = /transparen/.test(m[4]) ? 1 - +m[3] / 100 : +m[3] / 100;
    return step;
  }
  if ((m = lc.match(/^(?:make|set)\s+(.+?)\s+(\d{1,3})\s*%\s*(transparent|opaque)$/)))
    return { action: 'style_layer', layer: m[1], opacity: m[3] === 'transparent' ? 1 - +m[2] / 100 : +m[2] / 100 };
  if ((m = lc.match(/^buffer\s+(.+?)\s+(?:by\s+)?(-?\d+(?:\.\d+)?)\s*([a-z]+)$/)) && UNITS.test(m[3]))
    return { action: 'buffer', layer: m[1], distance: +m[2], units: m[3].startsWith('k') ? 'kilometers' : 'meters' };
  if ((m = lc.match(/^(clip|intersect)\s+(.+?)\s+(?:to|by|with)\s+(.+)$/)))
    return { action: m[1], layer: m[2], other: m[3] };
  if ((m = lc.match(/^dissolve\s+(.+?)(?:\s+by\s+([a-z_][a-z0-9_]*))?$/)))
    return { action: 'dissolve', layer: m[1], field: m[2] || '' };
  if ((m = lc.match(/^(?:show|add)\s+(?:the\s+)?(ndvi|ndbi|mndwi)(?:\s+(change|difference|delta|before|after))?(?:\s+(?:layer|map))?$/)))
    return { action: 'add_index_layer', index: m[1].toUpperCase(), kind: ASSIST_INDEX_KINDS[m[2] || 'change'] };
  if ((m = lc.match(/^(?:export|download|save)\s+(?:the\s+)?(selected\s+|selection\s+(?:of|from)\s+)?(.+?)\s+(?:as|to)\s+(geojson|csv|kml)$/)))
    return { action: 'export', layer: m[2], format: m[3], selectedOnly: !!m[1] };
  if ((m = lc.match(/^(?:zoom|go|fly)\s+to\s+(.+)$/)))
    return { action: 'zoom', layer: m[1] };
  if (/^(?:open\s+)?(?:a\s+)?(?:charts?|graphs?|plots?)(?:\s+panel)?$/.test(lc)) return { action: 'chart' };
  return null;
}

/** Checks a step against the layers that exist and fills in layer ids. Returns {step} or {error}. */
function validateStep(step, layers) {
  const out = { ...step };
  for (const key of ['layer', 'other']) {
    if (!(key in step)) continue;
    const r = resolveLayer(step[key], layers);
    if (r.error) return { error: r.error };
    out[key] = r.ref ? { ref: 'last' } : r.id;
  }
  if (step.action === 'style_layer' && step.opacity != null && !(step.opacity >= 0 && step.opacity <= 1))
    return { error: 'Transparency must be between 0 % and 100 %.' };
  if (step.action === 'buffer' && (!Number.isFinite(step.distance) || step.distance === 0))
    return { error: 'Buffer by a non-zero distance (negative shrinks polygons).' };
  return { step: out };
}

/** The steps of a request, or null if it isn't an action. {steps} or {error} when it is one. */
function parseActions(text, layers) {
  const clauses = text.split(STEP_SPLIT).filter(s => s.trim());
  const steps = clauses.map(c => parseStep(c, layers));
  if (steps.every(s => s === null)) return null;
  const bad = clauses.find((c, i) => steps[i] === null);
  if (bad) return { error: `I understood part of that, but not “${bad.trim()}”. Nothing was run.` };
  const checked = steps.map(s => validateStep(s, layers));
  const err = checked.find(r => r.error);
  if (err) return { error: `${err.error} Nothing was run.` };
  if (Object.values(checked[0].step).some(v => v?.ref))
    return { error: '“it” needs an earlier step that makes a layer. Nothing was run.' };
  return { steps: checked.map(r => r.step) };
}

/** What a step does, in words (shown before it runs, like ArcGIS Pro shows the tool chain). */
function describeStep(s, name) {
  const L = id => (id?.ref ? 'the previous result' : `“${name(id)}”`);
  return {
    style_layer: () => `Style ${L(s.layer)}: ${s.color ? `colour ${s.color}` : ''}${s.color && s.opacity != null ? ', ' : ''}${s.opacity != null ? `${Math.round((1 - s.opacity) * 100)} % transparent` : ''}`,
    buffer: () => `Buffer ${L(s.layer)} by ${s.distance} ${s.units} → new layer`,
    clip: () => `Clip ${L(s.layer)} to ${L(s.other)} → new layer`,
    intersect: () => `Intersect ${L(s.layer)} with ${L(s.other)} → new layer`,
    dissolve: () => `Dissolve ${L(s.layer)}${s.field ? ` by ${s.field}` : ''} → new layer`,
    add_index_layer: () => `Add the ${s.index} ${s.kind} layer from Earth Engine`,
    export: () => `Export ${s.selectedOnly ? 'the selected features of ' : ''}${L(s.layer)} as ${s.format.toUpperCase()}`,
    zoom: () => `Zoom to ${L(s.layer)}`,
    chart: () => 'Open the linked charts',
    undo: () => 'Undo the last action',
  }[s.action]();
}

/** Words that make a request look like a tool action rather than a change search (worth asking the model). */
const ACTION_HINT = /\b(buffer|clip|intersect|dissolve|style|colou?r|paint|transparen\w*|opacity|export|download|save|zoom|chart|graph|plot|ndvi|ndbi|mndwi|layer|undo|outline|symbol\w*)\b/i;

/** Steps from the model, checked like the parser's. {steps} or {error}. */
function checkModelSteps(raw, layers) {
  const checked = raw.map(s => validateStep(s.color ? { ...s, color: parseColor(s.color) || s.color } : s, layers));
  const err = checked.find(r => r.error);
  if (err) return { error: `${err.error} Nothing was run.` };
  if (Object.values(checked[0].step).some(v => v?.ref)) return { error: '“it” needs an earlier step that makes a layer. Nothing was run.' };
  return { steps: checked.map(r => r.step) };
}

if (typeof module !== 'undefined') module.exports = { parseActions, parseStep, resolveLayer, describeStep, checkModelSteps, ACTION_HINT };

// ---------- running (browser only) ----------
const assistUndo = [];          // [{label, undo: () => void}]

function assistLayerName(id) { return (typeof layerById === 'function' && layerById(id)?.name) || id; }

/** Runs one step; returns {msg, newLayerId?, undo?}. */
async function runStep(s, lastId) {
  const id = v => (v?.ref ? lastId : v);
  const newLayer = async fn => {
    const before = new Set(state.layers.map(l => l.id));
    const msg = await fn();
    const made = state.layers.find(l => !before.has(l.id));
    return { msg: typeof msg === 'string' ? msg : msg?.msg || 'Done.', newLayerId: made?.id,
             undo: made && (() => { const l = layerById(made.id); if (l) removeLayer(l); }) };
  };
  const layer = s.layer !== undefined ? layerById(id(s.layer)) : null;
  if (s.layer !== undefined && !layer) throw new Error('The layer is gone.');
  if (s.action === 'style_layer') {
    const prev = { sym: layer.sym ? { ...layer.sym } : null, opacity: layer.opacity };
    if (s.color) {
      if (layer.kind !== 'vector') throw new Error(`“${layer.name}” is an image layer: only its transparency can change.`);
      layer.sym = { ...defaultSym(layer), method: 'single', color: s.color };
      applySymbology(layer);
    }
    if (s.opacity != null) setOpacity(layer, s.opacity);
    renderLayerList();
    return { msg: `Styled “${layer.name}”.`, undo: () => {
      layer.sym = prev.sym; if (layer.kind === 'vector') applySymbology(layer); setOpacity(layer, prev.opacity); renderLayerList(); } };
  }
  if (['buffer', 'clip', 'intersect', 'dissolve'].includes(s.action)) {
    if (layer.kind !== 'vector') throw new Error(`“${layer.name}” is an image layer; ${s.action} needs a vector layer.`);
    const fm = { ...toolDefaults(s.action === 'clip' || s.action === 'intersect' ? s.action : s.action, vectorLayers()), layer: layer.id };
    if (s.action === 'buffer') Object.assign(fm, { distance: s.distance, units: s.units });
    if (s.action === 'dissolve') fm.field = s.field;
    if (s.other !== undefined) fm.other = id(s.other);
    return newLayer(() => RUNNERS[s.action](fm, () => {}));
  }
  if (s.action === 'add_index_layer') return newLayer(async () => { await addIndexLayer(s.index, s.kind); if (gis.indexMsg) throw new Error(gis.indexMsg); return `Added the ${s.index} ${s.kind} layer.`; });
  if (s.action === 'export') {
    const n = exportLayer(layer, s.format, s.selectedOnly);
    return { msg: `Exported ${n} feature${n === 1 ? '' : 's'} as ${s.format.toUpperCase()} (a download: it can't be undone).` };
  }
  if (s.action === 'zoom') { zoomTo(layer); return { msg: `Zoomed to “${layer.name}”.` }; }
  if (s.action === 'chart') { setTimeout(() => openPanel('charts'), 0); return { msg: 'Opened the charts.' }; }
  throw new Error(`Unknown action ${s.action}`);
}

/** Called by the Find changes chat (explore.js askChat) before it tries a search. Returns false when the
 *  text is not an action, so the chat searches as before. */
async function askAssistant(text) {
  const vl = state.layers.map(l => ({ id: l.id, name: l.name }));
  const say = html => { explore.chat.push({ who: 'bot', html }); explore.chat = explore.chat.slice(-8); renderPanel(); };
  let plan = parseActions(text, vl), byModel = false;
  if ((!plan || plan.error) && ACTION_HINT.test(text)) {
    const m = await assistModelPlan(text, vl);
    if (m === 'search') return false;
    if (m) { plan = m; byModel = true; }
  }
  if (!plan) return false;
  if (plan.error) { say(esc(plan.error)); return true; }
  if (plan.steps.length === 1 && plan.steps[0].action === 'undo') {
    const last = assistUndo.pop();
    if (!last) say('Nothing to undo.');
    else { last.undo(); say(`Undid: ${esc(last.label)}.`); }
    return true;
  }
  const chain = plan.steps.map(s => describeStep(s, assistLayerName));
  const log = [];
  let lastId = null;
  for (const [i, s] of plan.steps.entries()) {
    try {
      const r = await runStep(s, lastId);
      if (r.newLayerId) lastId = r.newLayerId;
      if (r.undo) assistUndo.push({ label: chain[i], undo: r.undo });
      log.push(`✓ ${esc(r.msg)}`);
    } catch (err) {
      log.push(`<span class="chip unsupported">Error</span> ${esc(err.message)}${i < plan.steps.length - 1 ? ' The remaining steps were not run.' : ''}`);
      break;
    }
  }
  say(`<b>Ran${byModel ? ' (read by the Geo-VLM)' : ''}:</b><pre class="sql">${chain.map((c, i) => `${i + 1}. ${esc(c)}`).join('\n')}</pre>${log.join('<br>')}` +
      (assistUndo.length ? '<br><button class="btn" data-assist-undo>↶ Undo last</button> <span class="muted small">or type “undo”</span>' : ''));
  return true;
}

/** The model's plan: {steps} | {error} | 'search' | null (no model, or it found nothing: keep the parser's answer). */
async function assistModelPlan(text, layers) {
  try {
    const r = await fetch('/api/assistant/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                   body: JSON.stringify({ text, layers: layers.map(l => l.name) }) });
    if (!r.ok) return null;
    const d = await r.json();
    if (d.status === 'search') return 'search';
    if (d.status !== 'ok') return null;
    return checkModelSteps(d.steps, layers);
  } catch (err) { return null; }
}

if (typeof document !== 'undefined') {
  document.addEventListener('click', e => {
    if (!e.target.closest('[data-assist-undo]')) return;
    const last = assistUndo.pop();
    if (!last) return;
    last.undo();
    explore.chat.push({ who: 'bot', html: `Undid: ${esc(last.label)}.` });
    renderPanel();
  });
}
