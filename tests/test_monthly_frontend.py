"""Exercise the monthly slider's async imagery and gap behaviour under node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "webapp" / "frontend" / "monthly.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_js(body):
    script = r"""
const fs = require('node:fs'), assert = require('node:assert/strict');
const elements = { '#monLabel': {}, '#monChart': {}, '#monMsg': {} };
const $ = key => elements[key];
const esc = text => String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
let source = { tiles: ['old'] }, layer = true, requested = [];
const map = {
  getLayer: id => id === 'mon-raster' && layer,
  getSource: () => source,
  removeLayer: () => { layer = false; },
  removeSource: () => { source = null; },
  addSource: (id, data) => { source = data; },
  addLayer: () => { layer = true; },
};
eval(fs.readFileSync(JS_PATH, 'utf8') + '\n' + `(async () => {
  mon.months = ['2025-01', '2025-02', '2025-03'];
  mon.layer = 'planet_rgb';
  TEST_BODY
})().catch(err => { console.error(err); process.exitCode = 1; });`);
""".replace("JS_PATH", json.dumps(str(JS))).replace("TEST_BODY", body)
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_planet_source_and_acquisition_metadata():
    run_js(r"""
  global.fetch = async url => {
    requested.push(url);
    return { ok: true, json: async () => ({ tiles: ['planet'], date: '2025-01-16', scale_m: 3,
      clear_share: 0.6, attribution: 'Imagery © Planet Labs PBC' }) };
  };
  await monthlyShow(0);
  assert.deepEqual(requested, ['/api/planet/layer?month=2025-01&layer=rgb']);
  assert.equal(source.attribution, 'Imagery © Planet Labs PBC');
  assert.match(elements['#monMsg'].textContent, /2025-01-16.*60%/);
  assert.equal(mon.on, true);
""")


def test_missing_month_clears_previous_imagery():
    run_js(r"""
  global.fetch = async () => ({ ok: false, json: async () => ({ detail: 'no Planet mosaic: shown as a gap' }) });
  await monthlyShow(1);
  assert.equal(source, null);
  assert.equal(layer, false);
  assert.equal(mon.on, false);
  assert.match(elements['#monMsg'].textContent, /gap/);
""")


def test_slow_old_request_cannot_replace_the_selected_month():
    run_js(r"""
  let first;
  global.fetch = url => {
    if (url.includes('2025-01')) return new Promise(resolve => { first = resolve; });
    return Promise.resolve({ ok: true, json: async () => ({ tiles: ['march'], date: '2025-03-20',
      scale_m: 3, clear_share: 0.9, attribution: 'Planet' }) });
  };
  const old = monthlyShow(0);
  assert.equal(source, null);                 // remove stale imagery as soon as the date changes
  await monthlyShow(2);
  first({ ok: true, json: async () => ({ tiles: ['january'], scale_m: 3, attribution: 'Planet' }) });
  await old;
  assert.deepEqual(source.tiles, ['march']);
  assert.match(elements['#monMsg'].textContent, /2025-03-20/);
""")
