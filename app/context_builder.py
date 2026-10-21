"""Build answer evidence and matching source references from selected chunks only."""

import json
def build_evidence_context(selected_chunks: list[dict]) -> dict:
    references = []
    references_by_path = {}
    evidence = []

    for chunk in selected_chunks:
        file_path = chunk["file_path"]

        if file_path not in references_by_path:
            reference = {
                "reference_id": str(len(references) + 1),
                "file_path": file_path,
                "content": [],
            }
            references.append(reference)
            references_by_path[file_path] = reference

        reference = references_by_path[file_path]
        reference["content"].append(chunk["content"])

        evidence.append({
            "reference_id": reference["reference_id"],
            "file_path": file_path,
            "chunk_id": chunk["chunk_id"],
            "content": chunk["content"],
        })

    return {
        "context": json.dumps(evidence, ensure_ascii=False),
        "references": references,
    }