"""Exercise current API/logging code with real MySQL and an existing test row.

The in-process API uses the actual repository. Generation is explicitly blocked;
this check never starts/restarts the user's server or calls a model provider.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from . import main as api
from .database import create_db_engine
from .database_config import load_database_settings
from .diagnose_request import build_diagnosis, read_events
from .logging_config import DEFAULT_LOG_DIR
from .qa_records import get_qa_record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args(argv)
    fixture = json.loads(args.source.read_text(encoding='utf-8'))
    if fixture.get('kind') != 'integration_smoke_not_model_evaluation' or fixture.get('status') != 'passed':
        raise ValueError('A passed synthetic MySQL fixture report is required')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8]
    output = Path(__file__).resolve().parents[1]/'evaluation/runs'/(run_id+'_request_logging.json')
    report = {'kind':'in_process_api_logging_integration_not_model_evaluation', 'source':str(args.source),
        'status':'started', 'request_id':fixture['request_id'], 'probes':[]}
    engine = None
    try:
        engine = create_db_engine(load_database_settings())
        before = get_qa_record(engine, fixture['request_id'])
        assert before and before['status'] == 'completed' and before['llm_generated'] == 0
        with engine.connect() as connection:
            key_row = connection.execute(text('SELECT question, idempotency_key FROM qa_records WHERE request_id=:id'),
                {'id':fixture['request_id']}).mappings().one()
            count_before = connection.execute(text('SELECT COUNT(*) FROM qa_records')).scalar_one()
        assert key_row['idempotency_key'] == fixture['idempotency_key']
        with patch.object(api, 'run_medium_qa_pipeline', side_effect=AssertionError('Generation forbidden in logging verification')) as provider:
            with TestClient(api.app) as client:
                for name, key, question, expected in [
                    ('replay_one', fixture['idempotency_key'], before['question'], 200),
                    ('replay_two', fixture['idempotency_key'], before['question'], 200),
                    ('input_conflict', fixture['idempotency_key'], before['question']+' changed', 409),
                    ('invalid_header', 'not-a-uuid', before['question'], 422),
                ]:
                    response = client.post('/ask/optimized', headers={'Idempotency-Key':key}, json={'question':question})
                    assert response.status_code == expected
                    attempt = response.headers['X-DocTrace-Attempt-ID']
                    events = read_events(DEFAULT_LOG_DIR, attempt_id=attempt)['events']
                    assert events[0]['event'] == 'http_received'
                    assert events[-1]['event'] == 'http_completed' and events[-1]['http_status'] == expected
                    if expected == 200:
                        assert response.json()['request_id'] == fixture['request_id']
                        assert any(row['event']=='replay_completed' for row in events)
                        assert not any(row['event']=='qa_started' for row in events)
                    report['probes'].append({'name':name, 'http_status':response.status_code,
                        'attempt_id':attempt, 'event_count':len(events)})
            assert provider.call_count == 0
            report['provider_calls'] = provider.call_count
        assert get_qa_record(engine, fixture['request_id']) == before
        with engine.connect() as connection:
            count_after = connection.execute(text('SELECT COUNT(*) FROM qa_records')).scalar_one()
        assert count_before == count_after
        observed = read_events(DEFAULT_LOG_DIR, request_id=fixture['request_id'])
        report.update(status='passed', total_before=count_before, total_after=count_after,
            record_unchanged=True, diagnosis=build_diagnosis(observed['events'], before))
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__)
    finally:
        if engine is not None:
            engine.dispose()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print('Status:', report['status'])
    print('Provider calls:', report.get('provider_calls'))
    print('Report:', output)
    return 0 if report['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
