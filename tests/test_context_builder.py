from copy import deepcopy
import json

from app import context_builder


CHUNKS = [
    {"chunk_id": "A", "file_path": "leave.md", "reference_id": "9",
     "content": "Manager coordination is required.", "rerank_score": 0.9},
    {"chunk_id": "B", "file_path": "pto.md", "reference_id": "4",
     "content": "Give six business days notice.", "rerank_score": 0.8},
]


def test_new_ids_match_context_and_returned_source_list():
    result = context_builder.build_evidence_context(CHUNKS)
    evidence = json.loads(result["context"])
    assert [e["reference_id"] for e in evidence] == ["1", "2"]
    assert [r["reference_id"] for r in result["references"]] == ["1", "2"]
    for item in evidence:
        ref = next(r for r in result["references"] if r["reference_id"] == item["reference_id"])
        assert ref["file_path"] == item["file_path"]
        assert item["content"] in ref["content"]
    assert [e["chunk_id"] for e in evidence] == ["A", "B"]


def test_multiple_chunks_from_one_file_share_one_reference():
    chunks = [CHUNKS[0], CHUNKS[1], {**CHUNKS[0], "chunk_id": "C", "content": "Another rule."}]
    result = context_builder.build_evidence_context(chunks)
    assert len(result["references"]) == 2
    assert result["references"][0]["content"] == [CHUNKS[0]["content"], "Another rule."]
    assert [x["reference_id"] for x in json.loads(result["context"])] == ["1", "2", "1"]


def test_input_and_original_ids_are_not_mutated():
    chunks = deepcopy(CHUNKS)
    result = context_builder.build_evidence_context(chunks)
    assert chunks == CHUNKS
    assert "rerank_score" not in json.loads(result["context"])[0]
    assert len(json.loads(result["context"])) == len(chunks)


def test_empty_selection_has_no_evidence_or_references():
    result = context_builder.build_evidence_context([])
    assert json.loads(result["context"]) == []
    assert result["references"] == []


def test_json_preserves_original_text_and_unicode():
    text = 'PTO制度\n"提前通知" 与反斜杠 \\ 保留原文。'
    result = context_builder.build_evidence_context([{**CHUNKS[0], "content": text}])
    assert json.loads(result["context"])[0]["content"] == text
    assert result["references"][0]["content"] == [text]
