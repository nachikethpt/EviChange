/* EviChange GIS — charts linked to the map (Phase 7b d, decisions.md D8).
 * Bar chart (count or sum by category) and histogram (numeric field). One series each,
 * drawn as plain SVG. Clicking a bar selects its features (Shift = add); the selection
 * shows as the darker part of each bar. Loaded BEFORE app.js; see gistools.js.
 */
'use strict';

const CHART_ACCENT = '#0f766e', CHART_INK = '#1f2933', CHART_MUTED = '#6b7280', CHART_GRID = '#e5e7eb';
const charts = { layer: null, type: 'bar', field: null, measure: 'count', bins: 10, table: false };

function chartFmt(n) { return Math.abs(n) >= 1000 ? Math.round(n).toLocaleString() : String(+(+n).toPrecision(3)); }

/** Groups: [{ key, label, value, selValue, fids, color }] */
function chartGroups(layer) {
  const feats = layer.data.features, sel = selectedFids(layer), f = charts.field;
  if (charts.type === 'hist') {
    const vals = feats.filter(x => typeof x.properties[f] === 'number' && Number.isFinite(x.properties[f]));
    if (!vals.length) return [];
    const lo = vals.reduce((m, x) => Math.min(m, x.properties[f]), Infinity);
    const hi = vals.reduce((m, x) => Math.max(m, x.properties[f]), -Infinity);
    const n = lo === hi ? 1 : charts.bins, w = (hi - lo) / n || 1;
    const groups = Array.from({ length: n }, (_, i) => ({ key: i, label: `${chartFmt(lo + i * w)} – ${chartFmt(lo + (i + 1) * w)}`,
                                                          value: 0, selValue: 0, fids: new Set(), color: CHART_ACCENT }));
    vals.forEach(x => {
      const g = groups[Math.min(n - 1, Math.floor((x.properties[f] - lo) / w))];
      g.value++; g.fids.add(x.properties.__fid); if (sel.has(x.properties.__fid)) g.selValue++;
    });
    return groups;
  }
  const byKey = new Map();
  feats.forEach(x => {
    const raw = x.properties[f], key = raw == null || typeof raw === 'object' ? '(no value)' : String(raw);
    const add = charts.measure === 'count' ? 1 : (+x.properties[charts.measure] || 0);
    const g = byKey.get(key) || byKey.set(key, { key, label: key, value: 0, selValue: 0, fids: new Set(),
      color: f === 'primary_type' && TYPE_INFO[key] ? TYPE_INFO[key].color : CHART_ACCENT }).get(key);
    g.value += add; g.fids.add(x.properties.__fid); if (sel.has(x.properties.__fid)) g.selValue += add;
  });
  const groups = [...byKey.values()].sort((a, b) => b.value - a.value);
  if (groups.length > 12) {        // fold the long tail into "Other" instead of drawing dozens of bars
    const rest = groups.splice(11);
    groups.push(rest.reduce((o, g) => { o.value += g.value; o.selValue += g.selValue; g.fids.forEach(x => o.fids.add(x)); return o; },
      { key: '__other', label: `Other (${rest.length})`, value: 0, selValue: 0, fids: new Set(), color: '#9ca3af' }));
  }
  if (f === 'primary_type') groups.forEach(g => { if (TYPE_INFO[g.key]) g.label = TYPE_INFO[g.key].short; });
  return groups;
}

