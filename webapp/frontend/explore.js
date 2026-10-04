/* EviChange GIS — change explorer.
 * Change-type colours + icons on the map, the "Find changes" panel (chat search, area
 * breakdown, region list) and the region detail card.
 * Loaded BEFORE app.js: this file only defines functions; app.js calls initExplorer()
 * from its map 'load' handler, after which map/state/$/esc/... from app.js are in scope.
 */
'use strict';

// How each change type is drawn and explained. Which types a region HAS comes from
// /api/change_types (agents/schema.py CHANGE_TYPES + T_IDX), the same rules the verifier uses.
const TYPE_INFO = {
  vegetation_loss:   { color: '#ea580c', icon: '🍂', short: 'Vegetation loss',
    plain: 'Vegetation visible in the before image is gone or much sparser after (NDVI fell). Land clearing, mining and construction look like this.' },
  built_up_increase: { color: '#dc2626', icon: '🏗️', short: 'More bare / built-up ground',
    plain: 'More bare soil, rock or built surface after (NDBI rose). Open-pit mining, spoil heaps, construction and new roads all look like this; the imagery alone cannot say which.' },
  water_increase:    { color: '#2563eb', icon: '💧', short: 'New / more water',
    plain: 'More surface water after (MNDWI rose): new ponds, flooded pits, reservoirs, or a different tide.' },
  vegetation_gain:   { color: '#16a34a', icon: '🌱', short: 'Vegetation gain',
    plain: 'Greener after than before (NDVI rose): regrowth, planting, or a seasonal difference.' },
  water_decrease:    { color: '#9333ea', icon: '🏜️', short: 'Less water',
    plain: 'Less surface water after (MNDWI fell): drained or filled ponds, reclaimed land, or a different tide.' },
  built_up_decrease: { color: '#64748b', icon: '🧱', short: 'Less bare / built-up ground',
    plain: 'Less bare or built surface after (NDBI fell), e.g. bare ground that plants or water now cover.' },
  unclear:           { color: '#9ca3af', icon: '❔', short: 'Type unclear',
    plain: 'Detected as change, but no index moved past the threshold, so what kind of change it is is not clear.' },
};
const INDEX_LABELS = { dNDVI: 'Vegetation (dNDVI)', dNDBI: 'Bare / built-up (dNDBI)', dMNDWI: 'Water (dMNDWI)' };
// Used only if /api/change_types cannot be reached; mirrors agents/schema.py.
const FALLBACK_TYPES = {
  vegetation_loss: { field: 'dNDVI', sign: -1 }, vegetation_gain: { field: 'dNDVI', sign: 1 },
  built_up_increase: { field: 'dNDBI', sign: 1 }, built_up_decrease: { field: 'dNDBI', sign: -1 },
  water_increase: { field: 'dMNDWI', sign: 1 }, water_decrease: { field: 'dMNDWI', sign: -1 },
};
const EXAMPLES = ['vegetation loss bigger than 10 ha', 'new water in the north', 'mining-like changes in this area', 'largest 5 changes'];

const explore = {
  types: FALLBACK_TYPES, tIdx: 0.1,
  meta: new Map(),          // region id -> { fid, bbox, anchor }
  filter: emptyFilter(),
  scope: 'all',             // 'all' | 'view' | 'drawn'
  drawnIds: null,           // Set of region ids inside the drawn area
  regionId: null,           // region shown in the detail card (null = list view)
  chat: [],
  markers: [],
  cardMaps: [],
  hoverFid: null,
};
function emptyFilter() { return { types: null, minHa: null, maxHa: null, locations: null, top: null }; }

// ---------- classification ----------
async function loadChangeTypes() {
  try {
    const j = await (await fetch('/api/change_types')).json();
    explore.types = j.types; explore.tIdx = j.t_idx;
  } catch (err) { /* keep FALLBACK_TYPES */ }
}

function regionTypes(p) {
  return Object.entries(explore.types)
    .filter(([, t]) => t.sign * (p[t.field] ?? 0) > explore.tIdx)
    .sort((a, b) => Math.abs(p[b[1].field]) - Math.abs(p[a[1].field]))
    .map(([k]) => k);
}

