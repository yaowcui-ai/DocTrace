import importlib
import json

import pytest


@pytest.fixture
def setup_cli(tmp_path, monkeypatch):
    module = importlib.import_module('app.publish_record_example')
    payload = {'question': 'Synthetic question', 'answer': 'Synthetic answer [1]',
        'references': [{'reference_id': '1', 'file_path': 'public.md', 'content': ['Synthetic evidence']}],
        'corpus_id': 'synthetic'}
    monkeypatch.setattr(module, 'OUTPUT_DIR', tmp_path)
    monkeypatch.setattr(module, 'read_snapshot', lambda identifier: payload)
    calls = []
    monkeypatch.setattr(module.create_example_draft, 'main', lambda args: calls.append('import') or 0)
    monkeypatch.setattr(module.publish_example, 'main', lambda args: calls.append('publish') or 0)
    return module, payload, calls, tmp_path


def inputs(monkeypatch, *values):
    iterator = iter(values)
    monkeypatch.setattr('builtins.input', lambda prompt='': next(iterator))


IDENTIFIER = '00000000-0000-4000-8000-000000000001'


def test_one_identifier_and_confirmation_publishes(setup_cli, monkeypatch):
    module, payload, calls, folder = setup_cli
    inputs(monkeypatch, IDENTIFIER, 'PUBLISH')
    assert module.main([]) == 0
    assert calls == ['import', 'publish']
    snapshot = json.loads((folder / (IDENTIFIER + '.json')).read_text(encoding='utf-8'))
    assert snapshot == payload
    assert 'request_id' not in snapshot


def test_cancel_does_not_write_or_publish(setup_cli, monkeypatch):
    module, _, calls, folder = setup_cli
    inputs(monkeypatch, IDENTIFIER, 'no')
    assert module.main([]) == 0
    assert calls == [] and list(folder.iterdir()) == []


def test_bad_identifier_does_not_read_database(setup_cli, monkeypatch):
    module, _, calls, _ = setup_cli
    monkeypatch.setattr(module, 'read_snapshot', lambda identifier: pytest.fail('No read'))
    inputs(monkeypatch, 'invalid')
    assert module.main([]) == 1
    assert calls == []


def test_failed_or_missing_record_rejected(setup_cli, monkeypatch):
    module, _, calls, _ = setup_cli
    monkeypatch.setattr(module, 'read_snapshot', lambda identifier: (_ for _ in ()).throw(ValueError()))
    inputs(monkeypatch, IDENTIFIER)
    assert module.main([]) == 1 and calls == []


def test_repeated_record_does_not_reimport(setup_cli, monkeypatch):
    module, _, calls, folder = setup_cli
    (folder / (IDENTIFIER + '.json')).write_text('keep')
    inputs(monkeypatch, IDENTIFIER)
    assert module.main([]) == 1 and calls == []


def test_import_failure_stops_publish(setup_cli, monkeypatch):
    module, _, calls, _ = setup_cli
    monkeypatch.setattr(module.create_example_draft, 'main', lambda args: 1)
    inputs(monkeypatch, IDENTIFIER, 'PUBLISH')
    assert module.main([]) == 1 and calls == []


@pytest.mark.parametrize('status,http_status,accepted', [
    ('completed', 200, True), ('processing', None, False), ('failed', 504, False),
])
def test_database_reader_only_exports_completed_public_fields(monkeypatch, status, http_status, accepted):
    from app import publish_record_example as module
    from sqlalchemy import create_engine, text
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('''CREATE TABLE qa_records (
            request_id TEXT, question TEXT, answer TEXT, references_json TEXT,
            corpus_id TEXT, status TEXT, http_status INTEGER, owner_user_id TEXT)'''))
        connection.execute(text('''INSERT INTO qa_records VALUES
            (:id, 'Question', 'Answer [1]', :refs, 'synthetic', :status, :http, 'private-owner')'''),
            {'id': IDENTIFIER, 'refs': json.dumps([{'reference_id': '1', 'file_path': 'public.md',
                'content': ['Evidence'], 'extra_private_metadata': 'never copy'}]),
             'status': status, 'http': http_status})
    monkeypatch.setattr(module, 'load_database_settings', lambda: object())
    monkeypatch.setattr(module, 'create_db_engine', lambda settings: engine)
    if accepted:
        payload = module.read_snapshot(IDENTIFIER)
        assert set(payload) == {'question', 'answer', 'references', 'corpus_id'}
        assert set(payload['references'][0]) == {'reference_id', 'file_path', 'content'}
    else:
        with pytest.raises(ValueError):
            module.read_snapshot(IDENTIFIER)
