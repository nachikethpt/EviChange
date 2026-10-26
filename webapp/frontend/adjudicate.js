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

  function render() {
    const { sites, index, pass, source } = state;
    if (!sites.length) { $('site').innerHTML = '<p class="adj-empty">No claims in these reports.</p>'; return; }
    const site = sites[index];
    const chips = site.chips.length
      ? site.chips.map((c) => `<figure><img loading="lazy" alt="${esc(c)}" src="/api/adjudicate/${source}/chip/${encodeURIComponent(site.site_id)}/${encodeURIComponent(c)}">
          <figcaption>${esc(c.replace('.png', '').replace('_', ' · '))}</figcaption></figure>`).join('')
      : '<p class="adj-empty">No cached chips for this box (they are made when a model run renders them).</p>';
    const label = site.label ? `<div><b>Ground-truth label</b>: change ${esc(site.label.change_occurred)}${site.label.change_types?.length ? ` (${site.label.change_types.map(esc).join(', ')})` : ''}, confidence ${esc(site.label.confidence)}${site.label.notes ? ` — ${esc(site.label.notes)}` : ''}</div>` : '';
    const evidence = pass === 2 && site.evidence ? `<details open><summary><b>Evidence</b> the system had (judge support against this only)</summary><pre>${esc(JSON.stringify(site.evidence, null, 1))}</pre></details>` : '';
    const items = site.items.map((it) => {
      const j = site.judgements[it.item_id] || {};
      return `<div class="adj-item ${j[field(pass)] ? 'done' : ''}" id="item-${it.item_id}">
        <div class="adj-text"><span class="adj-level">${esc(it.level)}</span>${esc(it.text)}</div>${choices(it, j, pass)}</div>`;
    }).join('');
    $('site').innerHTML = `<section class="adj-site">
      <div class="adj-site-head"><h2>Site ${index + 1} of ${sites.length}</h2>
        <button class="adj-btn" id="prev" ${index === 0 ? 'disabled' : ''}>← Previous</button>
        <button class="adj-btn" id="next" ${index === sites.length - 1 ? 'disabled' : ''}>Next →</button>
        <button class="adj-btn" id="open">Next unfinished</button></div>
      ${pass === 1 ? (site.chips.length ? `<div class="adj-chips">${chips}</div>` : chips) : ''}
      <div class="adj-ref">${pass === 1 ? label : evidence}</div>
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
