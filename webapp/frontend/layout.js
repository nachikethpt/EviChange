/* EviChange GIS — export layers + print layout (Phase 7b d, decisions.md D8).
 * Export: GeoJSON, CSV (attributes + centroid), KML; all features or the selection.
 * Print layout: title, map, legend, north arrow, scale bar and attribution drawn onto one
 * canvas, saved as PNG or printed (the browser's "Save as PDF").
 * Loaded BEFORE app.js; see gistools.js.
 */
'use strict';

const layout = { title: '', subtitle: '', orientation: 'landscape', legend: true, north: true, scale: true,
                 exportLayer: null, exportSelected: false, preview: null, busy: false, msg: '' };

// ---------- export ----------
function slug(s) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'layer'; }

function saveFile(name, data, type) {
  const url = data.startsWith?.('data:') ? data : URL.createObjectURL(new Blob([data], { type }));
  const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  if (!url.startsWith('data:')) setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportFeatures(layer, selectedOnly) {
  return toolInput(layer, selectedOnly).map(f => turf.feature(f.geometry, cleanProps(f.properties)));
}

function toCsv(feats) {
  const cols = [...new Set(feats.flatMap(f => Object.keys(f.properties)))];
  const cell = v => {
    const s = v == null ? '' : Array.isArray(v) ? v.join(';') : typeof v === 'object' ? JSON.stringify(v) : String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = feats.map(f => {
    const c = turf.centroid(f).geometry.coordinates;
    return [...cols.map(k => cell(f.properties[k])), c[0].toFixed(6), c[1].toFixed(6)].join(',');
  });
  return [[...cols.map(cell), 'centroid_lon', 'centroid_lat'].join(','), ...rows].join('\r\n');
}

function toKml(name, feats) {
  const x = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[c]));
  const coords = cs => cs.map(c => `${c[0]},${c[1]}`).join(' ');
  const poly = rings => `<Polygon><outerBoundaryIs><LinearRing><coordinates>${coords(rings[0])}</coordinates></LinearRing></outerBoundaryIs>${
    rings.slice(1).map(r => `<innerBoundaryIs><LinearRing><coordinates>${coords(r)}</coordinates></LinearRing></innerBoundaryIs>`).join('')}</Polygon>`;
  const geom = g => ({
    Point: () => `<Point><coordinates>${coords([g.coordinates])}</coordinates></Point>`,
    LineString: () => `<LineString><coordinates>${coords(g.coordinates)}</coordinates></LineString>`,
    Polygon: () => poly(g.coordinates),
    MultiPoint: () => `<MultiGeometry>${g.coordinates.map(c => `<Point><coordinates>${coords([c])}</coordinates></Point>`).join('')}</MultiGeometry>`,
    MultiLineString: () => `<MultiGeometry>${g.coordinates.map(l => `<LineString><coordinates>${coords(l)}</coordinates></LineString>`).join('')}</MultiGeometry>`,
    MultiPolygon: () => `<MultiGeometry>${g.coordinates.map(poly).join('')}</MultiGeometry>`,
  }[g.type] || (() => ''))();
  const marks = feats.map((f, i) => {
    const p = f.properties;
    const data = Object.entries(p).map(([k, v]) => `<Data name="${x(k)}"><value>${x(Array.isArray(v) ? v.join(';') : typeof v === 'object' ? JSON.stringify(v) : v)}</value></Data>`).join('');
    return `<Placemark><name>${x(p.id ?? p.name ?? i + 1)}</name><ExtendedData>${data}</ExtendedData>${geom(f.geometry)}</Placemark>`;
  }).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>${x(name)}</name>\n${marks}\n</Document></kml>`;
}

function exportLayer(layer, format, selectedOnly) {
  const feats = exportFeatures(layer, selectedOnly);
  const base = slug(layer.name) + (selectedOnly && selectedFids(layer).size ? '-selection' : '');
  if (format === 'geojson') saveFile(`${base}.geojson`, JSON.stringify(turf.featureCollection(feats)), 'application/geo+json');
  if (format === 'csv') saveFile(`${base}.csv`, '﻿' + toCsv(feats), 'text/csv');          // BOM so Excel reads UTF-8
  if (format === 'kml') saveFile(`${base}.kml`, toKml(layer.name, feats), 'application/vnd.google-earth.kml+xml');
  return feats.length;
}

// ---------- print layout ----------
const PAGE = { landscape: [1754, 1240], portrait: [1240, 1754] };   // A4 at 150 dpi

function plainText(html) { const d = document.createElement('div'); d.innerHTML = html; return d.textContent.trim(); }

function attributionText() {
  const parts = new Set();
  if (state.basemap !== 'none') parts.add(plainText(TILES[state.basemap].attribution));
  state.layers.filter(l => l.visible && l.kind === 'raster').forEach(l => {
    const a = map.getSource(l.id)?.attribution; if (a) parts.add(plainText(a));
  });
  return [...parts].join(' · ');
}

/** Legend entries for the visible layers: [{ title, rows: [{color, label, outline?}], ramp? }] */
function legendEntries() {
  return state.layers.filter(l => l.visible && (l.kind === 'vector' || l.legend)).map(l => {
    if (l.kind === 'raster') return { title: l.name, ramp: l.legend };
    const sym = symbologyFor(l);
    if (sym) return { title: `${l.name}${l.sym.method === 'single' ? '' : ` (${l.sym.field})`}`, rows: sym.legend };
    if (l.style === 'change_type') {
      const present = new Set(l.data.features.map(f => f.properties.primary_type));
      return { title: l.name, rows: Object.entries(TYPE_INFO).filter(([k]) => present.has(k)).map(([, t]) => ({ color: t.color, label: t.short })) };
    }
    if (l.style === 'confidence') return { title: l.name, ramp: { min: 0.3, max: 0.9, palette: ['#fde68a', '#f97316', '#b91c1c'], label: 'mean_conf' } };
    if (l.style === 'outline') return { title: l.name, rows: [{ color: '#5eead4', label: 'Outline', outline: true }] };
    return { title: l.name, rows: [{ color: l.color, label: 'All features' }] };
  });
}

function niceLength(maxMeters) {
  const p = Math.pow(10, Math.floor(Math.log10(maxMeters)));
  return [5, 2, 1].map(m => m * p).find(v => v <= maxMeters) || p;
}

async function captureMap() {
  // wait for tiles, but not forever: a tile server that keeps failing means the map never goes 'idle'
  await new Promise(r => {
    if (map.loaded()) return r();
    const done = () => { clearTimeout(timer); map.off('idle', done); r(); };
    const timer = setTimeout(done, 8000);
    map.on('idle', done);
  });
  // the WebGL buffer is only readable during a render, so grab it in the next 'render' event
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { map.off('render', grab); reject(new Error('the map did not redraw')); }, 5000);
    function grab() {
      clearTimeout(timer); map.off('render', grab);
      try { resolve(map.getCanvas().toDataURL('image/png')); } catch (e) { reject(e); }
    }
    map.on('render', grab);
    map.triggerRepaint();
  });
}

function loadImage(src) { return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = src; }); }

/** Draws the whole page and returns it as a PNG data URL. */
async function buildLayout() {
  const img = await loadImage(await captureMap());
  const [W, H] = PAGE[layout.orientation], M = 56, landscape = layout.orientation === 'landscape';
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const g = cv.getContext('2d');
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, W, H);
  const font = (px, weight = 400) => `${weight} ${px}px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;

  // title block
  g.fillStyle = '#1f2933'; g.font = font(40, 700); g.fillText(layout.title || 'EviChange map', M, M + 34);
  let top = M + 52;
  if (layout.subtitle) { g.fillStyle = '#6b7280'; g.font = font(22); g.fillText(layout.subtitle, M, top + 14); top += 34; }
  top += 10;

  // frames: legend on the right (landscape) or below (portrait)
  const legendW = layout.legend ? (landscape ? 380 : W - 2 * M) : 0, legendH = layout.legend && !landscape ? 330 : 0;
  const footH = 60;
  // map frame: the largest box with the map view's own shape, so the whole view is printed uncropped
  const room = { w: W - 2 * M - (landscape && layout.legend ? legendW + 24 : 0), h: H - top - M - footH - (legendH ? legendH + 20 : 0) };
  const s = Math.min(room.w / img.width, room.h / img.height);
  const frame = { x: M, y: top, w: img.width * s, h: img.height * s };
  g.drawImage(img, frame.x, frame.y, frame.w, frame.h);
  g.strokeStyle = '#1f2933'; g.lineWidth = 2; g.strokeRect(frame.x, frame.y, frame.w, frame.h);

  // scale bar: metres per canvas pixel at the map centre, then per page pixel
  if (layout.scale) {
    const lat = map.getCenter().lat * Math.PI / 180;
    const mPerCssPx = 40075016.686 * Math.cos(lat) / (512 * Math.pow(2, map.getZoom()));
    const mPerPagePx = mPerCssPx * (map.getContainer().clientWidth / img.width) / s;
    const len = niceLength(frame.w * 0.25 * mPerPagePx), px = len / mPerPagePx;
    const x = frame.x + 24, y = frame.y + frame.h - 30;
    g.fillStyle = 'rgba(255,255,255,.85)'; g.fillRect(x - 10, y - 30, px + 90, 46);
    g.fillStyle = '#1f2933'; g.fillRect(x, y, px / 2, 8); g.strokeStyle = '#1f2933'; g.lineWidth = 2; g.strokeRect(x, y, px, 8);
    g.font = font(18); g.fillText(len >= 1000 ? `${len / 1000} km` : `${len} m`, x + px + 10, y + 9);
    g.font = font(14); g.fillStyle = '#6b7280'; g.fillText('0', x - 4, y - 8);
  }

  // north arrow, rotated with the map
  if (layout.north) {
    const cx = frame.x + frame.w - 50, cy = frame.y + 60;
    g.fillStyle = 'rgba(255,255,255,.85)'; g.beginPath(); g.arc(cx, cy, 38, 0, 2 * Math.PI); g.fill();
    g.save(); g.translate(cx, cy); g.rotate(-map.getBearing() * Math.PI / 180);
    g.fillStyle = '#1f2933'; g.beginPath(); g.moveTo(0, -26); g.lineTo(13, 14); g.lineTo(0, 6); g.closePath(); g.fill();
    g.fillStyle = '#9ca3af'; g.beginPath(); g.moveTo(0, -26); g.lineTo(-13, 14); g.lineTo(0, 6); g.closePath(); g.fill();
    g.fillStyle = '#1f2933'; g.font = font(18, 700); g.textAlign = 'center'; g.fillText('N', 0, 32); g.restore();
    g.textAlign = 'left';
  }

  // legend
  if (layout.legend) {
    let lx = landscape ? frame.x + frame.w + 24 : M, ly = landscape ? frame.y : frame.y + frame.h + 20;
    const colW = landscape ? legendW : (W - 2 * M) / 2, bottom = landscape ? frame.y + frame.h : ly + legendH;
    const startY = ly;
    g.fillStyle = '#1f2933'; g.font = font(24, 700); g.fillText('Legend', lx, ly + 22); ly += 40;
    for (const e of legendEntries()) {
      const need = 30 + (e.ramp ? 46 : e.rows.length * 26);
      if (ly + need > bottom) {                                  // next column (portrait) or stop (landscape)
        if (landscape || lx > M) { g.fillStyle = '#6b7280'; g.font = font(15); g.fillText('… more layers not shown', lx, Math.min(ly + 16, bottom)); break; }
        lx += colW; ly = startY + 40;
      }
      g.fillStyle = '#1f2933'; g.font = font(17, 600); g.fillText(fitText(g, e.title, colW - 10), lx, ly + 16); ly += 28;
      g.font = font(16);
      if (e.ramp) {
        const grad = g.createLinearGradient(lx, 0, lx + colW - 60, 0);
        e.ramp.palette.forEach((c, i) => grad.addColorStop(i / (e.ramp.palette.length - 1), c));
        g.fillStyle = grad; g.fillRect(lx, ly, colW - 60, 14); g.strokeStyle = '#d1d5db'; g.lineWidth = 1; g.strokeRect(lx, ly, colW - 60, 14);
        g.fillStyle = '#6b7280'; g.font = font(14); g.fillText(`≤ ${e.ramp.min}`, lx, ly + 32);
        g.textAlign = 'right'; g.fillText(`≥ ${e.ramp.max}`, lx + colW - 60, ly + 32); g.textAlign = 'left';
        ly += 46;
      } else {
        e.rows.forEach(r => {
          if (r.outline) { g.strokeStyle = r.color; g.lineWidth = 3; g.setLineDash([6, 4]); g.strokeRect(lx + 1, ly + 1, 18, 16); g.setLineDash([]); }
          else { g.fillStyle = r.color; g.fillRect(lx, ly, 20, 18); g.strokeStyle = 'rgba(0,0,0,.25)'; g.lineWidth = 1; g.strokeRect(lx, ly, 20, 18); }
          g.fillStyle = '#1f2933'; g.fillText(fitText(g, r.label + (r.count != null ? ` (${r.count})` : ''), colW - 40), lx + 30, ly + 15); ly += 26;
        });
      }
      ly += 10;
    }
  }

  // footer
  g.fillStyle = '#6b7280'; g.font = font(14);
  const footY = H - M - footH + 22;
  g.fillText(fitText(g, `Imagery and data: ${attributionText() || 'none'}`, W - 2 * M), M, footY);
  g.fillText(`Made with EviChange GIS · ${new Date().toISOString().slice(0, 10)} · change regions from a Sentinel-2 index-threshold detector; not field-validated`, M, footY + 22);
  return cv.toDataURL('image/png');
}
/** Shortens text with an ellipsis to fit `w` pixels in the current canvas font. */
function fitText(g, t, w) { if (g.measureText(t).width <= w) return t; while (t.length > 1 && g.measureText(t + '…').width > w) t = t.slice(0, -1); return t + '…'; }

