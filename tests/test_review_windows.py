from copy import deepcopy

import pytest

from app.review_units import build_review_windows, split_answer_paragraphs


TEXT = "仅限经理级别及以上：\n\n可以申请Coaching。[1]\n\n仍需满足其他资格条件。[1]"


def test_target_keeps_qualification_before_it_and_caveat_after_it():
    blocks = split_answer_paragraphs(TEXT)
    windows = build_review_windows(TEXT, neighbor_count=1)
    assert windows[1] == {
        "target": blocks[1], "context_before": [blocks[0]], "context_after": [blocks[2]],
    }
    assert windows[1]["target"]["text"] == "可以申请Coaching。[1]"


def test_first_and_last_windows_do_not_wrap_around():
    blocks = split_answer_paragraphs(TEXT)
    windows = build_review_windows(TEXT, neighbor_count=1)
    assert windows[0]["context_before"] == []
    assert windows[0]["context_after"] == [blocks[1]]
    assert windows[-1]["context_before"] == [blocks[-2]]
    assert windows[-1]["context_after"] == []


def test_larger_context_preserves_original_order_and_excludes_target():
    text = "段落甲\n\n段落乙\n\n段落丙\n\n段落丁\n\n段落戊"
    blocks = split_answer_paragraphs(text)
    middle = build_review_windows(text, neighbor_count=2)[2]
    assert middle == {"target": blocks[2], "context_before": blocks[:2], "context_after": blocks[3:]}


def test_zero_neighbors_keeps_only_target_without_changing_split():
    blocks = split_answer_paragraphs(TEXT)
    windows = build_review_windows(TEXT, neighbor_count=0)
    assert windows == [{"target": block, "context_before": [], "context_after": []} for block in blocks]


def test_large_neighbor_count_is_clamped_to_available_paragraphs():
    blocks = split_answer_paragraphs(TEXT)
    windows = build_review_windows(TEXT, neighbor_count=100)
    assert windows[1] == {"target": blocks[1], "context_before": blocks[:1], "context_after": blocks[2:]}


def test_all_targets_and_context_are_exact_original_spans():
    text = "\n**标题**\r\n \r\n第一项[1]\n  单行续写条件\n\n最后一段。[2]\n"
    windows = build_review_windows(text, neighbor_count=1)
    assert [w["target"] for w in windows] == split_answer_paragraphs(text)
    for window in windows:
        assert set(window) == {"target", "context_before", "context_after"}
        for block in [window["target"], *window["context_before"], *window["context_after"]]:
            assert text[block["start"]:block["end"]] == block["text"]


def test_windows_do_not_share_mutable_blocks():
    windows = build_review_windows(TEXT, neighbor_count=1)
    before = deepcopy(windows)
    windows[0]["context_after"][0]["text"] = "changed"
    assert windows[1] == before[1]
    windows[0]["target"]["text"] = "changed target"
    assert windows[1] == before[1]


def test_empty_answer_has_no_windows():
    assert build_review_windows("  \n\n", neighbor_count=1) == []


@pytest.mark.parametrize("count", [-1, True, False, 1.0, "1", None])
def test_invalid_neighbor_count_is_rejected_even_for_empty_answer(count):
    with pytest.raises(ValueError):
        build_review_windows("", neighbor_count=count)
