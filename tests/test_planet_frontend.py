"""Planet UI: explicit dates, separate periods, and no stale results after a run/source switch."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "webapp" / "frontend"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_js(file, body):
    script = r"""
const assert = require('node:assert/strict'), fs = require('node:fs');
const state = {panel: 'changes', currentRunId: 'abc'}, explore = {meta: new Map([['r1', {fid: 1}]])};
const CHANGE_ID = 'change';
const esc = v => String(v).replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const info = t => ({short: t});
const map = {setFeatureState: (_key, value) => { map.last = value; }};
const renderPanel = () => {}, applyFilter = () => {}, $ = () => null;
eval(fs.readFileSync(JS_PATH, 'utf8') + '\n' + `(async () => { TEST_BODY })().catch(e => { console.error(e); process.exitCode = 1; });`);
""".replace("JS_PATH", json.dumps(str(FRONTEND / file))).replace("TEST_BODY", body)
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_different_planet_dates_never_hide_detector_results():
    run_js("geovlm.js", r"""
  gv.results.set('r1', {status: 'checked', verdict: 'no_change', comparable: false});
  assert.equal(vlmHidden('r1'), false);
  flagRegion('r1'); assert.equal(map.last.vlmNo, false);
  gv.results.set('r1', {status: 'checked', verdict: 'no_change', comparable: true});
  assert.equal(vlmHidden('r1'), true);
  flagRegion('r1'); assert.equal(map.last.vlmNo, true);
""")


def test_planet_request_snapshots_selected_dates_and_source():
    run_js("geovlm.js", r"""
  gv.source = 'planet'; gv.beforeMonth = '2025-01'; gv.afterMonth = '2025-09';
  let sent;
  global.fetch = async (_url, options) => {
    sent = JSON.parse(options.body);
    return {ok: true, json: async () => ({status: 'insufficient_imagery', detail: 'cloudy'})};
  };
  await checkRegions(['r1']);
  assert.deepEqual(sent, {region_id: 'r1', run_id: 'abc', source: 'planet',
    before_month: '2025-01', after_month: '2025-09', chips: 'planet_rgb_nir'});
  assert.equal(gv.results.get('r1').status, 'insufficient_imagery');
  assert.equal(vlmHidden('r1'), false);
""")


def test_slow_planet_answer_cannot_leak_into_another_run():
    run_js("geovlm.js", r"""
  let resolve;
  global.fetch = () => new Promise(r => {resolve = r;});
  const pending = checkRegions(['r1']);
  resetVlmResults(); state.currentRunId = 'another';
  resolve({ok: true, json: async () => ({status: 'checked', verdict: 'no_change'})});
  await pending;
  assert.equal(gv.results.size, 0);
  assert.equal(gv.running, false);
""")


def test_planet_controls_are_available_before_a_model_is_connected():
    run_js("geovlm.js", r"""
  gv.source = 'planet'; gv.status = {available: false, detail: 'off'};
  gv.planet = {months: [{month: '2025-01', date: '2025-01-12', clear_share: .9}]};
  const html = vlmSectionHtml([]);
  assert.match(html, /id="gvSource"/); assert.match(html, /id="gvBefore"/);
  assert.match(html, /2025-01-12/); assert.match(html, /Planet has no SWIR/);
""")


def test_shoreline_chart_keeps_planet_gaps_and_blind_references():
    run_js("shoreline.js", r"""
  shore.mode = 'months'; shore.tid = 't1';
  shore.detail = {series: [{month: '2025-01', pos: 5}, {month: '2025-02', pos: 10}],
    planet: {series: [{month: '2025-01', pos: 0}, {month: '2025-02', pos: null}]}};
  assert.deepEqual(shoreSeries().pts.map(p => p.opt), [0, null]);
  shore.detail = {hidden: true, series: null, planet: null};
  assert.match(shoreChart(), /hidden Phase 14/);
  shore.planet = {catalog: [{month: '2025-01', date: '2025-01-12'}], position_counts: {'2025-01': 10}};
  shore.labels = ['2025-01', '2025-02']; shore.idx = 1;
  assert.match(shorePlanetStatus(), /No delivered Planet mosaic.*gap/);
""")