/** Adds change_types / primary_type to every region (called before the layer is drawn). */
function annotateRegions(fc) {
  fc.features.forEach(f => {
    const types = regionTypes(f.properties);
    f.properties.change_types = types;
    f.properties.primary_type = types[0] || 'unclear';
  });
}

function changeLayer() { return state.layers.find(l => l.id === CHANGE_ID); }
function allRegions() { return changeLayer()?.data.features ?? []; }
function regionById(id) { return allRegions().find(f => f.properties.id === id); }
function info(type) { return TYPE_INFO[type] ?? TYPE_INFO.unclear; }
function typesOf(f) { return f.properties.change_types?.length ? f.properties.change_types : ['unclear']; }
function fmtHa(ha) { return ha >= 100 ? `${Math.round(ha).toLocaleString()} ha` : `${(+ha).toFixed(1)} ha`; }

function changeTypePaint(hl) {
  const match = ['match', ['get', 'primary_type'], ...Object.entries(TYPE_INFO).flatMap(([k, v]) => [k, v.color]), TYPE_INFO.unclear.color];
  return {
    fill: { 'fill-color': match, 'fill-opacity': 0.5 },
    line: { 'line-color': ['case', hl, '#22d3ee', match], 'line-width': ['case', hl, 3.5, 1.4] },
  };
}

// ---------- start-up ----------
function initExplorer() {
  const layer = changeLayer();
  if (!layer) return;
  layer.data.features.forEach(f => {
    explore.meta.set(f.properties.id, { fid: f.properties.__fid, bbox: turf.bbox(f), anchor: turf.pointOnFeature(f).geometry.coordinates });
  });
  map.on('moveend', () => { refreshMarkers(); if (state.panel === 'changes' && explore.scope === 'view' && !explore.regionId) renderPanel(); });
  applyFilter();
}

// ---------- filtering ----------
function inScope(f) {
  if (explore.scope === 'drawn') return !!explore.drawnIds?.has(f.properties.id);
  if (explore.scope === 'view') {
    const b = map.getBounds(), [w, s, e, n] = explore.meta.get(f.properties.id).bbox;
    return w <= b.getEast() && e >= b.getWest() && s <= b.getNorth() && n >= b.getSouth();
  }
  return true;
}

function matchesFilter(f, flt = explore.filter) {
  const p = f.properties;
  if (flt.types && !typesOf(f).some(t => flt.types.has(t))) return false;
  if (flt.minHa != null && p.area_ha < flt.minHa) return false;
  if (flt.maxHa != null && p.area_ha > flt.maxHa) return false;
  if (flt.locations && !flt.locations.has(p.location)) return false;
  return true;
}

function filterActive() { const f = explore.filter; return !!(f.types || f.minHa != null || f.maxHa != null || f.locations || f.top); }

/** Regions in the current scope that match the filter, largest first. */
function currentResults() {
  const res = allRegions().filter(f => inScope(f) && matchesFilter(f)).sort((a, b) => b.properties.area_ha - a.properties.area_ha);
  return explore.filter.top ? res.slice(0, explore.filter.top) : res;
}

/** Show only matching regions on the map (all regions when nothing is filtered). */
function applyFilter() {
  const layer = changeLayer(); if (!layer) return;
  const limited = filterActive() || explore.scope !== 'all';
  const ids = limited ? currentResults().map(f => f.properties.id) : null;
  layer.mapLayers.forEach(ml => map.setFilter(ml, ids ? ['in', ['get', 'id'], ['literal', ids]] : null));
  refreshMarkers();
  renderLegend();
}

function setFilter(flt) { explore.filter = flt; applyFilter(); }
function clearFilter() { explore.filter = emptyFilter(); applyFilter(); }

