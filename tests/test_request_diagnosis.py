"""Read-only diagnostics over bounded local logs; no provider calls."""
from importlib import import_module
import json
from pathlib import Path

import pytest


def module():
    assert (Path(__file__).parents[1] / 'app/diagnose_request.py').exists(), 'Create app/diagnose_request.py first'
    return import_module('app.diagnose_request')


def event(second, name='stage_started', record='record', attempt='attempt', **extra):
    return {'timestamp':f'2026-10-17T00:00:{second:02d}+00:00', 'event':name,
        'request_id':record, 'attempt_id':attempt, **extra}


def test_reads_rotated_logs_filters_identity_and_ignores_malformed_lines(tmp_path):
    m = module()
    (tmp_path/'doctrace-qa.jsonl.1').write_text(json.dumps(event(1))+'\nbad-json\n[]\n', encoding='utf-8')
    (tmp_path/'doctrace-qa.jsonl').write_text('\n'.join(json.dumps(row) for row in [event(3), event(2), event(4, record='other')]), encoding='utf-8')
    report = m.read_events(tmp_path, request_id='record')
    assert [row['timestamp'] for row in report['events']] == [event(n)['timestamp'] for n in [1,2,3]]
    assert report['skipped_lines'] == 2


def test_attempt_lookup_includes_events_before_record_creation(tmp_path):
    m = module()
    rows = [event(1, record=None), event(2), event(3, attempt='other')]
    (tmp_path/'doctrace-qa.jsonl').write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    assert m.read_events(tmp_path, attempt_id='attempt')['events'] == rows[:2]


def test_equal_timestamps_preserve_order_across_rotation(tmp_path):
    m = module()
    (tmp_path/'doctrace-qa.jsonl.1').write_text(json.dumps(event(1, name='stage_started')), encoding='utf-8')
    (tmp_path/'doctrace-qa.jsonl').write_text(json.dumps(event(1, name='stage_completed')), encoding='utf-8')
    assert [row['event'] for row in m.read_events(tmp_path, request_id='record')['events']] == ['stage_started','stage_completed']


def test_record_lookup_includes_its_attempts_precreation_events(tmp_path):
    m = module()
    rows = [event(1, name='http_received', record=None), event(2, name='record_created'),
        event(3, name='http_received', record=None, attempt='unrelated')]
    (tmp_path/'doctrace-qa.jsonl').write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
    assert m.read_events(tmp_path, request_id='record')['events'] == rows[:2]


def test_unknown_directory_has_no_log_evidence(tmp_path):
    m = module()
    assert m.read_events(tmp_path/'missing', request_id='record')['events'] == []
    assert m.build_diagnosis([])['classification'] == 'no_log_evidence'


def test_diagnostic_output_uses_allowlisted_log_fields(tmp_path):
    m = module()
    row = event(1, question='private-question', api_key='private-key', exception='private-exception')
    (tmp_path/'doctrace-qa.jsonl').write_text(json.dumps(row), encoding='utf-8')
    result = json.dumps(m.read_events(tmp_path, request_id='record'))
    assert not any(value in result for value in ['private-question','private-key','private-exception'])


def test_processing_is_unconfirmed_not_assumed_running_or_failed():
    m = module()
    report = m.build_diagnosis([event(1, stage='回答模型')], {'status':'processing'})
    assert report['classification'] == 'incomplete_unconfirmed'
    assert report['attempts'][0]['last_business_stage'] == '回答模型'


@pytest.mark.parametrize('status', ['completed', 'failed'])
def test_database_terminal_state_is_reported_without_exposing_answer(status):
    m = module()
    report = m.build_diagnosis([event(1)], {'status':status, 'answer':'private-answer', 'question':'private-question'})
    assert report['classification'] == 'database_'+status
    assert not any(value in json.dumps(report) for value in ['private-answer','private-question'])


def test_http_end_does_not_hide_last_business_stage_or_merge_attempts():
    m = module()
    logs = [event(1, stage='回答模型'), event(2, name='http_completed', stage='HTTP'),
        event(3, name='record_reused', attempt='retry'), event(4, name='replay_completed', attempt='retry')]
    report = m.build_diagnosis(logs)
    assert report['classification'] == 'log_only'
    assert len(report['attempts']) == 2
    assert report['attempts'][0]['last_business_stage'] == '回答模型'
    assert report['attempts'][1]['last_event'] == 'replay_completed'


def test_cli_database_lookup_is_read_only_and_output_excludes_payload(tmp_path, monkeypatch, capsys):
    m = module()
    from app import database, database_config, qa_records
    from unittest.mock import Mock
    record_id = '3d00a758-9cbe-4b50-96d4-9bc1e07ab373'
    engine = Mock()
    monkeypatch.setattr(database_config, 'load_database_settings', lambda: object())
    monkeypatch.setattr(database, 'create_db_engine', lambda settings: engine)
    monkeypatch.setattr(qa_records, 'get_qa_record', lambda db, key: {
        'status':'processing', 'answer':'private-answer', 'question':'private-question'})
    assert m.main(['--request-id',record_id,'--database','--log-dir',str(tmp_path)]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result['classification'] == 'incomplete_unconfirmed'
    assert result['database_check']['status'] == 'checked'
    assert result['database_check']['record_status'] == 'processing'
    assert 'private-answer' not in output and 'private-question' not in output
    engine.begin.assert_not_called()
    engine.dispose.assert_called_once()


def test_cli_database_failure_is_reported_without_raw_error(tmp_path, monkeypatch, capsys):
    m = module()
    from app import database_config
    def fail():
        raise RuntimeError('private-connection-secret')
    monkeypatch.setattr(database_config, 'load_database_settings', fail)
    m.main(['--request-id','3d00a758-9cbe-4b50-96d4-9bc1e07ab373','--database','--log-dir',str(tmp_path)])
    output = capsys.readouterr().out
    assert json.loads(output)['database_check'] == {'status':'unavailable','error_type':'RuntimeError'}
    assert 'private-connection-secret' not in output
