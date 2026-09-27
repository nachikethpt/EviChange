"""Public entry points for the EviChange multi-agent pipeline.

`run_pipeline` / `build_graph` are loaded lazily so the web app can import
`agents.schema` and `agents.verifier` without pulling in LangGraph.
"""

__all__ = ["build_graph", "run_pipeline"]


def __getattr__(name):
    if name in __all__:
        from . import graph
        return getattr(graph, name)
    raise AttributeError(f"module 'agents' has no attribute {name!r}")
