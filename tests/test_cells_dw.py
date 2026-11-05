import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cells_dw  # noqa: E402


def test_month_range_rolls_over_the_year():
    assert cells_dw.month_range("2024-10") == ("2024-10-01", "2024-11-01")
    assert cells_dw.month_range("2025-12") == ("2025-12-01", "2026-01-01")


def test_built_needs_more_than_half_and_an_observation():
    assert cells_dw.is_built(0.56) is True
    assert cells_dw.is_built(0.5) is False          # exactly half is not "more than half" (D13 (c))
    assert cells_dw.is_built(0.0) is False
    assert cells_dw.is_built(None) is None          # no Dynamic World look: left out


def test_label_months_refuses_before_the_labels_exist(tmp_path):
    with pytest.raises(SystemExit):
        cells_dw.label_months(tmp_path)


def test_label_months_reads_the_labelled_months(tmp_path):
    rec = {"protocol": "labels14_v1", "labeler": "labeler1", "labeled_at": "2026-11-02T11:42:28", "cell_id": "c01",
           "dates": ["2024-10", "2025-11"], "months": {"2024-10": "built", "2025-11": "not_built"},
           "confidence": "medium", "notes": "", "seconds_spent": 44}
    (tmp_path / "labels14_cells.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert cells_dw.label_months(tmp_path) == ["2024-10", "2025-11"]
