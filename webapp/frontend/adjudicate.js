// Claim adjudication page (Phase 5). The server sends a blinded queue (eval/adjudication.py): no
// condition, no verdict, no region ids. Every change is saved at once, so closing the tab loses nothing.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const store = {
    get(k) { try { return localStorage.getItem('evichange-adj-' + k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem('evichange-adj-' + k, v); } catch (e) { /* private window */ } },
  };
  let state = null;   // {source, who, role, pass, sites, index}

  for (const k of ['source', 'who', 'role', 'pass']) {
    const v = store.get(k);
    if (v) $(k).value = v;
  }

  $('setup').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const cfg = { source: $('source').value, who: $('who').value.trim(), role: $('role').value, pass: Number($('pass').value) };
    for (const [k, v] of Object.entries(cfg)) store.set(k, v);
    $('site').innerHTML = '<p class="adj-empty">Loading…</p>';
    const q = new URLSearchParams({ adjudicator: cfg.who, role: cfg.role, pass: cfg.pass });
    const resp = await fetch(`/api/adjudicate/${cfg.source}?${q}`);
    const data = await resp.json();
    if (!resp.ok) { $('site').innerHTML = `<p class="adj-empty adj-err">${esc(data.detail)}</p>`; return; }
    state = { ...cfg, sites: data.sites, index: firstOpen(data.sites, cfg.pass) };
    showProgress(data.progress);
    render();
  });

  const field = (pass) => (pass === 1 ? 'truth' : 'support');
  const done = (site, pass) => site.items.every((it) => site.judgements[it.item_id]?.[field(pass)]);
  function firstOpen(sites, pass) {
    const i = sites.findIndex((s) => !done(s, pass));
    return i < 0 ? 0 : i;
  }

  function showProgress(p) {
    $('progress').textContent = `${p.truth_done} / ${p.items} truth · ${p.support_done} / ${p.items} support`;
  }

  function choices(item, j, pass) {
    const name = `${field(pass)}-${item.item_id}`;
    const opts = pass === 1 ? ['true', 'false', 'unverifiable'] : ['supported', 'unsupported'];
    const radios = opts.map((o) => `<label><input type="radio" name="${name}" value="${o}" ${j[field(pass)] === o ? 'checked' : ''}
      data-item="${item.item_id}" data-field="${field(pass)}"> ${o}</label>`).join('');
    const flags = pass === 1 ? `
      <label title="The claim describes the detector or evidence, not the ground"><input type="checkbox" data-item="${item.item_id}"
        data-field="about_detector" ${j.about_detector ? 'checked' : ''}> about the detector</label>
      <label title="The claim joins two or more statements"><input type="checkbox" data-item="${item.item_id}"
        data-field="compound" ${j.compound ? 'checked' : ''}> compound</label>` : '';
    return `<div class="adj-choices">${radios}${flags}</div>
      <input class="adj-note" placeholder="note (optional, e.g. R3 area)" data-item="${item.item_id}" data-field="note" value="${esc(j.note)}">`;
  }

  // Pass 2: the evidence as tables, so a claim can be checked field by field (same data as the raw JSON).
  const num = (v, d = 2) => (v === null || v === undefined ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(d));
  const dir = (v, up, down) => (v === null || v === undefined ? '' : v > 0 ? up : v < 0 ? down : 'no change');
  const table = (head, rows) => `<table class="adj-tbl"><thead><tr>${head.map((h) => `<th>${h}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  const topShares = (f) => Object.entries(f || {}).sort((a, b) => b[1] - a[1]).slice(0, 3)
    .map(([k, v]) => `${esc(k)} ${Math.round(v * 100)}%`).join(', ');
  function evidenceView(ev) {
    const regions = ev.regions || [], transects = ev.transects || [], strips = ev.coastal_strips || [];
    const total = regions.reduce((s, r) => s + (r.area_ha || 0), 0);
    const dates = (ev.dates || []).map((d) => d.join(' → ')).join('  vs  ');
    let html = `<div class="adj-ev-sum">
      <span><b>Dates</b> ${esc(dates)}</span>
      <span><b>Changed share of box</b> ${Math.round((ev.change_frac || 0) * 100)}%</span>
      <span><b>Regions</b> ${regions.length}${regions.length ? ` · <b>total</b> ${total.toFixed(2)} ha` : ' (detector found no change)'}</span>
      <span><b>Transects</b> ${transects.length} · <b>coastal strips</b> ${strips.length}</span></div>`;
    if (regions.length) {
      html += `<div class="adj-ev-h">Change regions in the box</div>` + table(
        ['id', 'area ha (in box)', 'whole region ha', 'where', 'dNDVI (vegetation)', 'dNDBI (built / bare)', 'dMNDWI (water)', 'class before → after', 'conf'],
        regions.map((r) => [esc(r.id), (r.area_ha ?? 0).toFixed(2), r.area_ha_whole_region != null ? Number(r.area_ha_whole_region).toFixed(2) : '—', esc(r.location),
          `${num(r.dNDVI)} <small>${dir(r.dNDVI, 'more veg', 'less veg')}</small>`,
          `${num(r.dNDBI)} <small>${dir(r.dNDBI, 'more built/bare', 'less built/bare')}</small>`,
          `${num(r.dMNDWI)} <small>${dir(r.dMNDWI, 'more water', 'less water')}</small>`,
          `${esc(r.class_before)} → ${esc(r.class_after)}<br><small>before: ${topShares(r.class_frac_before)}<br>after: ${topShares(r.class_frac_after)}</small>`,
          r.mean_conf != null ? Number(r.mean_conf).toFixed(2) : '—']));
    }
    if (transects.length) {
      html += `<div class="adj-ev-h">Shoreline transects</div>` + table(
        ['id', 'where', 'shoreline', 'net movement m', 'rate m/yr'],
        transects.map((t) => [esc(t.id), esc(t.location), esc(t.change), num(t.nsm, 0), num(t.lrr, 1)]));
    }
    if (strips.length) {
      html += `<div class="adj-ev-h">Built area near the shore</div>` + table(
        ['strip (m from shore)', 'where', 'built ha before', 'built ha after', 'change ha'],
        strips.map((c) => [esc(c.strip), esc(c.location), Number(c.built_ha_before).toFixed(2), Number(c.built_ha_after).toFixed(2),
          num(c.built_ha_after - c.built_ha_before)]));
    }
    return html + `<div class="adj-ev-note">Numbers count as supported within about 25 % of the evidence value.</div>`;
  }
  // numbers in a claim, bold, so they are easy to match against the tables
  const markNumbers = (html) => html.replace(/(?<![\w.#])([+−-]?\d+(?:\.\d+)?\s?(?:%|ha|hectares|km²|m\/yr|m)?)(?![^<]*>)/g, '<b class="adj-num">$1</b>');

  function render() {
    const { sites, index, pass, source } = state;
    if (!sites.length) { $('site').innerHTML = '<p class="adj-empty">No claims in these reports.</p>'; return; }
    const site = sites[index];
    // before / after pairs side by side: before_cir, after_cir, before_rgb, ...
    const when = (c) => (c.startsWith('before') ? 0 : 1);
    const band = (c) => c.replace(/^(before|after)_/, '');
    const ordered = [...site.chips].sort((a, b) => band(a).localeCompare(band(b)) || when(a) - when(b));
    const chips = site.chips.length
      ? ordered.map((c) => `<figure><img loading="lazy" alt="${esc(c)}" src="/api/adjudicate/${source}/chip/${encodeURIComponent(site.site_id)}/${encodeURIComponent(c)}">
          <figcaption>${esc(c.replace('.png', '').replace('_', ' · '))}</figcaption></figure>`).join('')
      : '<p class="adj-empty">No cached chips for this box (they are made when a model run renders them).</p>';
    const label = site.label ? `<div><b>Ground-truth label</b>: change ${esc(site.label.change_occurred)}${site.label.change_types?.length ? ` (${site.label.change_types.map(esc).join(', ')})` : ''}, confidence ${esc(site.label.confidence)}${site.label.notes ? ` — ${esc(site.label.notes)}` : ''}</div>` : '';
    const evidence = pass === 2 && site.evidence ? `<div class="adj-ev"><b>Evidence</b> the system had (judge support against this only)
      ${evidenceView(site.evidence)}
      <details><summary>raw JSON</summary><pre>${esc(JSON.stringify(site.evidence, null, 1))}</pre></details></div>` : '';
    const items = site.items.map((it) => {
      const j = site.judgements[it.item_id] || {};
      return `<div class="adj-item ${j[field(pass)] ? 'done' : ''}" id="item-${it.item_id}">
        <div class="adj-text"><span class="adj-level">${esc(it.level)}</span>${pass === 2 ? markNumbers(esc(it.text)) : esc(it.text)}</div>${choices(it, j, pass)}</div>`;
    }).join('');
    $('site').innerHTML = `<section class="adj-site">
      <div class="adj-sticky">
      <div class="adj-site-head"><h2>Site ${index + 1} of ${sites.length}</h2>
        <button class="adj-btn" id="prev" ${index === 0 ? 'disabled' : ''}>← Previous</button>
        <button class="adj-btn" id="next" ${index === sites.length - 1 ? 'disabled' : ''}>Next →</button>
        <button class="adj-btn" id="open">Next unfinished</button></div>
      ${pass === 1 ? (site.chips.length ? `<div class="adj-chips">${chips}</div>` : chips) : ''}
      <div class="adj-ref">${pass === 1 ? label : evidence}</div></div>
      ${items}</section>`;
    $('prev').onclick = () => go(index - 1);
    $('next').onclick = () => go(index + 1);
    $('open').onclick = () => {
      const after = sites.findIndex((s, i) => i > index && !done(s, pass));
      go(after >= 0 ? after : firstOpen(sites, pass));
    };
  }

  function go(i) {
    state.index = Math.max(0, Math.min(state.sites.length - 1, i));
    render();
    window.scrollTo({ top: 0 });
  }

  async function save(itemId, key, value) {
    const site = state.sites[state.index];
    site.judgements[itemId] = { ...(site.judgements[itemId] || {}), [key]: value };
    const resp = await fetch(`/api/adjudicate/${state.source}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, adjudicator: state.who, [key]: value }),
    });
    const data = await resp.json();
    if (!resp.ok) { alert(`Not saved: ${data.detail}`); return; }
    showProgress(data.progress);
    $(`item-${itemId}`)?.classList.toggle('done', Boolean(site.judgements[itemId][field(state.pass)]));
  }

  $('site').addEventListener('change', (ev) => {
    const el = ev.target;
    if (!el.dataset?.item) return;
    const value = el.type === 'checkbox' ? el.checked : el.value;
    save(el.dataset.item, el.dataset.field, value);
  });
})();
