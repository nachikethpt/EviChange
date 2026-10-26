"""webapp/frontend/assistant.js (D9 map assistant): the keyword parser, run under node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "webapp" / "frontend" / "assistant.js"
LAYERS = [{"id": "change", "name": "Detected change regions"}, {"id": "aoi", "name": "Study area (AOI)"},
          {"id": "gp-1", "name": "River lines"}, {"id": "gp-2", "name": "River buffer 500 m"}]

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def parse(*texts):
    script = (f"const a = require({json.dumps(str(JS))});"
              f"const L = {json.dumps(LAYERS)};"
              f"console.log(JSON.stringify({json.dumps(list(texts))}.map(t => a.parseActions(t, L))));")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


def test_single_actions():
    style, opac, buf, clip, diss, ndvi, exp, zoom, chart = parse(
        "make the AOI purple, 95% transparent", "set the change regions 40% opaque", "buffer the change regions by 2 km",
        "clip the change regions to the study area", "dissolve the change regions by location", "show the NDVI change",
        "export the selected change regions as CSV", "zoom to river lines", "open charts")
    assert style == {"steps": [{"action": "style_layer", "layer": "aoi", "color": "#9333ea", "opacity": pytest.approx(0.05)}]}
    assert opac["steps"][0] == {"action": "style_layer", "layer": "change", "opacity": 0.4}
    assert buf["steps"][0] == {"action": "buffer", "layer": "change", "distance": 2, "units": "kilometers"}
    assert clip["steps"][0] == {"action": "clip", "layer": "change", "other": "aoi"}
    assert diss["steps"][0] == {"action": "dissolve", "layer": "change", "field": "location"}
    assert ndvi["steps"][0] == {"action": "add_index_layer", "index": "NDVI", "kind": "change"}
    assert exp["steps"][0] == {"action": "export", "layer": "change", "format": "csv", "selectedOnly": True}
    assert zoom["steps"][0] == {"action": "zoom", "layer": "gp-1"}
    assert chart["steps"][0] == {"action": "chart"}


def test_chain_with_it():
    (r,) = parse("buffer the river lines by 500 m and clip the change regions to it")
    assert r["steps"] == [{"action": "buffer", "layer": "gp-1", "distance": 500, "units": "meters"},
                          {"action": "clip", "layer": "change", "other": {"ref": "last"}}]
    (r,) = parse("buffer the change regions by 100 m, then make it red")
    assert r["steps"][1] == {"action": "style_layer", "layer": {"ref": "last"}, "color": "#dc2626"}


def test_not_actions_fall_through_to_search():
    """Search requests must stay searches: parseActions returns null and the chat searches as before."""
    assert parse("vegetation loss bigger than 10 ha", "add new water in the north", "select trees to built",
                 "largest 5 changes", "make it bigger") == [None] * 5


def test_errors_never_run_anything():
    unknown, ambiguous, partial, it_first, zero, transp = parse(
        "buffer the roads by 50 m", "zoom to river", "buffer the change regions by 50 m then frobnicate the aoi",
        "clip it to the study area", "buffer the change regions by 0 m", "make the aoi 150% transparent")
    assert "No layer called “roads”" in unknown["error"] and "Nothing was run" in unknown["error"]
    assert "matches 2 layers" in ambiguous["error"]
    assert "not “frobnicate the aoi”" in partial["error"]
    assert "“it” needs an earlier step" in it_first["error"]
    assert "non-zero" in zero["error"] and "between 0 % and 100 %" in transp["error"]


def test_undo():
    assert parse("undo") == [{"steps": [{"action": "undo"}]}]
