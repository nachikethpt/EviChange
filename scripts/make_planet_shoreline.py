"""Extract Planet shorelines on unlocked Phase 11 transects; resume cached batches after interruption.

    python scripts/make_planet_shoreline.py

Reads delivered EE mosaics only. Writes separate planet.json; radar / frozen evidence are unchanged.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import planet, planet_shoreline, shoreline  # noqa: E402
from agents.ee_engine import _ee                       # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    transects, positions = shoreline.load("transects.geojson"), shoreline.load("positions.json")
    if not transects or not positions:
        raise SystemExit("run scripts/make_shoreline.py first")
    catalog = planet.month_catalog(_ee())
    result = planet_shoreline.build(transects, positions["months"], catalog)
    path = shoreline.SHORELINE_DIR / planet_shoreline.FILE
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(planet_shoreline.summary(result, transects), ensure_ascii=False, indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
