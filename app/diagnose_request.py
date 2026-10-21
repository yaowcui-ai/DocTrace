"""Read local request events, optionally comparing with a read-only DB query."""
import argparse
import json
from pathlib import Path
from uuid import UUID

from .logging_config import DEFAULT_LOG_DIR

LOG_FIELDS = {
    'timestamp', 'event', 'request_id', 'attempt_id', 'stage', 'duration_ms',
    'http_status', 'error_type', 'chunk_count', 'strategy', 'degraded', 'outcome',
}


def read_events(log_dir: Path, *, request_id=None, attempt_id=None) -> dict:
    events = []
    skipped = 0
    unreadable = 0
    def rotation_order(path):
        suffix = path.name.removeprefix('doctrace-qa.jsonl')
        return int(suffix[1:]) if suffix.startswith('.') and suffix[1:].isdigit() else 0

    # Stable ordering preserves original event order when timestamps tie.
    for path in sorted(Path(log_dir).glob('doctrace-qa.jsonl*'), key=rotation_order, reverse=True):
        try:
            with path.open(encoding='utf-8', errors='replace') as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict) or not isinstance(row.get('timestamp'), str) or not isinstance(row.get('event'), str):
                            skipped += 1
                            continue
                    except (ValueError, TypeError):
                        skipped += 1
                        continue
                    if attempt_id is not None and row.get('attempt_id') != attempt_id:
                        continue
                    events.append({key:value for key,value in row.items() if key in LOG_FIELDS})
        except OSError:
            unreadable += 1
    events.sort(key=lambda row: row['timestamp'])
    if request_id is not None:
        attempts = {row['attempt_id'] for row in events if row.get('request_id') == request_id and row.get('attempt_id')}
        events = [row for row in events if row.get('request_id') == request_id
            or (row.get('request_id') is None and row.get('attempt_id') in attempts)]
    return {'events':events, 'skipped_lines':skipped, 'unreadable_files':unreadable}


def build_diagnosis(events: list[dict], database_record: dict | None = None) -> dict:
    groups = {}
    for row in events:
        groups.setdefault(row.get('attempt_id'), []).append(row)
    attempts = []
    for attempt_id, rows in groups.items():
        attempts.append({
            'attempt_id':attempt_id,
            'first_seen':rows[0]['timestamp'], 'last_seen':rows[-1]['timestamp'],
            'last_event':rows[-1]['event'],
            'last_business_stage':next((row['stage'] for row in reversed(rows) if row.get('stage') and row['stage'] != 'HTTP'), None),
            'last_http_status':next((row['http_status'] for row in reversed(rows) if row.get('http_status') is not None), None),
            'event_count':len(rows),
        })
    status = database_record.get('status') if database_record is not None else None
    classification = 'log_only' if events else 'no_log_evidence'
    if status in ('completed', 'failed'):
        classification = 'database_'+status
    elif status == 'processing':
        classification = 'incomplete_unconfirmed'
    elif status is not None:
        classification = 'unknown_database_state'
    return {
        'classification':classification, 'database_status':status,
        'attempts':attempts,
        'note':'日志仅代表最后观测到的事件；缺少结束日志或数据库为 processing，均不能证明任务仍在运行或已经停止。',
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--request-id', type=UUID)
    identity.add_argument('--attempt-id', type=UUID)
    parser.add_argument('--log-dir', type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument('--database', action='store_true', help='Also read current MySQL record state')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    request_id = str(args.request_id) if args.request_id else None
    attempt_id = str(args.attempt_id) if args.attempt_id else None
    observed = read_events(args.log_dir, request_id=request_id, attempt_id=attempt_id)
    database_check = {'status':'not_requested'}
    row = None
    if args.database:
        if request_id is None:
            ids = {item['request_id'] for item in observed['events'] if item.get('request_id')}
            request_id = next(iter(ids)) if len(ids) == 1 else None
        if request_id is None:
            database_check = {'status':'record_id_unavailable'}
        else:
            from .database import create_db_engine
            from .database_config import load_database_settings
            from .qa_records import get_qa_record
            engine = None
            try:
                engine = create_db_engine(load_database_settings())
                row = get_qa_record(engine, request_id)
                database_check = {'status':'checked', 'record_present':row is not None}
                if row is not None:
                    database_check['record_status'] = row.get('status')
                    database_check.update({key:row.get(key) for key in ('http_status','error_stage','updated_at','duration_ms')})
            except Exception as error:
                database_check = {'status':'unavailable', 'error_type':type(error).__name__}
            finally:
                if engine is not None:
                    engine.dispose()
    result = {'request_id':request_id, 'attempt_id':attempt_id,
        **observed, **build_diagnosis(observed['events'], row), 'database_check':database_check}
    output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding='utf-8')
    print(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
