import importlib
import json

import pytest


@pytest.fixture
def wizard(tmp_path, monkeypatch):
    module = importlib.import_module('app.publish_example_wizard')
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'references': [{'reference_id': '1', 'file_path': 'public.md',
        'content': ['Public evidence']}], 'corpus_id': 'synthetic'}), encoding='utf-8')
    calls = []
    monkeypatch.setattr(module.create_example_draft, 'main', lambda args: calls.append(('import', args)) or 0)
    monkeypatch.setattr(module.publish_example, 'main', lambda args: calls.append(('publish', args)) or 0)
    return module, source, tmp_path / 'new.json', calls


def answer(monkeypatch, values):
    iterator = iter(values)
    monkeypatch.setattr('builtins.input', lambda prompt='': next(iterator))


def test_confirmed_input_serializes_quotes_newlines_and_publishes(wizard, monkeypatch):
    module, source, output, calls = wizard
    answer(monkeypatch, ['Question "quoted"?', 'Answer "quoted" [1]', '', 'More.', 'END', 'PUBLISH'])
    assert module.main(['--source', str(source), '--output', str(output)]) == 0
    data = json.loads(output.read_text(encoding='utf-8'))
    assert data['answer'] == 'Answer "quoted" [1]\n\nMore.'
    assert data['references'][0]['content'] == ['Public evidence']
    from app.public_example_review import load_reviewed_draft
    assert load_reviewed_draft(output)[0] == data
    assert [call[0] for call in calls] == ['import', 'publish']
    assert '--submit' in calls[0][1] and '--publish' in calls[1][1]


def test_cancel_keeps_local_draft_without_approval_or_db(wizard, monkeypatch):
    module, source, output, calls = wizard
    answer(monkeypatch, ['Question?', 'Answer [1]', 'END', 'no'])
    assert module.main(['--source', str(source), '--output', str(output)]) == 0
    assert output.exists()
    assert not output.with_suffix('.review.json').exists()
    assert calls == []


def test_invalid_citation_never_approves_or_imports(wizard, monkeypatch):
    module, source, output, calls = wizard
    answer(monkeypatch, ['Question?', 'Answer [9]', 'END'])
    assert module.main(['--source', str(source), '--output', str(output)]) == 1
    assert not output.exists()
    assert calls == []


def test_existing_output_preserved(wizard):
    module, source, output, calls = wizard
    output.write_text('keep', encoding='utf-8')
    assert module.main(['--source', str(source), '--output', str(output)]) == 1
    assert output.read_text() == 'keep'
    assert calls == []


def test_import_failure_stops_publication_and_preserves_files(wizard, monkeypatch):
    module, source, output, calls = wizard
    monkeypatch.setattr(module.create_example_draft, 'main', lambda args: 1)
    answer(monkeypatch, ['Question?', 'Answer [1]', 'END', 'PUBLISH'])
    assert module.main(['--source', str(source), '--output', str(output)]) == 1
    assert output.with_suffix('.review.json').exists()
    assert calls == []


def test_bad_source_has_no_db_effect(wizard):
    module, source, output, calls = wizard
    source.write_text('{broken', encoding='utf-8')
    assert module.main(['--source', str(source), '--output', str(output)]) == 1
    assert not output.exists()
    assert calls == []


def test_real_import_and_publication_on_temporary_database(tmp_path, monkeypatch, example_engine):
    from app import publish_example_wizard as module
    from sqlalchemy import text
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'references': [{'reference_id': '1', 'file_path': 'public.md',
        'content': ['Synthetic public evidence']}], 'corpus_id': 'synthetic'}), encoding='utf-8')
    output = tmp_path / 'new.json'
    for cli in (module.create_example_draft, module.publish_example):
        monkeypatch.setattr(cli, 'load_database_settings', lambda: object())
        monkeypatch.setattr(cli, 'create_db_engine', lambda settings: example_engine)
    answer(monkeypatch, ['Question?', 'Answer [1]', 'END', 'PUBLISH'])
    assert module.main(['--source', str(source), '--output', str(output)]) == 0
    with example_engine.connect() as connection:
        rows = connection.execute(text('SELECT status, question FROM public_examples')).all()
    assert rows == [('published', 'Question?')]
    assert json.loads(output.with_suffix('.import.json').read_text())['status'] == 'created'
