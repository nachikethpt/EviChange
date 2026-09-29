"""Run the multi-agent pipeline and publish the result straight to the web app.

Retries a few times if the mock "too cloudy" case comes up (same behavior the
Orchestrator itself does internally, just at the whole-run level too — real
Earth Engine ingestion won't need this once query_scenes() is swapped in,
since you control the date range yourself there).

    python run_and_publish.py                          # default AOI, gated condition
    python run_and_publish.py --condition ungated
"""
import argparse
from agents.graph import run_pipeline
from agents.study import load_study_config

STUDY = load_study_config()
AOI = STUDY["aoi"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", default="gated", choices=["template", "ungated", "gated"])
    ap.add_argument("--runs", type=int, default=5, help="whole-pipeline attempts if every run fails")
    args = ap.parse_args()

    for i in range(1, args.runs + 1):
        r = run_pipeline(aoi_name=f"cli_run_{i}", aoi=AOI, before_window=STUDY["before_window"], after_window=STUDY["after_window"],
                          condition=args.condition, publish_live=True)
        print(f"run {i}: status={r['status']} attempts={r['attempt']}")
        for e in r["log"]:
            print(f"   {e['agent']:20s} {e['event']:6s} {e['detail']}")
        if r["status"] == "done":
            print("\nPublished. Start (or refresh) the web app to see it: run_webapp_windows.bat")
            break
    else:
        print("\nEvery attempt failed (mock cloud cover) — this is expected sometimes with mock data; just run again.")
