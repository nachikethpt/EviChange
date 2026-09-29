"""Shared study configuration loading for scripts and the agent pipeline."""
from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STUDY_PATH = REPO_ROOT / "data" / "quangninh" / "study.json"


def load_study_config(path: str | Path = DEFAULT_STUDY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
