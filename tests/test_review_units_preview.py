import hashlib
import json

import pytest

from app import grounding_experiment, review_units_preview
from app.review_units import build_review_windows


ANSWER = "仅限经理级别及以上：\n\n可以申请Coaching。[1]\n\n仍需符合其他资格条件。[1]"


def source_file(tmp_path):
    data = {"run_id": "saved", "evaluation_kind": "optimized_end_to_end", "dataset_id": "example",
            "records": [{"case_id": "EXAMPLE", "question": "谁能申请？", "http_status": 200,
                         "error_kind": None, "result": {"response": ANSWER, "references": [
                             {"reference_id": "1", "file_path": "policy.md", "content": ["Only managers qualify."]}],
                             "llm_generated": True, "response_time": 1.0}}]}
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_preview_is_offline_and_preserves_source_and_original_spans(tmp_path, monkeypatch, capsys):
    source = source_file(tmp_path); before = source.read_bytes()
    def fail(*args, **kwargs): pytest.fail("Preview must not load keys or request a model")
    monkeypatch.setattr(grounding_experiment, "load_answer_settings", fail)
    monkeypatch.setattr(grounding_experiment.httpx, "Client", fail)
    output = tmp_path / "output"
    monkeypatch.setattr(review_units_preview, "OUTPUT_DIR", output)
    args = ["--source", str(source), "--case", "EXAMPLE", "--neighbors", "1"]
    review_units_preview.main(args)
    report = json.loads(next(output.glob('*_units.json')).read_text(encoding="utf-8"))
    assert report["evaluation_kind"] == "offline_review_window_preview"
    assert report["status"] == "prepared_unreviewed"
    assert report["neighbor_count"] == 1
    assert report["windows"] == build_review_windows(ANSWER, neighbor_count=1)
    assert report["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert report["source_answer"] == ANSWER
    assert report["references"][0]["content"] == ["Only managers qualify."]
    assert source.read_bytes() == before
    assert "No model request sent" in capsys.readouterr().out
    # Repeated preparation also preserves its own output instead of overwriting.
    review_units_preview.main(args)
    assert len(list(output.glob('*_units.json'))) == 2


@pytest.mark.parametrize("neighbors", ["0", "2"])
def test_preview_records_explicit_neighbor_choice(tmp_path, monkeypatch, neighbors):
    source = source_file(tmp_path);output=tmp_path/'out'
    monkeypatch.setattr(review_units_preview, "OUTPUT_DIR", output)
    review_units_preview.main(["--source",str(source),"--case","EXAMPLE","--neighbors",neighbors])
    report=json.loads(next(output.glob('*_units.json')).read_text(encoding='utf-8'))
    assert report['windows']==build_review_windows(ANSWER,neighbor_count=int(neighbors))


@pytest.mark.parametrize("neighbors", ["-1", "bad"])
def test_invalid_neighbor_count_writes_no_report(tmp_path, monkeypatch, neighbors):
    output=tmp_path/'out';monkeypatch.setattr(review_units_preview,"OUTPUT_DIR",output)
    with pytest.raises(SystemExit) as exc:
        review_units_preview.main(["--source",str(source_file(tmp_path)),"--case","EXAMPLE","--neighbors",neighbors])
    assert exc.value.code==2
    assert not output.exists()


def test_unknown_case_is_rejected_before_creating_report(tmp_path, monkeypatch):
    output=tmp_path/'out';monkeypatch.setattr(review_units_preview,"OUTPUT_DIR",output)
    with pytest.raises(SystemExit) as exc:
        review_units_preview.main(["--source",str(source_file(tmp_path)),"--case","MISSING","--neighbors","1"])
    assert exc.value.code==2
    assert not output.exists()


def test_list_preview_records_segmentation_and_full_parent(tmp_path, monkeypatch):
    source = source_file(tmp_path)
    data = json.loads(source.read_text(encoding="utf-8"))
    data["records"][0]["result"]["response"] = "前提：\n- 需经理批准。[1]\n- 需提供证明。[1]"
    source.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "out"
    monkeypatch.setattr(review_units_preview, "OUTPUT_DIR", output)
    review_units_preview.main(["--source", str(source), "--case", "EXAMPLE", "--neighbors", "1", "--split-lists"])
    report = json.loads(next(output.glob('*_units.json')).read_text(encoding="utf-8"))
    assert report["segmentation"] == "top_level_list_items"
    assert len(report["windows"]) == 3
    assert report["windows"][2]["shared_intro"]["text"] == "前提："
    assert report["windows"][2]["parent_paragraph"]["text"] == data["records"][0]["result"]["response"]
