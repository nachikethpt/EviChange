"""Shared typed state passed between every pipeline node."""
from typing import Literal, Optional, TypedDict


class LogEntry(TypedDict):
    agent: str
    event: str
    detail: str


class PipelineState(TypedDict, total=False):
    aoi: dict
    aoi_name: str
    date_before: str
    date_after: str
    task: Literal["change_detection"]
    condition: Literal["template", "ungated", "gated"]
    scene_before_id: str
    scene_after_id: str
    cloud_pct_before: float
    cloud_pct_after: float
    preprocessing_version: str
    tiles_ready: bool
    model_version: str
    change_frac: float
    regions: list[dict]
    prompt_version: str
    claims: list[dict]
    abstain: list[dict]
    raw_output: Optional[str]
    published_geojson: dict
    published_report: dict
    step: str
    attempt: int
    max_attempts: int
    status: Literal["running", "done", "failed"]
    error: Optional[str]
    log: list[LogEntry]


def log(state: PipelineState, agent: str, event: str, detail: str = "") -> list[LogEntry]:
    return [*state.get("log", []), {"agent": agent, "event": event, "detail": detail}]