// ---------- icons on the map ----------
function refreshMarkers() {
  explore.markers.forEach(m => m.remove());
  explore.markers = [];
  const layer = changeLayer();
  if (!layer || !layer.visible) return;
  const z = map.getZoom(), b = map.getBounds();
  const minHa = z < 11.5 ? 20 : z < 12.5 ? 5 : z < 13.5 ? 1 : 0;   // fewer, bigger regions when zoomed out
  currentResults()
    .filter(f => f.properties.area_ha >= minHa && b.contains(explore.meta.get(f.properties.id).anchor))
    .slice(0, 150)
    .forEach(f => {
      const p = f.properties, t = info(p.primary_type);
      const el = document.createElement('button');
      el.className = 'chg-marker';
      el.style.setProperty('--c', t.color);
      el.textContent = t.icon;
      el.title = `${p.id} · ${typesOf(f).map(k => info(k).short).join(' + ')} · ${fmtHa(p.area_ha)}`;
      el.onclick = ev => { ev.stopPropagation(); openRegion(p.id); };
      explore.markers.push(new maplibregl.Marker({ element: el }).setLngLat(explore.meta.get(p.id).anchor).addTo(map));
    });
}

// ---------- legend (left pane) ----------
function renderLegend() {
  const el = $('#legend'); if (!el) return;
  const all = allRegions();
  const counts = {};
  all.forEach(f => { const k = f.properties.primary_type; counts[k] = (counts[k] || 0) + 1; });
  const shown = filterActive() || explore.scope !== 'all' ? currentResults().length : all.length;
  const selTypes = explore.filter.types;
  el.innerHTML = `<div class="pane-subtitle">Change regions — what changed</div>` +
    Object.entries(TYPE_INFO).filter(([k]) => counts[k]).map(([k, t]) => `
      <button class="legend-row ${selTypes && !selTypes.has(k) ? 'off' : ''}" data-k="${k}" title="Show only: ${esc(t.short)}">
        <span class="swatch" style="background:${t.color}">${t.icon}</span><span>${esc(t.short)}</span><span class="muted">${counts[k]}</span>
      </button>`).join('') +
    `<div class="muted legend-foot">Showing ${shown} of ${all.length}${shown < all.length ? ' · <button class="linkish" id="legClear">show all</button>' : ''}</div>
     <div class="muted legend-foot">Colour = strongest index change. Click a type to filter, a region or icon for details.</div>`;
  el.querySelectorAll('.legend-row').forEach(b => b.onclick = () => {
    const k = b.dataset.k;
    const only = selTypes && selTypes.size === 1 && selTypes.has(k);
    setFilter({ ...explore.filter, types: only ? null : new Set([k]) });
    if (state.panel === 'changes') renderPanel();
  });
  const c = $('#legClear');
  if (c) c.onclick = () => { explore.scope = 'all'; clearFilter(); if (state.panel === 'changes') renderPanel(); };
}

