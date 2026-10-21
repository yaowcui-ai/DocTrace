import re
from copy import deepcopy

from app.review_units import build_item_review_windows, split_answer_paragraphs


def test_shared_intro_and_each_top_level_item_have_separate_targets():
    text = "仅限经理：\n- 可申请Coaching。[1]\n- 仍需批准。[2]"
    windows = build_item_review_windows(text, neighbor_count=1)
    assert [w["target"]["text"] for w in windows] == ["仅限经理：", "- 可申请Coaching。[1]", "- 仍需批准。[2]"]
    assert [w["target_kind"] for w in windows] == ["intro", "list_item", "list_item"]
    assert [w["target"]["item_id"] for w in windows] == [1, 2, 3]
    assert windows[0]["shared_intro"] is None
    for w in windows[1:]:
        assert w["shared_intro"]["text"] == "仅限经理："
        assert w["parent_paragraph"]["text"] == text


def test_parent_context_keeps_conditions_in_sibling_items():
    text = "- 只有经理符合资格。[1]\n- 可以申请。[1]"
    windows = build_item_review_windows(text, neighbor_count=0)
    assert len(windows) == 2
    assert "只有经理符合资格" in windows[1]["parent_paragraph"]["text"]
    assert windows[1]["shared_intro"] is None


def test_numbered_items_split_without_splitting_nested_continuations():
    text = "1. 经理协调。[1]\n   - 关键期限受影响可调整。\n   续行条件。\n2) 需提前通知。[2]"
    windows = build_item_review_windows(text, neighbor_count=0)
    assert len(windows) == 2
    assert "关键期限受影响可调整" in windows[0]["target"]["text"]
    assert "续行条件。" in windows[0]["target"]["text"]
    assert windows[1]["target"]["text"] == "2) 需提前通知。[2]"


def test_original_spans_parent_and_neighbor_context_are_preserved():
    text = "前提✅。[1]\n\n补充说明：\r\n- 第一项。[2]\r\n- 第二项。[3]\n\n后续例外。[4]"
    blocks = split_answer_paragraphs(text)
    windows = build_item_review_windows(text, neighbor_count=1)
    middle = [w for w in windows if w["target"]["unit_id"] == 2]
    assert len(middle) == 3
    for w in middle:
        assert w["context_before"] == [blocks[0]]
        assert w["context_after"] == [blocks[2]]
    for w in windows:
        spans = [w["target"], w["parent_paragraph"], *w["context_before"], *w["context_after"]]
        if w["shared_intro"] is not None: spans.append(w["shared_intro"])
        for span in spans:
            assert text[span["start"]:span["end"]] == span["text"]
    targets = "".join(w["target"]["text"] for w in windows)
    assert re.sub(r"\s", "", targets) == re.sub(r"\s", "", text)


def test_plain_paragraph_and_heading_are_retained_without_semantic_classification():
    text = "**标题**\n\n费用是$1,000.01，不是列表。"
    windows = build_item_review_windows(text, neighbor_count=1)
    assert len(windows) == 2
    assert all(w["target_kind"] == "paragraph" for w in windows)
    assert all(w["target"]["item_id"] == 1 for w in windows)


def test_fenced_answer_conservatively_disables_list_splitting():
    text = "```text\n\n- 代码里的文本\n- 不是政策建议\n\n```\n\n- 其他文本也保守保留"
    windows = build_item_review_windows(text, neighbor_count=1)
    assert [w["target"]["text"] for w in windows] == [b["text"] for b in split_answer_paragraphs(text)]
    assert all(w["target_kind"] == "paragraph" for w in windows)


def test_windows_have_independent_parent_intro_and_target_dicts():
    windows = build_item_review_windows("前提：\n- 甲。[1]\n- 乙。[1]", neighbor_count=1)
    before = deepcopy(windows)
    windows[1]["shared_intro"]["text"] = "changed"
    windows[1]["parent_paragraph"]["text"] = "changed"
    windows[1]["target"]["text"] = "changed"
    assert windows[0] == before[0]
    assert windows[2] == before[2]


def test_empty_answer_stays_empty():
    assert build_item_review_windows("", neighbor_count=1) == []
