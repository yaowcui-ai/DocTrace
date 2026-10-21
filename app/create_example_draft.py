"""Validate an approved snapshot, or explicitly import it as an unpublished draft."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from sqlalchemy.exc import SQLAlchemyError

from .config import ConfigurationError
from .database import create_db_engine
from .database_config import load_database_settings
from .public_examples import create_public_example_draft
from .public_example_review import load_reviewed_draft


def write_receipt(path: Path, record: dict, *, exclusive=False):
    value = json.dumps(record, ensure_ascii=False, indent=2) + '\n'
    if exclusive:
        with path.open('x', encoding='utf-8') as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--submit', action='store_true', help='Save as draft; this never publishes')
    args = parser.parse_args(argv)
    source = args.file.resolve()
    try:
        payload, digest = load_reviewed_draft(source)
    except (OSError, ValueError, TypeError):
        print('Draft or review record invalid/missing, or content changed after approval. No database write.')
        return 1

    print('Validation passed')
    print('Reviewed SHA256:', digest)
    if not args.submit:
        print('Preview only. No database access; add --submit to create an unpublished draft.')
        return 0

    receipt_path = source.with_suffix('.import.json')
    if receipt_path.exists():
        print('Import record already exists. Do not repeat submission; inspect the receipt and database first.')
        print('Receipt:', receipt_path)
        return 1

    engine = None
    try:
        engine = create_db_engine(load_database_settings())
        record = {
            'kind': 'public_example_draft_import',
            'status': 'submission_started',
            'payload_sha256': digest,
            'started_at_utc': datetime.now(timezone.utc).isoformat(),
            'example_id': None,
        }
        # Reserve this file's operation before insertion. A crash/error leaves a
        # marker so manual reruns cannot silently create another draft.
        write_receipt(receipt_path, record, exclusive=True)
    except (ConfigurationError, SQLAlchemyError, OSError):
        if engine is not None:
            engine.dispose()
        print('Unable to prepare submission. No insert attempted; inspect any existing import receipt.')
        return 1

    try:
        example_id = create_public_example_draft(engine, payload=payload)
    except (SQLAlchemyError, ValueError):
        print('Submission was not confirmed. Keep the receipt and inspect the database; do not retry automatically.')
        return 1
    finally:
        engine.dispose()

    print('Draft created; not published')
    print('Example ID:', example_id)
    record.update(status='created', example_id=example_id)
    try:
        write_receipt(receipt_path, record)
    except OSError:
        print('Database creation succeeded, but receipt update failed. Save the Example ID above; do not resubmit.')
        return 1
    print('Receipt:', receipt_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