// ---------- "Find changes" chat: plain-language search ----------
const TOPIC_RULES = [
  { re: /\b(deforest\w*|logging|cut down|clear(?:ed|ing)? (?:the )?(?:forest|trees|vegetation|land))\b/, types: ['vegetation_loss'] },
  { re: /\b(reforest\w*|regrow\w*|re-?vegetat\w*|greening|replant\w*)\b/, types: ['vegetation_gain'] },
  { re: /\b(min(?:e|es|ing)|quarr(?:y|ies)|excavat\w*|spoil|open[- ]pit|coal)\b/, types: ['built_up_increase', 'vegetation_loss'], mining: true },
  { re: /\b(construct\w*|urbani[sz]\w*|development)\b/, types: ['built_up_increase'] },
  { re: /\b(flood\w*)\b/, types: ['water_increase'] },
  { re: /\b(drought|drain\w*|dried|drying)\b/, types: ['water_decrease'] },
  { re: /\b(construct\w*|build\w*|built|urban\w*|roads?|settlements?|hous\w*|concrete|develop\w*|bare|soil|rock\w*|ground)\b/, topic: 'built' },
  { re: /\b(veg\w*|forest\w*|trees?|green\w*|plants?|crops?|grass\w*|mangroves?|farm\w*)\b/, topic: 'veg' },
  { re: /\b(water|lakes?|ponds?|rivers?|reservoirs?|wet\w*|sea|coast\w*|pits? filled)\b/, topic: 'water' },
];
const TOPIC_TYPES = { veg: ['vegetation_loss', 'vegetation_gain'], built: ['built_up_increase', 'built_up_decrease'], water: ['water_increase', 'water_decrease'] };
const LOSS_RE = /\b(loss|lost|lose|losing|less|fewer|removed?|cleared|clearing|cut|gone|decreas\w*|declin\w*|shrink\w*|disappear\w*|reduc\w*|fell|drop\w*)\b/;
const GAIN_RE = /\b(gain\w*|new|more|increas\w*|grow\w*|expan\w*|appear\w*|added|ris(?:e|en|ing)|rose|spread\w*|creat\w*)\b/;
const NUM = String.raw`(\d+(?:[.,]\d+)?)\s*(ha\b|hectares?|km2|km²|sq\.? ?km|square kilomet(?:er|re)s?)?`;
const MIN_RE = new RegExp(String.raw`(?:bigger|larger|greater|more|over|above|at least|>=?|≥)\s*(?:than\s*)?` + NUM);
const MAX_RE = new RegExp(String.raw`(?:smaller|less|under|below|at most|<=?|≤)\s*(?:than\s*)?` + NUM);
const BETWEEN_RE = new RegExp(String.raw`between\s*` + NUM + String.raw`\s*(?:and|to|-)\s*` + NUM);
const TOP_RE = /\b(?:top|largest|biggest)\s+(\d+)\b|\b(\d+)\s+(?:largest|biggest)\b/;
const LOC_RE = /\b(north|south)[\s-]?(east|west)(?:ern)?\b|\b(north|south|east|west)(?:ern)?\b|\b(cent(?:re|er|ral)|middle)\b/g;

function toHa(num, unit) { const n = parseFloat(num.replace(',', '.')); return unit && /km|kilomet/.test(unit) ? n * 100 : n; }

/** Turns a typed request into a filter. Keyword-based, not an AI model: it only knows
 *  change types, sizes, locations, "largest N" and the search area. */
function parseQuery(text) {
  let q = ` ${text.toLowerCase()} `;
  const flt = emptyFilter(), notes = [];
  let understood = false, scope = null;
  const cut = m => { q = q.replace(m[0], ' '); understood = true; };

  if (/^\s*(clear|reset|show (me )?(all|everything)|all( changes)?|everything|any change)\s*$/.test(q)) return { reset: true };

  let m;
  if ((m = q.match(BETWEEN_RE))) {
    const a = toHa(m[1], m[2] || m[4]), b = toHa(m[3], m[4] || m[2]);
    [flt.minHa, flt.maxHa] = [Math.min(a, b), Math.max(a, b)]; cut(m);
  }
  if ((m = q.match(MIN_RE))) { flt.minHa = toHa(m[1], m[2]); cut(m); }
  if ((m = q.match(MAX_RE))) { flt.maxHa = toHa(m[1], m[2]); cut(m); }
  if ((m = q.match(TOP_RE))) { flt.top = +(m[1] || m[2]); cut(m); }
  else if ((m = q.match(/\b(largest|biggest)\b/))) { flt.top = 10; cut(m); }
  if (flt.minHa == null && (m = q.match(/\b(large|big|major)\b/))) { flt.minHa = 20; cut(m); }
  if (flt.maxHa == null && (m = q.match(/\b(small|tiny|minor)\b/))) { flt.maxHa = 5; cut(m); }

  if ((m = q.match(/\b(this|selected|drawn|my) area\b|\bhere\b|\binside\b/))) { scope = 'drawn'; cut(m); }
  else if ((m = q.match(/\b(in view|on screen|visible|this view|current view|on the map)\b/))) { scope = 'view'; cut(m); }
  else if ((m = q.match(/\b(whole|entire|everywhere|all over|study area)\b/))) { scope = 'all'; cut(m); }

  const locs = new Set();
  for (const lm of q.matchAll(LOC_RE)) {
    if (lm[1]) locs.add(`${lm[1]}-${lm[2]}`);
    else if (lm[3]) schemaLocations().filter(l => l.split('-').includes(lm[3])).forEach(l => locs.add(l));
    else if (lm[4]) locs.add('centre');
  }
  if (locs.size) { flt.locations = locs; understood = true; }
  q = q.replace(LOC_RE, ' ');

  const types = new Set();
  const loss = LOSS_RE.test(q), gain = GAIN_RE.test(q);
  for (const rule of TOPIC_RULES) {
    if (!rule.re.test(q)) continue;
    if (rule.types) rule.types.forEach(t => types.add(t));
    else {
      const [up, down] = rule.topic === 'veg' ? [TOPIC_TYPES.veg[1], TOPIC_TYPES.veg[0]] : TOPIC_TYPES[rule.topic];
      if (gain || !loss) types.add(up);
      if (loss || !gain) types.add(down);
    }
    if (rule.mining) notes.push('Satellite indices cannot confirm mining. Showing vegetation loss and more bare ground, which is what open-pit mining looks like.');
  }
  if (/\b(unclear|unknown|other)\b/.test(q)) types.add('unclear');
  if (types.size) { flt.types = types; understood = true; }

  return { filter: flt, scope, notes, understood };
}

