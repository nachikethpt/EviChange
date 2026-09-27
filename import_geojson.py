"""Bring Person 1's REAL Earth Engine export into the web app.

EviChange_Person1_starter.ipynb (../notebooks/) ends by saving
`change_regions_quangninh_v1.json` to Google Drive. Download that file, then:

    python import_geojson.py path\to\change_regions_quangninh_v1.json

Refresh the web app in your browser — it now shows Person 1's real regions
instead of demo or agent-mock data. Property names already match
(agents/schema.py REGION_FIELDS), so nothing is translated, only validated
and copied into place.
"""
import json
import sys
from pathlib import Path

from agents.schema import validate_change_regions
from agents.webapp_bridge import DATA_DIR


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    src = Path(sys.argv[1])
    fc = json.loads(src.read_text())
    errors = validate_change_regions(fc)
    if errors:
        sys.exit(f"{src} does not match agents/schema.py:
  " + "
  ".join(errors[:20]))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "change_regions.json").write_text(json.dumps(fc, indent=2))
    print(f"Imported {len(fc['features'])} regions from {src.name}")
    print(f"Wrote: {DATA_DIR / 'change_regions.json'}")
    print("Refresh the web app in your browser to see it (server does not need restarting).")
    print("Note: this did not touch aoi.json — if Person 1's AOI differs from the demo one, "
          "also copy their AOI GeoJSON to", DATA_DIR / "aoi.json")


if __name__ == "__main__":
    main()
