"""Audit citation identifiers and known marker formats, without judging factual support."""

import re
def audit_citations(
    answer_text: str,
    references: list[dict],
) -> dict:
    pattern = r"\[(?:reference_id:\s*)?([0-9]+)\]"
    known_ids = {ref["reference_id"] for ref in references}

    cited_ids = []
    nonstandard_markers = []

    for match in re.finditer(pattern, answer_text, re.IGNORECASE):
        identifier = match.group(1)

        if identifier not in cited_ids:
            cited_ids.append(identifier)

        if match.group(0) != f"[{identifier}]":
            nonstandard_markers.append(match.group(0))

    unknown_ids = [
        identifier
        for identifier in cited_ids
        if identifier not in known_ids
    ]

    return {
        "cited_ids": cited_ids,
        "unknown_ids": unknown_ids,
        "nonstandard_markers": nonstandard_markers,
        "has_citations": bool(cited_ids),
        "ids_valid": not unknown_ids,
        "format_valid": not nonstandard_markers,
    }