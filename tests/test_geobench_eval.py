"""scripts/geobench_eval.py, the GPU-free parts (question loading, prompt, letter parsing, table)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import geobench_eval as ge  # noqa: E402


def test_parse_letter():
    assert ge.parse_letter("B") == "B" and ge.parse_letter("B. Tsunami") == "B" and ge.parse_letter("(C)") == "C"
    assert ge.parse_letter("Answer: E") == "E" and ge.parse_letter("The answer is D.") == "D"
    assert ge.parse_letter("Because ...") is None and ge.parse_letter("") is None


def test_questions_prompt_and_table(tmp_path):
    qa = [{"question_id": 0, "image_path": ["farm_pond/a_t1.png", "farm_pond/a_t2.png"], "prompts": ["Did a pond appear?"],
           "options": "A. yes  B. no  C. two  D. three  E. four", "ground_truth_option": "A"},
          {"question_id": 1, "image_path": "land_use/b.png", "task": "Land Use Classification", "prompts": ["Land use?"],
           "options": "A. a  B. b  C. c  D. d  E. e", "ground_truth_option": "C"}]
    (tmp_path / "qa.json").write_text(json.dumps(qa))
    qs = ge.load_questions(tmp_path)
    assert [ge.task_of(q) for q in qs] == ["farm_pond", "Land Use Classification"]
    assert [p.name for p in ge.image_paths(qs[0], tmp_path)] == ["a_t1.png", "a_t2.png"]
    p = ge.build_prompt(qs[0])
    assert p.startswith("Did a pond appear?\nA. yes") and p.endswith("(A, B, C, D or E).")
    t = ge.table([{"task": "farm_pond", "gt": "A", "pred": "A"}, {"task": "farm_pond", "gt": "A", "pred": None},
                  {"task": "Land Use Classification", "gt": "C", "pred": "B"}])
    assert "| farm_pond | 2 | 50.0% | 1 |" in t and "| **all** | 3 | **33.3%** | 1 |" in t and "random guess" in t