function schemaLocations() { return ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west', 'centre']; }

function describeFilter(flt, scope) {
  const parts = [];
  parts.push(flt.types ? [...flt.types].map(t => `${info(t).icon} ${info(t).short.toLowerCase()}`).join(' or ') : 'any kind of change');
  if (flt.minHa != null && flt.maxHa != null) parts.push(`between ${fmtHa(flt.minHa)} and ${fmtHa(flt.maxHa)}`);
  else if (flt.minHa != null) parts.push(`at least ${fmtHa(flt.minHa)}`);
  else if (flt.maxHa != null) parts.push(`at most ${fmtHa(flt.maxHa)}`);
  if (flt.locations) parts.push(`in the ${[...flt.locations].join(' / ')}`);
  parts.push({ all: 'in the whole study area', view: 'in the current map view', drawn: 'inside the drawn area' }[scope]);
  if (flt.top) parts.push(`(largest ${flt.top})`);
  return parts.join(', ');
}

function askChat(text) {
  text = text.trim(); if (!text) return;
  explore.chat.push({ who: 'you', html: esc(text) });
  const r = parseQuery(text);
  if (r.reset) {
    explore.scope = 'all'; clearFilter();
    explore.chat.push({ who: 'bot', html: `Showing all ${allRegions().length} change regions again.` });
  } else if (!r.understood) {
    explore.chat.push({ who: 'bot', html: `I can search by <b>type</b> (vegetation, bare/built-up ground, water, mining-like), <b>gain or loss</b>, <b>size</b> ("bigger than 10 ha"), <b>location</b> ("in the north-east"), <b>largest N</b>, and <b>where</b> ("in this area" for a drawn area, "in view"). Try one of the examples below.` });
  } else {
    if (r.scope === 'drawn' && !explore.drawnIds) explore.chat.push({ who: 'bot', html: 'No area drawn yet: searching the whole study area. Use ✎ Draw area first to search inside an area.' });
    else if (r.scope) explore.scope = r.scope;
    explore.filter = r.filter; applyFilter();
    const res = currentResults(), total = res.reduce((s, f) => s + f.properties.area_ha, 0);
    explore.chat.push({ who: 'bot', html:
      `Looking for ${esc(describeFilter(r.filter, explore.scope))}.<br>` +
      (res.length ? `<b>Found ${res.length} region${res.length > 1 ? 's' : ''}, ${fmtHa(total)} in total.</b> They are the only ones shown on the map now.`
                  : '<b>No regions match.</b> Try a smaller size, another location or the whole study area.') +
      r.notes.map(n => `<div class="muted">${esc(n)}</div>`).join('') });
    if (res.length) fitToRegions(res);
  }
  explore.chat = explore.chat.slice(-8);
  explore.regionId = null;
  renderPanel();
}

function fitToRegions(feats) {
  const boxes = feats.map(f => explore.meta.get(f.properties.id).bbox);
  map.fitBounds([[Math.min(...boxes.map(b => b[0])), Math.min(...boxes.map(b => b[1]))],
                 [Math.max(...boxes.map(b => b[2])), Math.max(...boxes.map(b => b[3]))]], { padding: 60, maxZoom: 15 });
}

// ---------- drawn area ----------
function setDrawnArea(area) {
  state.drawnArea = area;
  explore.drawnIds = new Set(allRegions().filter(f => turf.booleanIntersects(f, area)).map(f => f.properties.id));
  explore.scope = 'drawn';
  explore.regionId = null;
  applyFilter();
}

function showDrawnOutline() {
  if (explore.scope !== 'drawn' || !state.drawnArea) return;
  ensureSketchLayers();
  map.getSource('sketch').setData(turf.featureCollection([state.drawnArea]));
}

// ---------- panel: list view + region card ----------
function openRegion(id, fly = false) {
  explore.regionId = id;
  highlightRegion(id);
  const f = regionById(id);
  if (fly && f) map.fitBounds(explore.meta.get(id).bbox, { padding: 80, maxZoom: 15 });
  if (state.panel === 'changes') renderPanel(); else openPanel('changes');
}

function highlightRegion(id) {
  if (explore.hoverFid != null && map.getSource(CHANGE_ID)) map.setFeatureState({ source: CHANGE_ID, id: explore.hoverFid }, { hl: false });
  explore.hoverFid = id == null ? null : explore.meta.get(id)?.fid ?? null;
  if (explore.hoverFid != null) map.setFeatureState({ source: CHANGE_ID, id: explore.hoverFid }, { hl: true });
}

function destroyCardMaps() { explore.cardMaps.forEach(m => m.remove()); explore.cardMaps = []; }

function renderChangesPanel(body) {
  destroyCardMaps();
  showDrawnOutline();
  if (explore.regionId && regionById(explore.regionId)) return renderRegionCard(body, regionById(explore.regionId));
  explore.regionId = null;
  highlightRegion(null);

  const results = currentResults();
  const total = results.reduce((s, f) => s + f.properties.area_ha, 0);
  const byType = {};
  results.forEach(f => { const k = f.properties.primary_type; (byType[k] ||= { n: 0, ha: 0 }); byType[k].n++; byType[k].ha += f.properties.area_ha; });
  const maxHa = Math.max(1, ...Object.values(byType).map(v => v.ha));
  const chat = explore.chat.length ? explore.chat.map(c => `<div class="msg ${c.who}">${c.html}</div>`).join('')
    : '<div class="msg bot">Ask for the changes you want to see, e.g. <i>"vegetation loss bigger than 10 ha"</i>. Or draw an area with ✎ Draw area to see everything that changed inside it.</div>';

  body.innerHTML = `
    <div class="chat" id="chatLog">${chat}</div>
    <form class="chat-form" id="chatForm"><input id="chatInput" placeholder="What changes are you looking for?" autocomplete="off">
      <button class="btn primary" type="submit">Find</button></form>
    <div class="chips examples">${EXAMPLES.map(x => `<button class="chip ex" type="button">${esc(x)}</button>`).join('')}</div>
    <div class="section seg scope" id="scopeSeg">
      <button data-s="all" class="${explore.scope === 'all' ? 'on' : ''}">Whole study area</button>
      <button data-s="view" class="${explore.scope === 'view' ? 'on' : ''}">Map view</button>
      <button data-s="drawn" class="${explore.scope === 'drawn' ? 'on' : ''}" ${explore.drawnIds ? '' : 'disabled title="Draw an area first (✎ Draw area)"'}>Drawn area</button>
    </div>
    <div class="section">
      <div class="pane-subtitle">${results.length} change region${results.length === 1 ? '' : 's'} · ${fmtHa(total)}
        ${filterActive() ? `<span class="muted"> · ${esc(describeFilter(explore.filter, explore.scope))}</span> <button class="linkish" id="clearF">clear</button>` : ''}</div>
      ${Object.entries(byType).sort((a, b) => b[1].ha - a[1].ha).map(([k, v]) => `
        <button class="type-row" data-k="${k}" title="Show only this type">
          <span class="swatch" style="background:${info(k).color}">${info(k).icon}</span>
          <span class="type-name">${esc(info(k).short)}</span>
          <span class="type-bar"><span style="width:${(100 * v.ha / maxHa).toFixed(1)}%;background:${info(k).color}"></span></span>
          <span class="type-num">${fmtHa(v.ha)}<br><span class="muted">${v.n} region${v.n > 1 ? 's' : ''}</span></span>
        </button>`).join('') || '<p class="muted">Nothing here. Try another search or the whole study area.</p>'}
    </div>
    ${results.length ? `<div class="section"><div class="pane-subtitle">Regions, largest first</div>
      <div class="region-list">${results.slice(0, 100).map(f => {
        const p = f.properties;
        return `<button class="region-row" data-id="${esc(p.id)}">
          <span class="swatch" style="background:${info(p.primary_type).color}">${info(p.primary_type).icon}</span>
          <span><b>${esc(typesOf(f).map(t => info(t).short).join(' + '))}</b><br>
          <span class="muted">${esc(p.id)} · ${fmtHa(p.area_ha)} · ${esc(p.location)}</span></span></button>`;
      }).join('')}</div>
      ${results.length > 100 ? `<p class="muted">…and ${results.length - 100} smaller regions. Narrow the search to see them.</p>` : ''}</div>
      <button class="btn" id="toReport">✦ AI report for these ${results.length} region${results.length > 1 ? 's' : ''}</button>` : ''}`;

  const log = $('#chatLog'); log.scrollTop = log.scrollHeight;
  $('#chatForm').onsubmit = e => { e.preventDefault(); askChat($('#chatInput').value); };
  body.querySelectorAll('.ex').forEach(b => b.onclick = () => askChat(b.textContent));
  body.querySelectorAll('#scopeSeg button').forEach(b => b.onclick = () => { explore.scope = b.dataset.s; applyFilter(); renderPanel(); });
  const cf = $('#clearF'); if (cf) cf.onclick = () => { clearFilter(); renderPanel(); };
  body.querySelectorAll('.type-row').forEach(b => b.onclick = () => { setFilter({ ...explore.filter, types: new Set([b.dataset.k]) }); renderPanel(); });
  body.querySelectorAll('.region-row').forEach(b => {
    b.onmouseenter = () => highlightRegion(b.dataset.id);
    b.onmouseleave = () => highlightRegion(null);
    b.onclick = () => openRegion(b.dataset.id, true);
  });
  const tr = $('#toReport');
  if (tr) tr.onclick = () => { state.selected = new Set(results.map(f => f.properties.id)); syncSelection(); openPanel('report'); };
}

function fmtWindow(s) {
  if (!s || !String(s).includes('/')) return s ?? '?';
  const fmt = d => new Date(`${d}T00:00:00`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
  const [a, b] = String(s).split('/');
  return `${fmt(a)} – ${fmt(b)}`;
}

function indexBar(field, v) {
  const R = 0.6, t = explore.tIdx;
  const pct = x => 50 + Math.max(-1, Math.min(1, x / R)) * 50;
  const strong = Math.abs(v) > t;
  const type = Object.entries(explore.types).find(([, d]) => d.field === field && Math.sign(v) === d.sign)?.[0];
  const color = strong && type ? info(type).color : '#cbd5e1';
  return `<div class="ibar">
    <div class="ibar-label"><span>${INDEX_LABELS[field]}</span><b>${v > 0 ? '+' : ''}${(+v).toFixed(2)}</b></div>
    <div class="ibar-track">
      <span class="ibar-band" style="left:${pct(-t)}%;width:${pct(t) - pct(-t)}%"></span>
      <span class="ibar-zero"></span>
      <span class="ibar-fill" style="left:${Math.min(pct(0), pct(v))}%;width:${Math.abs(pct(v) - pct(0))}%;background:${color}"></span>
    </div></div>`;
}

function renderRegionCard(body, f) {
  const p = f.properties, types = typesOf(f);
  $('#panelTitle').textContent = `Change region ${p.id}`;
  highlightRegion(p.id);
  body.innerHTML = `
    <button class="linkish" id="cardBack">← All changes</button>
    <div class="card-head">
      <div class="card-icons">${types.map(t => `<span class="swatch big" style="background:${info(t).color}" title="${esc(info(t).short)}">${info(t).icon}</span>`).join('')}</div>
      <div><div class="card-title">${esc(types.map(t => info(t).short).join(' + '))}</div>
        <div class="muted">${fmtHa(p.area_ha)} · ${esc(p.location)} of the study area</div></div>
    </div>
    <div class="beforeafter">
      <figure><div class="minimap" id="mmBefore"></div><figcaption>Before · 2018</figcaption></figure>
      <figure><div class="minimap" id="mmAfter"></div><figcaption>After · 2022</figcaption></figure>
    </div>
    <p class="muted small">Images: Sentinel-2 cloudless yearly mosaics (EOX). The detector compared ${esc(fmtWindow(p.date_before))} with ${esc(fmtWindow(p.date_after))}.</p>
    <div class="section"><div class="pane-subtitle">What changed</div>
      ${types.map(t => `<p class="explain"><span class="swatch" style="background:${info(t).color}">${info(t).icon}</span> ${esc(info(t).plain)}</p>`).join('')}</div>
    <div class="section"><div class="pane-subtitle">Index changes (after − before)</div>
      ${['dNDVI', 'dNDBI', 'dMNDWI'].map(k => indexBar(k, p[k] ?? 0)).join('')}
      <p class="muted small">Grey band = ±${explore.tIdx}: changes inside it are too small to count as evidence.</p></div>
    <div class="section facts">
      <div><span class="muted">Area</span><b>${fmtHa(p.area_ha)}</b></div>
      <div><span class="muted">Location</span><b>${esc(p.location)}</b></div>
      <div><span class="muted">Index agreement</span><b>${p.mean_conf != null ? (+p.mean_conf).toFixed(2) : '–'}</b></div>
      <div><span class="muted">Source</span><b>${esc(p.source ?? '–')}</b></div>
    </div>
    <div class="section card-actions">
      <button class="btn" id="cardZoom">🔍 Zoom to</button>
      <button class="btn" id="cardSwipe">⇆ Swipe here</button>
      <button class="btn primary" id="cardAI">✦ AI claims</button>
    </div>
    <div id="cardReport"></div>`;

  const clean = { type: 'Feature', properties: {}, geometry: f.geometry };
  explore.cardMaps.push(miniMap('mmBefore', 's2_2018', clean), miniMap('mmAfter', 's2_2022', clean));
  $('#cardBack').onclick = () => { explore.regionId = null; renderPanel(); };
  $('#cardZoom').onclick = () => map.fitBounds(explore.meta.get(p.id).bbox, { padding: 80, maxZoom: 15 });
  $('#cardSwipe').onclick = () => { map.fitBounds(explore.meta.get(p.id).bbox, { padding: 80, maxZoom: 15, duration: 0 }); openPanel('swipe'); };
  $('#cardAI').onclick = async () => {
    const out = $('#cardReport');
    out.innerHTML = '<p class="muted">Generating…</p>';
    state.selected = new Set([p.id]); syncSelection();
    try { out.innerHTML = reportHtml(await fetchReport('gated')); }
    catch (err) { out.innerHTML = `<p class="chip unsupported">Error: ${esc(err.message)}</p>`; }
  };
}

function miniMap(container, tileKey, feature) {
  const [w, s, e, n] = turf.bbox(feature);
  const pad = Math.max(e - w, n - s) * 0.35 + 0.002;
  return new maplibregl.Map({
    container, interactive: false, attributionControl: false,
    bounds: [[w - pad, s - pad], [e + pad, n + pad]],
    style: { version: 8, sources: { img: rasterSource(tileKey), r: { type: 'geojson', data: feature } }, layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#dfe3e8' } },
      { id: 'img', type: 'raster', source: 'img' },
      { id: 'r', type: 'line', source: 'r', paint: { 'line-color': '#fde047', 'line-width': 2 } }] },
  });
}
