import re

import pytest

from app.review_units import split_answer_paragraphs


def test_blank_line_splits_with_original_character_offsets():
    text = "需要经理协调。[1]\n\n如影响关键期限，经理可能要求调整。[1]"
    first, second = text.split("\n\n")
    assert split_answer_paragraphs(text) == [
        {"unit_id": 1, "start": 0, "end": len(first), "text": first},
        {"unit_id": 2, "start": len(first) + 2, "end": len(text), "text": second},
    ]


def test_single_newlines_keep_conditions_and_citations_together():
    text = "可以申请。\n条件：需经理协调。\n例外：如影响期限，可能需改日期。\n[1]"
    assert split_answer_paragraphs(text) == [
        {"unit_id": 1, "start": 0, "end": len(text), "text": text}]


def test_punctuation_does_not_split_sentences_or_numeric_amounts():
    text = "费用$1,000.01，需经理与VP审批。是否符合资格？还需核实！[1]"
    assert split_answer_paragraphs(text)[0]["text"] == text
    assert len(split_answer_paragraphs(text)) == 1


def test_crlf_blank_line_with_spaces_is_supported():
    text = "第一段[1]\r\n \t\r\n第二段[2]"
    units = split_answer_paragraphs(text)
    assert [u["text"] for u in units] == ["第一段[1]", "第二段[2]"]
    assert all(text[u["start"]:u["end"]] == u["text"] for u in units)


def test_only_outer_whitespace_is_removed():
    text = " \t\n第一段  内部空格\n  缩进续行 [1]  \n\n\n  第二段 [2] \n "
    units = split_answer_paragraphs(text)
    assert [u["text"] for u in units] == ["第一段  内部空格\n  缩进续行 [1]", "第二段 [2]"]
    assert all(text[u["start"]:u["end"]] == u["text"] for u in units)


def test_repeated_paragraphs_have_distinct_original_positions():
    text = "同一句[1]\n\n同一句[1]"
    units = split_answer_paragraphs(text)
    assert len(units) == 2
    assert units[0]["text"] == units[1]["text"]
    assert units[1]["start"] == len("同一句[1]\n\n")


def test_headings_and_list_blocks_are_not_silently_discarded():
    text = "## 适用条件\n\n- 必须全职 [1]\n- 不处于休假状态 [1]\n\n补充说明：\n\n需按当地要求提供证明 [2]"
    units = split_answer_paragraphs(text)
    assert [u["text"] for u in units] == [
        "## 适用条件", "- 必须全职 [1]\n- 不处于休假状态 [1]",
        "补充说明：", "需按当地要求提供证明 [2]",
    ]


def test_unicode_offsets_are_characters_not_utf8_byte_positions():
    text = "资格✅[1]\n\n说明：需要证明。"
    units = split_answer_paragraphs(text)
    assert units[1]["start"] == len("资格✅[1]\n\n")
    assert text[units[1]["start"]:units[1]["end"]] == "说明：需要证明。"


@pytest.mark.parametrize("text", ["", "  \t\r\n\n", "\n\n\n\n"])
def test_blank_input_returns_no_blocks(text):
    assert split_answer_paragraphs(text) == []


@pytest.mark.parametrize("text", [None, 123, [], {}])
def test_non_string_input_is_rejected(text):
    with pytest.raises(ValueError):
        split_answer_paragraphs(text)


def test_all_non_whitespace_characters_are_preserved_in_order():
    text = "\n## 条件\n\n\n仅限经理。[2]\n\n除非符合例外。\n续行[1]\n\n结尾。"
    units = split_answer_paragraphs(text)
    assert re.sub(r"\s", "", "".join(u["text"] for u in units)) == re.sub(r"\s", "", text)
    assert [u["unit_id"] for u in units] == list(range(1, len(units) + 1))
    assert all(set(u) == {"unit_id", "start", "end", "text"} for u in units)
    assert all(text[u["start"]:u["end"]] == u["text"] for u in units)
    assert all(a["end"] <= b["start"] for a, b in zip(units, units[1:]))