/** Horizontal bars (categories) or vertical bins (histogram), as one SVG string. */
function chartSvg(groups, horizontal) {
  const max = Math.max(...groups.map(g => g.value), 0) || 1, anySel = groups.some(g => g.selValue);
  const shade = (g, x, y, w, h) => anySel
    ? `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="2" fill="${g.color}" opacity=".3"/>`
    : `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="2" fill="${g.color}"/>`;
  if (horizontal) {
    const W = 330, labelW = 118, valW = 46, row = 24, bar = 16, plotW = W - labelW - valW, H = groups.length * row + 4;
    const rows = groups.map((g, i) => {
      const y = i * row + 4, w = Math.max(2, g.value / max * plotW), sw = g.selValue / max * plotW;
      return `<g class="bar" data-i="${i}">
        <rect class="hit" x="0" y="${y - 3}" width="${W}" height="${row}" fill="transparent"/>
        <text x="${labelW - 6}" y="${y + bar / 2 + 4}" text-anchor="end" fill="${CHART_INK}" font-size="11">${esc(g.label.length > 19 ? g.label.slice(0, 18) + '…' : g.label)}</text>
        ${shade(g, labelW, y, w, bar)}
        ${g.selValue ? `<rect x="${labelW}" y="${y}" width="${Math.max(2, sw)}" height="${bar}" rx="2" fill="${g.color}"/>` : ''}
        <text x="${labelW + w + 4}" y="${y + bar / 2 + 4}" fill="${CHART_MUTED}" font-size="11">${chartFmt(g.value)}</text>
      </g>`;
    }).join('');
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">${rows}</svg>`;
  }
  const W = 330, H = 170, left = 34, bottom = 22, plotH = H - bottom - 8, gap = 2, bw = (W - left) / groups.length;
  const ticks = [0, max / 2, max].map(t => {
    const y = 8 + plotH - t / max * plotH;
    return `<line x1="${left}" x2="${W}" y1="${y}" y2="${y}" stroke="${CHART_GRID}"/><text x="${left - 4}" y="${y + 4}" text-anchor="end" fill="${CHART_MUTED}" font-size="10">${chartFmt(t)}</text>`;
  }).join('');
  const bars = groups.map((g, i) => {
    const x = left + i * bw + gap / 2, w = bw - gap, h = g.value / max * plotH, sh = g.selValue / max * plotH;
    return `<g class="bar" data-i="${i}">
      <rect class="hit" x="${x}" y="8" width="${w}" height="${plotH}" fill="transparent"/>
      ${g.value ? shade(g, x, 8 + plotH - h, w, h) : ''}
      ${g.selValue ? `<rect x="${x}" y="${8 + plotH - sh}" width="${w}" height="${sh}" rx="2" fill="${g.color}"/>` : ''}
    </g>`;
  }).join('');
  const first = groups[0]?.label.split(' – ')[0] ?? '', last = groups[groups.length - 1]?.label.split(' – ')[1] ?? '';
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">${ticks}${bars}
    <line x1="${left}" x2="${W}" y1="${8 + plotH}" y2="${8 + plotH}" stroke="${CHART_MUTED}"/>
    <text x="${left}" y="${H - 6}" fill="${CHART_MUTED}" font-size="10">${esc(first)}</text>
    <text x="${W}" y="${H - 6}" text-anchor="end" fill="${CHART_MUTED}" font-size="10">${esc(last)}</text></svg>`;
}

function renderChartsPanel(body) {
  const layers = vectorLayers();
  if (!layers.length) { body.innerHTML = '<p class="muted">No vector layers. Add data first.</p>'; return; }
  const layer = layerById(charts.layer) || layers[0]; charts.layer = layer.id;
  const fields = layerFields(layer);
  const numeric = [...fields].filter(([, t]) => t === 'number').map(([k]) => k);
  if (charts.type === 'hist' && !numeric.length) charts.type = 'bar';
  if (charts.type === 'hist' && !numeric.includes(charts.field)) charts.field = pickField(fields, 'number', ['area_ha', 'mean_conf']);
  if (charts.type === 'bar' && !fields.has(charts.field)) charts.field = pickField(fields, 'string', ['primary_type', 'location']) ?? [...fields.keys()][0];
  if (charts.measure !== 'count' && !numeric.includes(charts.measure)) charts.measure = 'count';

  const groups = charts.field ? chartGroups(layer) : [];
  const opt = (v, label, sel) => `<option value="${esc(v)}" ${sel ? 'selected' : ''}>${esc(label)}</option>`;
  const measureLabel = charts.measure === 'count' ? 'Number of features' : `Sum of ${charts.measure}`;
  const title = charts.type === 'hist' ? `Distribution of ${charts.field}` : `${measureLabel} by ${charts.field}`;
  const selN = selectedFids(layer).size;
  body.innerHTML = `
    <div class="section"><label>Layer<br><select id="chLayer">${layers.map(l => opt(l.id, l.name, l === layer)).join('')}</select></label></div>
    <div class="section seg"><button data-ct="bar" class="${charts.type === 'bar' ? 'on' : ''}">Bar chart</button>
      <button data-ct="hist" class="${charts.type === 'hist' ? 'on' : ''}" ${numeric.length ? '' : 'disabled'}>Histogram</button></div>
    <div class="section sym-grid">
      <label>${charts.type === 'hist' ? 'Field' : 'Category'}<br><select id="chField">${(charts.type === 'hist' ? numeric : [...fields.keys()]).map(k => opt(k, k, k === charts.field)).join('')}</select></label>
      ${charts.type === 'hist'
        ? `<label>Bins<br><select id="chBins">${[5, 8, 10, 15, 20].map(n => opt(n, n, n === charts.bins)).join('')}</select></label>`
        : `<label>Value<br><select id="chMeasure">${opt('count', 'Count', charts.measure === 'count')}${numeric.map(k => opt(k, `Sum of ${k}`, k === charts.measure)).join('')}</select></label>`}
    </div>
    <div class="chart-title">${esc(title)}</div>
    <div class="muted small">${esc(layer.name)} · ${layer.data.features.length} features${selN ? ` · ${selN} selected (darker)` : ''}</div>
    <div class="chart" id="chart">${groups.length ? chartSvg(groups, charts.type === 'bar') : '<p class="muted">No values to chart.</p>'}</div>
    <div class="chart-tip" id="chartTip" hidden></div>
    <div class="card-actions section">
      <button class="btn" id="chTable">${charts.table ? 'Hide table' : 'Show as table'}</button>
      ${selN ? '<button class="btn" id="chClear">Clear selection</button>' : ''}
    </div>
    ${charts.table ? `<table class="cmp"><thead><tr><th>${esc(charts.type === 'hist' ? charts.field : charts.field)}</th><th>${esc(charts.type === 'hist' ? 'Count' : measureLabel)}</th><th>Selected</th></tr></thead>
      <tbody>${groups.map(g => `<tr><td>${esc(g.label)}</td><td>${chartFmt(g.value)}</td><td>${g.selValue ? chartFmt(g.selValue) : ''}</td></tr>`).join('')}</tbody></table>` : ''}
    <p class="muted small">Click a bar to select its features on the map (Shift+click adds). Charts follow the selection from ⚙ Tools, the table and the AI report.</p>`;

  $('#chLayer').onchange = e => { charts.layer = e.target.value; charts.field = null; renderPanel(); };
  body.querySelectorAll('[data-ct]').forEach(b => b.onclick = () => { charts.type = b.dataset.ct; charts.field = null; renderPanel(); });
  $('#chField').onchange = e => { charts.field = e.target.value; renderPanel(); };
  const m = $('#chMeasure'); if (m) m.onchange = e => { charts.measure = e.target.value; renderPanel(); };
  const bn = $('#chBins'); if (bn) bn.onchange = e => { charts.bins = +e.target.value; renderPanel(); };
  $('#chTable').onclick = () => { charts.table = !charts.table; renderPanel(); };
  const c = $('#chClear'); if (c) c.onclick = () => { setSelection(layer, new Set()); renderPanel(); };

  const tip = $('#chartTip'), box = $('#chart');
  box.querySelectorAll('.bar').forEach(el => {
    const g = groups[+el.dataset.i];
    el.onmousemove = e => {
      const r = box.getBoundingClientRect();
      tip.hidden = false;
      tip.innerHTML = `<b>${esc(g.label)}</b><br>${charts.type === 'hist' ? 'Count' : esc(measureLabel)}: ${chartFmt(g.value)}${g.selValue ? `<br>Selected: ${chartFmt(g.selValue)}` : ''}`;
      tip.style.left = `${Math.min(e.clientX - r.left + 12, r.width - 150)}px`;
      tip.style.top = `${e.clientY - r.top + box.offsetTop + 12}px`;
    };
    el.onmouseleave = () => { tip.hidden = true; };
    el.onclick = e => {
      setSelection(layer, e.shiftKey ? new Set([...selectedFids(layer), ...g.fids]) : new Set(g.fids));
      if (g.fids.size) {
        const fc = turf.featureCollection(layer.data.features.filter(f => g.fids.has(f.properties.__fid)));
        map.fitBounds(turf.bbox(fc), { padding: 60, maxZoom: 15 });
      }
      renderPanel();
    };
  });
}
