"""Bind a local review record to validated snapshot content, not a file name."""
import hashlib
import hmac
import json
from pathlib import Path

from .public_example_schemas import PublicExampleDraft


def payload_digest(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def load_reviewed_draft(path: Path) -> tuple[dict, str]:
    payload = PublicExampleDraft.model_validate_json(path.read_text(encoding='utf-8')).model_dump(mode='json')
    review = json.loads(path.with_suffix('.review.json').read_text(encoding='utf-8'))
    digest = payload_digest(payload)
    if (
        not isinstance(review, dict)
        or review.get('review_status') != 'approved'
        or not isinstance(review.get('payload_sha256'), str)
        or not hmac.compare_digest(review['payload_sha256'], digest)
    ):
        raise ValueError('Content does not match its approval record.')
    return payload, digest
