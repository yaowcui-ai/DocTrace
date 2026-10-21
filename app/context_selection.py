"""Choose whole ranked chunks within an explicit character budget and record decisions."""
import math

def select_context(
    ranked_chunks: list[dict],
    *,
    max_chars: int,
    min_score: float | None = None,
) -> dict:
    if type(max_chars) is not int or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    if min_score is not None:
        if type(min_score) not in (int, float) or not math.isfinite(min_score):
            raise ValueError("min_score must be a finite number")
    selected = []
    selected_ids = set()
    characters = 0
    decisions = []

    for position, chunk in enumerate(ranked_chunks, start=1):
        chunk_id = chunk["chunk_id"]
        size = len(chunk["content"])
        score = chunk.get("rerank_score")

        if min_score is not None:
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError("Invalid rerank score")
        if chunk_id in selected_ids:
            reason = "duplicate_id"
        elif min_score is not None and score < min_score:
            reason = "below_min_score"
        elif characters + size > max_chars:
            reason = "budget_exceeded"
        else:
            reason = "selected"
            selected.append(dict(chunk))
            selected_ids.add(chunk_id)
            characters += size

        decisions.append({
            "position": position,
            "chunk_id": chunk_id,
            "characters": size,
            "reason": reason,
        })

    return {
        "selected_chunks": selected,
        "characters": characters,
        "decisions": decisions,
    }