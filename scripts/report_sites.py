r"""The Phase 4/5 evaluation run: every report condition on the 30 labelled sites, with the prompts
frozen in D19 (gated_report_v6, ungated_report_v1 + claim_extract_v5 + claim_parse_v2).

The unit is each site's box, the yellow `outline` in data/quangninh/labels/sites.json (methods
draft). Each report is verified against that box's evidence (agents/site_evidence.py) and written to
data/reports_sites.jsonl in report_dev.py's record shape, which eval/adjudication.py and the
adjudication page read. `stratum` is "site": the detected / random key (sites_key.json) is joined only
when scoring (eval/metrics.py), so the adjudicator stays blind to it. Reruns skip logged reports.

    set VLM_URL=... & set VLM_TOKEN=...
    python scripts\report_sites.py --arms template,gated,ungated
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import report_dev                             # noqa: E402
import vlm_batch                              # noqa: E402
from agents import vlm_check                  # noqa: E402

LOG = ROOT / "data" / "reports_sites.jsonl"


def site_boxes() -> tuple[dict, list[dict]]:
    """(regions fc, [{'id': site id, 'stratum': 'site', 'box'}]) for the 30 labelled sites."""
    if not vlm_check.LABELLED_SITES_UNLOCKED:
        raise SystemExit("the labelled sites are still locked (vlm_check.LABELLED_SITES_UNLOCKED): freeze the prompts first")
    fc = json.loads(vlm_batch.REGIONS.read_text(encoding="utf-8"))
    boxes = []
    for site in json.loads(vlm_check.SITES_FILE.read_text(encoding="utf-8")):
        ring = site["outline"]["coordinates"][0]
        box = (min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring))
        boxes.append({"id": site["site_id"], "stratum": "site", "box": box})
    return fc, boxes


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arms", default=",".join(report_dev.ARMS), help="comma-separated: template, gated, ungated")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    bad = [a for a in arms if a not in report_dev.ARMS]
    if bad:
        raise SystemExit(f"unknown arms {bad}; choose from {report_dev.ARMS}")
    from agents.vlm_client import VLMClient
    counts = report_dev.run(VLMClient(), arms, log_path=LOG, boxes=site_boxes())
    print(f"done {counts['done']}, already logged {counts['skipped']}, failed {counts['failed']} -> {LOG}")


if __name__ == "__main__":
    main()
