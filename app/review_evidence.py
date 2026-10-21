"""Map target citation IDs to saved evidence, without judging factual support."""

from copy import deepcopy

from .citation_audit import audit_citations


def select_cited_references(target_text: str, references: list[dict]) -> dict:
    by_id = {ref["reference_id"]: ref for ref in references}
    if len(by_id) != len(references):
        raise ValueError("Duplicate reference IDs")
    audit = audit_citations(target_text, references)
    if not audit["has_citations"] or not audit["ids_valid"]:
        raise ValueError("Target must have known citation IDs")
    return {
        "references": deepcopy([by_id[identifier] for identifier in audit["cited_ids"]]),
        "citation_audit": audit,
        "selection_policy": "all_saved_chunks_of_target_cited_references",
    }
