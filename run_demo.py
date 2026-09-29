"""Run the multi-agent pipeline a few times and print every handoff."""
import json

from agents.graph import run_pipeline
from agents.study import load_study_config

STUDY = load_study_config()
AOI = STUDY["aoi"]


if __name__ == "__main__":
    print("Running the pipeline 5 times (some runs exercise the retry path)\n")
    result = None
    for name in ["run_a", "run_b", "run_c", "run_d", "run_e"]:
        result = run_pipeline(name, AOI, STUDY["before_window"], STUDY["after_window"])
        print(f"--- {name} --- status={result['status']} attempts={result['attempt']}")
        for entry in result["log"]:
            marker = {"ok": "  ", "error": "!!", "retry": "~~"}.get(entry["event"], "->")
            print(f"  {marker} {entry['agent']:20s} {entry['detail']}")
        print()

    print("Full published report from the last run:")
    print(json.dumps(result.get("published_report", {}), indent=2))
