"""LangGraph wiring, including a bounded preprocessing retry loop."""
from langgraph.graph import END, StateGraph

from .schema import CONDITIONS, check, validate_aoi, validate_windows
from .nodes import dl_analysis_agent, geovlm_agent, ingestion_agent, orchestrator, preprocessing_agent, publishing_agent
from .state import PipelineState, log
from .study import load_study_config


def _failed_node(state: PipelineState) -> dict:
    return {"status": "failed", "log": log(state, "orchestrator", "error", "pipeline stopped")}


def _after_orchestrator(state: PipelineState) -> str:
    if state.get("status") == "failed":
        return "failed"

    attempt = int(state.get("attempt", 0))
    max_attempts = max(int(state.get("max_attempts", 1)), 1)
    if attempt > max_attempts:
        return "failed"

    normalized_condition = str(state.get("condition", "gated")).strip().lower()
    if normalized_condition not in CONDITIONS:
        return "failed"

    try:
        check(validate_aoi(state.get("aoi")), "AOI")
    except ValueError:
        return "failed"

    if validate_windows(state.get("before_window"), state.get("after_window")):
        return "failed"

    return "ingestion_agent"


def _after_preprocessing(state: PipelineState) -> str:
    if state.get("tiles_ready"):
        return "dl_analysis_agent"
    return "orchestrator" if state["attempt"] < state["max_attempts"] else "failed"


def build_graph():
    graph = StateGraph(PipelineState)
    for name, node in (
        ("orchestrator", orchestrator),
        ("ingestion_agent", ingestion_agent),
        ("preprocessing_agent", preprocessing_agent),
        ("dl_analysis_agent", dl_analysis_agent),
        ("geovlm_agent", geovlm_agent),
        ("publishing_agent", publishing_agent),
        ("failed", _failed_node),
    ):
        graph.add_node(name, node)
    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges("orchestrator", _after_orchestrator, {"ingestion_agent": "ingestion_agent", "failed": "failed"})
    graph.add_edge("ingestion_agent", "preprocessing_agent")
    graph.add_conditional_edges("preprocessing_agent", _after_preprocessing, {"orchestrator": "orchestrator", "dl_analysis_agent": "dl_analysis_agent", "failed": "failed"})
    graph.add_edge("dl_analysis_agent", "geovlm_agent")
    graph.add_edge("geovlm_agent", "publishing_agent")
    graph.add_edge("publishing_agent", END)
    graph.add_edge("failed", END)
    return graph.compile()


def run_pipeline(aoi_name: str, aoi: dict, before_window: list[str], after_window: list[str], condition: str = "gated", max_attempts: int = 3, publish_live: bool = False) -> PipelineState:
    normalized_condition = str(condition).strip().lower() if condition is not None else "gated"
    bounded_attempts = max(int(max_attempts), 1)
    return build_graph().invoke({
        "aoi": aoi,
        "aoi_name": aoi_name,
        "before_window": before_window,
        "after_window": after_window,
        "thresholds": load_study_config()["thresholds"],
        "task": "change_detection",
        "condition": normalized_condition,
        "publish_live": publish_live,
        "attempt": 0,
        "max_attempts": bounded_attempts,
        "status": "running",
        "log": [],
    })
