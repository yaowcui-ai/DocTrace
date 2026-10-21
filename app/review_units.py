"""Traceable paragraph blocks for a future offline review pipeline.

A paragraph block is not necessarily an independent policy claim. Titles and
context are retained as blocks; do not review blocks in isolation yet.
"""

import re
from copy import deepcopy


# A blank line, including a blank line containing spaces/tabs; supports CRLF.
PARAGRAPH_BREAK = re.compile(r"\r?\n[ \t]*\r?\n")


def split_answer_paragraphs(answer_text: str) -> list[dict]:
    if not isinstance(answer_text, str):
        raise ValueError("Answer must be a string.")

    units = []
    cursor = 0

    # 保存所有空行分隔符的位置。
    boundaries = [
        (match.start(), match.end())
        for match in PARAGRAPH_BREAK.finditer(answer_text)
    ]

    # 最后增加文本末尾，确保最后一段也被处理。
    boundaries.append((len(answer_text), len(answer_text)))

    for stop, next_cursor in boundaries:
        raw = answer_text[cursor:stop]

        if raw.strip():
            # 跳过外侧空白，同时保留在原答案中的真实位置。
            start = cursor + len(raw) - len(raw.lstrip())
            end = cursor + len(raw.rstrip())

            units.append({
                "unit_id": len(units) + 1,
                "start": start,
                "end": end,
                "text": answer_text[start:end],
            })

        cursor = next_cursor

    return units


def build_review_windows(
    answer_text: str,
    *,
    neighbor_count: int,
) -> list[dict]:
    if type(neighbor_count) is not int or neighbor_count < 0:
        raise ValueError("Neighbor count must be a nonnegative integer.")

    paragraphs = split_answer_paragraphs(answer_text)
    windows = []

    for index, paragraph in enumerate(paragraphs):
        left = max(0, index - neighbor_count)
        right = min(len(paragraphs), index + neighbor_count + 1)

        window = {
            "target": paragraph,
            "context_before": paragraphs[left:index],
            "context_after": paragraphs[index + 1:right],
        }

        windows.append(deepcopy(window))

    return windows


TOP_LEVEL_ITEM = re.compile(r"(?m)^(?:[-*+]|\d+[.)])[ \t]+")
CODE_FENCE = re.compile(r"(?m)^[ \t]*(?:`{3,}|~{3,})")


def _original_subspan(paragraph: dict, start: int, end: int) -> dict | None:
    """Reuse the original-position calculation for a span inside one paragraph."""
    raw = paragraph["text"][start:end]
    if not raw.strip():
        return None
    left = start + len(raw) - len(raw.lstrip())
    right = start + len(raw.rstrip())
    return {"unit_id": paragraph["unit_id"],
            "start": paragraph["start"] + left, "end": paragraph["start"] + right,
            "text": paragraph["text"][left:right]}


def build_item_review_windows(answer_text: str, *, neighbor_count: int) -> list[dict]:
    """Refine top-level lists while retaining all original paragraph context.

    This is structural splitting, not semantic claim extraction. The intro also
    remains a target, so substantive text is never silently discarded. Every
    list target retains its full parent paragraph, preserving sibling conditions
    as context, plus the original neighboring paragraphs. Fenced answers disable
    list splitting conservatively; this is not a complete Markdown parser.
    """
    paragraphs = build_review_windows(answer_text, neighbor_count=neighbor_count)
    can_split = CODE_FENCE.search(answer_text) is None
    results = []
    for window in paragraphs:
        parent = window["target"]
        text = parent["text"]
        starts = [m.start() for m in TOP_LEVEL_ITEM.finditer(text)] if can_split else []
        intro = None
        if starts:
            intro = _original_subspan(parent, 0, starts[0])
            ranges = [(0, starts[0], "intro")] if intro is not None else []
            ranges += [(start, stop, "list_item")
                       for start, stop in zip(starts, starts[1:] + [len(text)])]
        else:
            ranges = [(0, len(text), "paragraph")]
        for item_id, (start, end, kind) in enumerate(ranges, 1):
            target = _original_subspan(parent, start, end)
            target["item_id"] = item_id
            results.append(deepcopy({
                "target": target, "target_kind": kind,
                "shared_intro": intro if kind == "list_item" else None,
                "parent_paragraph": parent,
                "context_before": window["context_before"],
                "context_after": window["context_after"],
            }))
    return results
