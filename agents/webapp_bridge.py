"""Connects the multi-agent pipeline to the web app, so there is exactly ONE
implementation of claim generation (webapp/backend/report.py) instead of the
pipeline and the web app silently drifting apart — and so a pipeline run's
output shows up on the live map without any manual copy/paste step.

Both packages live at the repo root, so run scripts from there
(`python run_and_publish.py`, `python -m uvicorn webapp.backend.main:app`).
"""
from __future__ import annotations

import json

from webapp.backend import data_store, report

DATA_DIR = data_store.DATA_DIR


def build_report(ev: dict, condition: str) -> dict:
    return report.build_report(ev, condition)


def write_live_data(aoi_geojson: dict, change_regions_geojson: dict) -> None:
    """Write a pipeline run's output where the web app's data_store.py looks for it.
    Refresh the browser afterward — no server restart needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "aoi.json").write_text(json.dumps(aoi_geojson, indent=2))
    (DATA_DIR / "change_regions.json").write_text(json.dumps(change_regions_geojson, indent=2))
