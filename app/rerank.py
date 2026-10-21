"""Map rerank scores back to original evidence without losing source metadata."""

import math
def map_rerank_results(
    chunks: list[dict],
    results: list[dict],
) -> list[dict]:
    if len(results) != len(chunks):
        raise ValueError("Incomplete rerank results")

    seen = set()
    mapped = []

    for item in results:
        if not isinstance(item, dict):
            raise ValueError("Invalid rerank item")

        index = item.get("index")
        score = item.get("relevance_score")

        if type(index) is not int:
            raise ValueError("Invalid rerank index")

        if not 0 <= index < len(chunks):
            raise ValueError("Rerank index out of range")

        if index in seen:
            raise ValueError("Duplicate rerank index")

        if type(score) not in (int, float):
            raise ValueError("Invalid rerank score")

        if not math.isfinite(score):
            raise ValueError("Non-finite rerank score")

        seen.add(index)
        mapped.append({
            **chunks[index],
            "rerank_score": float(score),
            "original_position": index + 1,
        })

    return mapped