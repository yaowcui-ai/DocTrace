"""Explicit local publication after matching the locked DB snapshot to its approval."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import column, select, table
from sqlalchemy.exc import SQLAlchemyError

from .config import ConfigurationError
from .database import create_db_engine
from .database_config import load_database_settings
from .public_example_review import load_reviewed_draft, payload_digest
from .public_example_schemas import PublicExampleDraft
from .public_examples import publish_public_example


class _CurrentTransaction:
    """Let the existing update function participate in the caller's locked transaction."""
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        # The outer engine.begin owns the actual commit/rollback.
        yield self.connection


def checked_publication(engine, identifier: str, digest: str, *, apply=False):
    examples = table('public_examples', *(column(name) for name in (
        'example_id', 'question', 'answer', 'references_json', 'corpus_id', 'status',
    )))
    statement = select(examples).where(examples.c.example_id == identifier).with_for_update()
    # MySQL locks this row from validation until commit; SQLite omits FOR UPDATE.
    with engine.begin() as connection:
        row = connection.execute(statement).mappings().first()
        if row is None:
            raise ValueError('Imported snapshot no longer exists.')
        data = {name: row[name] for name in ('question', 'answer', 'corpus_id')}
        data['references'] = json.loads(row['references_json'])
        snapshot = PublicExampleDraft.model_validate(data).model_dump(mode='json')
        if payload_digest(snapshot) != digest:
            raise ValueError('Database snapshot changed after review.')
        if row['status'] == 'published':
            result = 'already_published'
        elif row['status'] != 'draft':
            raise ValueError('Only drafts may be published.')
        elif not apply:
            result = 'ready'
        else:
            if not publish_public_example(_CurrentTransaction(connection), identifier):
                raise ValueError('Draft transition did not occur.')
            result = 'published'
    # Report success only after the outer transaction has committed.
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--publish', action='store_true', help='Explicitly publish; default only validates')
    args = parser.parse_args(argv)
    path = args.file.resolve()
    try:
        _, digest = load_reviewed_draft(path)
        receipt = json.loads(path.with_suffix('.import.json').read_text(encoding='utf-8'))
        if not isinstance(receipt, dict) or (
            receipt.get('kind') != 'public_example_draft_import'
            or receipt.get('status') != 'created'
            or receipt.get('payload_sha256') != digest
        ):
            raise ValueError('Import receipt does not confirm this approved content.')
        identifier = str(UUID(receipt['example_id']))
    except (OSError, ValueError, TypeError, KeyError):
        print('Review or import record is missing/invalid, or content changed. No publication attempted.')
        return 1

    engine = None
    try:
        engine = create_db_engine(load_database_settings())
        result = checked_publication(engine, identifier, digest, apply=args.publish)
    except ConfigurationError:
        print('Database configuration invalid. No publication attempted.')
        return 1
    except (ValueError, TypeError):
        print('Publication rejected: snapshot missing, changed, invalid, or not a draft. Review it before publishing.')
        return 1
    except SQLAlchemyError:
        print('Publication was not confirmed. Check the database using preview mode before another attempt.')
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    print('Validation passed')
    print('Example ID:', identifier)
    print({
        'ready': 'Ready to publish; preview only, database unchanged. Add --publish to publish.',
        'published': 'Published',
        'already_published': 'Already published; content and publication time unchanged.',
    }[result])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
