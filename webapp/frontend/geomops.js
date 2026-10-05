/* EviChange GIS — geometry operations behind ⚙ Tools (Phase 7b c, decisions.md D8).
 * Pure functions on GeoJSON (Turf only, no DOM or map), so they run inside geomworker.js:
 * Sentinel-2 regions are pixel-edged and one can have 100k+ vertices, which makes exact
 * cutting / buffering take seconds — too long for the page's main thread.
 * Every op takes plain features and returns plain features (or feature ids).
 */
'use strict';

const isPoly = f => /Polygon$/.test(f.geometry?.type);
const isPoint = f => /Point$/.test(f.geometry?.type);
function bboxOverlap(a, b) { return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]; }
function cleanProps(p) { const { __fid, ...rest } = p; return rest; }
function polygonsOf(f) { return f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates; }

/** Polygon outputs get their own area; the source value is kept as area_ha_src. */
function withArea(f, props) {
  const out = { ...props };
  if (isPoly(f)) {
    if (out.area_ha != null) out.area_ha_src = out.area_ha;
    out.area_ha = Math.round(turf.area(f) / 100) / 100;
  }
  return turf.feature(f.geometry, out);
}

/** Union of many polygons. Polygons whose bounding boxes don't touch can't overlap, so only
 *  touching clusters go through turf.union (slow on pixel-edged regions); the rest are just collected. */
function unionAll(polys) {
  if (!polys.length) return null;
  if (polys.length === 1) return polys[0];
  const boxes = polys.map(p => turf.bbox(p)), parent = polys.map((_, i) => i);
  const find = i => { while (parent[i] !== i) i = parent[i] = parent[parent[i]]; return i; };
  for (let i = 0; i < polys.length; i++)
    for (let j = i + 1; j < polys.length; j++) if (bboxOverlap(boxes[i], boxes[j])) parent[find(i)] = find(j);
  const clusters = new Map();
  polys.forEach((p, i) => { const r = find(i); (clusters.get(r) || clusters.set(r, []).get(r)).push(p); });
  const parts = [];
  clusters.forEach(c => {
    const u = c.length === 1 ? c[0] : turf.union(turf.featureCollection(c));
    if (u) parts.push(...polygonsOf(u));
  });
  if (!parts.length) return null;
  return turf.feature(parts.length === 1 ? { type: 'Polygon', coordinates: parts[0] } : { type: 'MultiPolygon', coordinates: parts });
}

/** True when the feature's bounding box lies inside one hole-free part of `poly`, so the feature does too. */
function whollyInside(f, poly) {
  const box = turf.bboxPolygon(turf.bbox(f));
  return polygonsOf(poly).some(rings => rings.length === 1 && turf.booleanWithin(box, turf.polygon(rings)));
}

function pointsInside(f, poly) {
  const pts = f.geometry.type === 'Point' ? [f.geometry.coordinates] : f.geometry.coordinates;
  return pts.some(c => turf.booleanPointInPolygon(c, poly));
}

/** The part of `f` inside `poly`: polygons are cut, points tested, lines kept whole when they cross. */
function overlayOne(f, poly) {
  if (isPoly(f)) return whollyInside(f, poly) ? f : turf.intersect(turf.featureCollection([f, poly]));
  if (isPoint(f)) return pointsInside(f, poly) ? f : null;
  return turf.booleanIntersects(f, poly) ? f : null;
}

function ticker(n, progress) {
  let last = 0;
  return i => { const now = Date.now(); if (progress && now - last > 250) { last = now; progress(i / n); } };
}

// ---------- ops (args are plain objects so they can cross postMessage) ----------
const GEO_OPS = {
  buffer({ feats, distance, units, dissolve }, progress) {
    const tick = ticker(feats.length, progress);
    let out = feats.map((f, i) => {
      tick(i);
      const b = turf.buffer(f, distance, { units });
      return b && b.geometry ? withArea(b, cleanProps(f.properties)) : null;
    }).filter(Boolean);
    if (dissolve) { const u = unionAll(out); out = u ? [withArea(u, { buffer: `${distance} ${units}` })] : []; }
    return { features: out };
  },

  /** Clip: one output per input feature, cut by the whole clip area. */
  clip({ feats, polys }, progress) {
    const area = unionAll(polys), ab = turf.bbox(area), tick = ticker(feats.length, progress);
    const out = []; let lines = 0, skipped = 0;
    feats.forEach((f, i) => {
      tick(i);
      if (!bboxOverlap(turf.bbox(f), ab)) return;
      try { const g = overlayOne(f, area); if (g) { out.push(withArea(g, cleanProps(f.properties))); if (!isPoly(f) && !isPoint(f)) lines++; } }
      catch (e) { skipped++; }
    });
    return { features: out, lines, skipped };
  },

  /** Intersect: one output per overlapping pair, attributes from both (the other's prefixed). */
  intersect({ feats, polys, prefix }, progress) {
    const boxes = polys.map(p => turf.bbox(p)), tick = ticker(feats.length, progress);
    const out = []; let lines = 0, skipped = 0;
    feats.forEach((f, i) => {
      tick(i);
      const fb = turf.bbox(f);
      polys.forEach((p, j) => {
        if (!bboxOverlap(fb, boxes[j])) return;
        try {
          const g = overlayOne(f, p);
          if (!g) return;
          const b = Object.fromEntries(Object.entries(cleanProps(p.properties)).map(([k, v]) => [`${prefix}_${k}`, v]));
          out.push(withArea(g, { ...cleanProps(f.properties), ...b }));
          if (!isPoly(f) && !isPoint(f)) lines++;
        } catch (e) { skipped++; }
      });
    });
    return { features: out, lines, skipped };
  },

  dissolve({ polys, field }, progress) {
    const groups = new Map();
    polys.forEach(f => { const k = field ? String(f.properties[field] ?? '(no value)') : 'all'; (groups.get(k) || groups.set(k, []).get(k)).push(f); });
    const tick = ticker(groups.size, progress);
    const out = [...groups].map(([k, fs], i) => {
      tick(i);
      const u = unionAll(fs);
      return u ? withArea(u, { ...(field ? { [field]: k } : {}), count: fs.length }) : null;
    }).filter(Boolean);
    return { features: out };
  },

  /** __fid of each target feature that intersects / lies within / is within a distance of a shape. */
  selectByLocation({ targets, shapes, relation, distance, units }, progress) {
    if (relation === 'within_distance') shapes = shapes.map(f => turf.buffer(f, distance, { units })).filter(Boolean);
    const boxes = shapes.map(s => turf.bbox(s)), tick = ticker(targets.length, progress);
    const hits = [];
    targets.forEach((f, i) => {
      tick(i);
      const fb = turf.bbox(f);
      const ok = shapes.some((s, j) => {
        if (!bboxOverlap(fb, boxes[j])) return false;
        try { return relation === 'within' ? turf.booleanWithin(f, s) : turf.booleanIntersects(f, s); } catch (e) { return false; }
      });
      if (ok) hits.push(f.properties.__fid);
    });
    return { fids: hits };
  },
};
