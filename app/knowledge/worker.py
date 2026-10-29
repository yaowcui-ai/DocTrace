"""One durable, sequential worker. It never retries an unconfirmed mutation."""
import argparse
from uuid import uuid4

from .repository import KnowledgeRepository
from .upstream import ManagedClient, ManagedFailure, load_managed_settings


def run_once(repo, client):
    owner = str(uuid4())
    if not repo.acquire(owner):
        return False
    try:
        task = repo.claim()
        if not task:
            return False
        version = repo.job_version(task)
        polling = task['previous_state'] in {'indexing', 'deleting'}
        try:
            if polling:
                rows = client.poll(version)
                if task['kind'] == 'delete':
                    if not any(row.get('id') == version['upstream_id'] for row in rows):
                        repo.complete_delete(task)
                    else:
                        repo.set_job(task, 'deleting')
                else:
                    matches = [r for r in rows if r.get('file_path') == client.file_source(version)]
                    if len(matches) == 1 and isinstance(matches[0].get('id'), str) and 1 <= len(matches[0]['id']) <= 255:
                        row = matches[0]
                        if row.get('status') == 'processed':
                            repo.complete_index(task['task_id'], row['id'])
                        elif row.get('status') == 'failed':
                            repo.set_job(task, 'failed', failure='upstream_processing_failed', upstream_id=row['id'])
                        else:
                            repo.set_job(task, 'indexing')
                    else:
                        repo.set_job(task, 'indexing', failure='upstream_document_unconfirmed')
            elif task['kind'] == 'index':
                # A failed processed document can retain partial vectors. Reconciliation
                # must delete it first; automatically resubmitting would risk conflict.
                if version['upstream_id']:
                    repo.set_job(task, 'failed', failure='upstream_reconciliation_required')
                else:
                    track = client.submit(version)
                    repo.set_job(task, 'indexing', track_id=track)
            else:
                if not version['upstream_id'] or not version['track_id']:
                    repo.set_job(task, 'failed', failure='upstream_reconciliation_required')
                else:
                    client.delete(version)
                    repo.set_job(task, 'deleting')
        except ManagedFailure as error:
            if polling:
                repo.set_job(task, task['previous_state'], failure=error.code)
            elif error.uncertain:
                repo.set_job(task, 'submission_unknown', failure=error.code)
            else:
                repo.set_job(task, 'failed', failure=error.code)
        return True
    finally:
        repo.release(owner)


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description='Process explicitly queued admin jobs; may invoke indexing APIs.')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--serve', action='store_true')
    parser.add_argument('--poll-seconds', type=int, choices=range(2, 31), default=5)
    return parser.parse_args(argv)


def run_service(repo, client, stopped, *, poll_seconds=5):
    steps = 0
    while not stopped.is_set():
        if run_once(repo, client):
            steps += 1
        stopped.wait(poll_seconds)
    return steps


def main(argv=None):
    args = parse_arguments(argv)
    from app.database import create_db_engine
    from app.database_config import load_database_settings
    from app.config import ConfigurationError
    from sqlalchemy.exc import SQLAlchemyError
    try:
        settings = load_managed_settings()
        engine = create_db_engine(load_database_settings())
        try:
            if args.serve:
                import signal
                from threading import Event
                stopped = Event()
                signal.signal(signal.SIGTERM, lambda *_: stopped.set())
                signal.signal(signal.SIGINT, lambda *_: stopped.set())
                print('Managed worker ready; only explicitly queued tasks are processed.', flush=True)
                run_service(KnowledgeRepository(engine), ManagedClient(settings), stopped, poll_seconds=args.poll_seconds)
            else:
                changed = run_once(KnowledgeRepository(engine), ManagedClient(settings))
                print('Worker step completed.' if changed else 'No claimable work or another worker holds the lock.')
        finally:
            engine.dispose()
    except (ConfigurationError, SQLAlchemyError):
        print('Managed worker configuration or persistence unavailable; no credentials are displayed.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
