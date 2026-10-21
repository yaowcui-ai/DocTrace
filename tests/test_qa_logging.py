"""Offline JSON logging checks; no database or model requests."""
from datetime import datetime
from importlib import import_module
from io import StringIO
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_module(name):
    assert (Path(__file__).parents[1] / 'app' / (name+'.py')).exists(), 'Create app/'+name+'.py first'
    return import_module('app.'+name)


@pytest.fixture
def capture(monkeypatch):
    module = load_module('qa_logging')
    output = StringIO()
    logger = logging.Logger('offline_qa_test', level=logging.INFO)
    logger.addHandler(logging.StreamHandler(output))
    monkeypatch.setattr(module, 'logger', logger)
    return module.log_qa_event, output


def payload(output):
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_event_contains_utc_time_and_record_identity(capture):
    log, output = capture
    log('record_created', 'test-id')
    item = payload(output)
    assert item['event'] == 'record_created'
    assert item['request_id'] == 'test-id'
    moment = datetime.fromisoformat(item['timestamp'])
    assert moment.utcoffset().total_seconds() == 0


def test_stage_duration_and_http_status_are_structured_fields(capture):
    log, output = capture
    log('qa_failed', 'test-id', stage='回答模型', duration_ms=123, http_status=504)
    item = payload(output)
    assert item['stage'] == '回答模型'
    assert item['duration_ms'] == 123
    assert item['http_status'] == 504


def test_absent_optional_fields_are_not_fabricated(capture):
    log, output = capture
    log('qa_started', 'test-id')
    assert set(payload(output)) == {'timestamp', 'event', 'request_id'}


def test_failure_before_record_creation_can_have_no_record_id(capture):
    log, output = capture
    log('record_create_failed', None, stage='记录保存', http_status=503)
    assert payload(output)['request_id'] is None


def test_zero_duration_is_preserved(capture):
    log, output = capture
    log('qa_completed', 'test-id', duration_ms=0)
    assert payload(output)['duration_ms'] == 0


def test_logger_does_not_accept_arbitrary_payload_fields(capture):
    log, output = capture
    with pytest.raises(TypeError):
        log('qa_started', 'test-id', api_key='private-test-value')
    assert output.getvalue() == ''


def test_newlines_are_encoded_inside_one_json_log_entry(capture):
    log, output = capture
    log('test\nnot_another_log_entry', 'test-id')
    assert payload(output)['event'] == 'test\nnot_another_log_entry'


def test_console_setup_is_repeatable_without_duplicate_handlers(monkeypatch, tmp_path):
    config = load_module('logging_config')
    logger = logging.Logger('isolated_config')
    monkeypatch.setattr(config, 'logging', SimpleNamespace(getLogger=lambda name: logger,
        INFO=logging.INFO, StreamHandler=logging.StreamHandler, Formatter=logging.Formatter))
    config.configure_qa_logging(tmp_path)
    config.configure_qa_logging(tmp_path)
    assert len(logger.handlers) == 2
    assert logger.level == logging.INFO
    assert logger.propagate is False
    for handler in logger.handlers:
        handler.close()


def test_console_handler_preserves_json_message(monkeypatch, tmp_path):
    config = load_module('logging_config')
    logger = logging.Logger('isolated_config')
    monkeypatch.setattr(config, 'logging', SimpleNamespace(getLogger=lambda name: logger,
        INFO=logging.INFO, StreamHandler=logging.StreamHandler, Formatter=logging.Formatter))
    config.configure_qa_logging(tmp_path)
    output = StringIO()
    logger.handlers[0].setStream(output)
    logger.info('{"event":"test"}')
    assert logger.handlers[0].wait_for_idle(1)
    assert output.getvalue().strip() == '{"event":"test"}'
    assert json.loads((tmp_path / 'doctrace-qa.jsonl').read_text(encoding='utf-8')) == {'event':'test'}
    for handler in logger.handlers:
        handler.close()


def test_file_rotation_keeps_json_lines_and_bounds_backups(monkeypatch, tmp_path):
    config = load_module('logging_config')
    logger = logging.Logger('isolated_rotation')
    monkeypatch.setattr(config, 'logging', SimpleNamespace(getLogger=lambda name: logger,
        INFO=logging.INFO, StreamHandler=logging.StreamHandler, Formatter=logging.Formatter))
    config.configure_qa_logging(tmp_path)
    handler = next(item for item in logger.handlers if item.name == 'doctrace_qa_file')
    assert handler.maxBytes == 5 * 1024 * 1024 and handler.backupCount == 3
    handler.maxBytes = 80
    handler.backupCount = 1
    for index in range(5):
        logger.info(json.dumps({'event':'test', 'index':index, 'text':'中文'*10}, ensure_ascii=False))
    for item in logger.handlers:
        item.close()
    files = list(tmp_path.glob('doctrace-qa.jsonl*'))
    assert len(files) == 2
    for item in files:
        for line in item.read_text(encoding='utf-8').splitlines():
            assert json.loads(line)['event'] == 'test'


def test_unavailable_log_directory_keeps_console_output(monkeypatch, tmp_path):
    config = load_module('logging_config')
    logger = logging.Logger('isolated_unavailable')
    monkeypatch.setattr(config, 'logging', SimpleNamespace(getLogger=lambda name: logger,
        INFO=logging.INFO, StreamHandler=logging.StreamHandler, Formatter=logging.Formatter))
    blocked = tmp_path / 'not-a-directory'
    blocked.write_text('test', encoding='utf-8')
    config.configure_qa_logging(blocked)
    assert [handler.name for handler in logger.handlers] == ['doctrace_qa_console']
    for handler in logger.handlers:
        handler.close()


def test_runtime_file_write_failure_does_not_raise(monkeypatch, tmp_path):
    config = load_module('logging_config')
    handler = config.QuietRotatingFileHandler(tmp_path/'test.jsonl', maxBytes=80, backupCount=1, encoding='utf-8')
    def fail(record):
        raise OSError('disk unavailable')
    monkeypatch.setattr(handler, 'shouldRollover', fail)
    logger = logging.Logger('isolated_failed_sink', level=logging.INFO)
    logger.addHandler(handler)
    logger.info('test')
    handler.close()