function defaultSubtitle() {
  const p = changeLayer()?.data.features[0]?.properties;
  return p?.date_before ? `Before ${p.date_before.replace('/', ' – ')} · after ${p.date_after.replace('/', ' – ')}` : '';
}

async function makeLayout(then, onFail) {
  layout.busy = true; layout.msg = 'Drawing the layout…'; renderPanel();
  try {
    layout.preview = await buildLayout();
    layout.msg = '';
    then?.(layout.preview);
  } catch (err) {
    onFail?.();
    layout.msg = `Could not draw the map: ${err.message}. A basemap or layer that blocks cross-origin use can cause this; switch it off and retry.`;
  }
  layout.busy = false; renderPanel();
}

function printLayout(png, w) {
  if (!w || w.closed) { layout.msg = 'The browser blocked the print window. Allow pop-ups for this page, or save the PNG.'; return renderPanel(); }
  w.document.write(`<!doctype html><title>${esc(layout.title || 'EviChange map')}</title>
    <style>@page { size: A4 ${layout.orientation}; margin: 0 } html, body { margin: 0 } img { width: 100%; display: block }</style>
    <img src="${png}" onload="setTimeout(() => { print(); }, 100)">`);
  w.document.close();
}

function renderPrintPanel(body) {
  const layers = vectorLayers();
  if (!layout.title) layout.title = 'Detected land-cover change';
  if (!layout.subtitle) layout.subtitle = defaultSubtitle();
  const exp = layerById(layout.exportLayer) || layers[0];
  if (exp) layout.exportLayer = exp.id;
  const nSel = exp ? selectedFids(exp).size : 0;
  const opt = (v, label, sel) => `<option value="${esc(v)}" ${sel ? 'selected' : ''}>${esc(label)}</option>`;
  const chk = (k, label) => `<label class="check"><input type="checkbox" data-lo="${k}" ${layout[k] ? 'checked' : ''}> ${label}</label>`;
  body.innerHTML = `
    <div class="pane-subtitle">Export a layer</div>
    ${exp ? `<div class="section">
      <select id="exLayer" style="width:100%">${layers.map(l => opt(l.id, l.name, l === exp)).join('')}</select>
      ${nSel ? `<label class="check"><input type="checkbox" id="exSel" ${layout.exportSelected ? 'checked' : ''}> Only the ${nSel} selected features</label>` : ''}
      <div class="export-row">
        <button class="btn" data-ex="geojson">GeoJSON</button><button class="btn" data-ex="csv">CSV (Excel)</button><button class="btn" data-ex="kml">KML (Google Earth)</button>
      </div></div>` : '<p class="muted">No vector layers to export.</p>'}
    <div class="pane-subtitle">Print layout (A4)</div>
    <div class="section sym-controls">
      <label>Title<br><input type="text" id="loTitle" value="${esc(layout.title)}"></label>
      <label>Subtitle<br><input type="text" id="loSub" value="${esc(layout.subtitle)}"></label>
      <div class="seg section"><button data-or="landscape" class="${layout.orientation === 'landscape' ? 'on' : ''}">Landscape</button>
        <button data-or="portrait" class="${layout.orientation === 'portrait' ? 'on' : ''}">Portrait</button></div>
      ${chk('legend', 'Legend')}${chk('north', 'North arrow')}${chk('scale', 'Scale bar')}
    </div>
    <div class="card-actions">
      <button class="btn" id="loPreview" ${layout.busy ? 'disabled' : ''}>Preview</button>
      <button class="btn" id="loPng" ${layout.busy ? 'disabled' : ''}>Save PNG</button>
      <button class="btn primary" id="loPrint" ${layout.busy ? 'disabled' : ''}>Print / save as PDF</button>
    </div>
    ${layout.msg ? `<p class="muted">${esc(layout.msg)}</p>` : ''}
    ${layout.preview ? `<img class="layout-preview" src="${layout.preview}" alt="Layout preview">` : ''}
    <p class="muted small">The layout uses the current map view and visible layers. Change-type icons are not printed; colours and the legend are.</p>`;

  if (exp) {
    $('#exLayer').onchange = e => { layout.exportLayer = e.target.value; layout.exportSelected = false; renderPanel(); };
    const s = $('#exSel'); if (s) s.onchange = e => { layout.exportSelected = e.target.checked; };
    body.querySelectorAll('[data-ex]').forEach(b => b.onclick = () => {
      const n = exportLayer(exp, b.dataset.ex, layout.exportSelected);
      layout.msg = `Exported ${n} feature${n === 1 ? '' : 's'} as ${b.dataset.ex.toUpperCase()}.`; renderPanel();
    });
  }
  $('#loTitle').oninput = e => { layout.title = e.target.value; };
  $('#loSub').oninput = e => { layout.subtitle = e.target.value; };
  body.querySelectorAll('[data-or]').forEach(b => b.onclick = () => { layout.orientation = b.dataset.or; renderPanel(); });
  body.querySelectorAll('[data-lo]').forEach(c => c.onchange = () => { layout[c.dataset.lo] = c.checked; });
  $('#loPreview').onclick = () => makeLayout();
  $('#loPng').onclick = () => makeLayout(png => saveFile(`${slug(layout.title)}.png`, png, 'image/png'));
  $('#loPrint').onclick = () => {
    const w = window.open('', '_blank');    // open now, while the click still counts: after the await it would be blocked
    makeLayout(png => printLayout(png, w), () => w?.close());
  };
}
