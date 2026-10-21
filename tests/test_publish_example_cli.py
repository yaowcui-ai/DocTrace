import hashlib
from importlib import import_module
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import public_examples


@pytest.fixture
def reviewed(example_engine,tmp_path):
    payload={'question':'synthetic question','answer':'synthetic answer [1]','corpus_id':'synthetic',
             'references':[{'reference_id':'1','file_path':'synthetic.md','content':['synthetic evidence']}]}
    identifier=public_examples.create_public_example_draft(example_engine,payload=payload)
    digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    path=tmp_path/'example.json'
    path.write_text(json.dumps(payload),encoding='utf-8')
    path.with_suffix('.review.json').write_text(json.dumps({'review_status':'approved','payload_sha256':digest}),encoding='utf-8')
    path.with_suffix('.import.json').write_text(json.dumps({'kind':'public_example_draft_import','status':'created','example_id':identifier,'payload_sha256':digest}),encoding='utf-8')
    return path,identifier


@pytest.fixture
def cli(example_engine,monkeypatch):
    module=import_module('app.publish_example')
    monkeypatch.setattr(module,'load_database_settings',lambda:object())
    monkeypatch.setattr(module,'create_db_engine',lambda settings:example_engine)
    return module


def status(engine,identifier):
    with engine.connect() as conn:
        return dict(conn.execute(text('SELECT status,published_at FROM public_examples WHERE example_id=:id'),{'id':identifier}).mappings().one())


def test_preview_does_not_publish(cli,reviewed,example_engine,capsys):
    path,identifier=reviewed
    assert cli.main(['--file',str(path)])==0
    assert status(example_engine,identifier)['status']=='draft'
    assert 'Ready to publish' in capsys.readouterr().out


def test_explicit_publication_is_visible(cli,reviewed,example_engine):
    path,identifier=reviewed
    assert cli.main(['--file',str(path),'--publish'])==0
    assert public_examples.get_published_example(example_engine,identifier) is not None


def test_repeat_publication_does_not_change_time(cli,reviewed,example_engine):
    path,identifier=reviewed
    assert cli.main(['--file',str(path),'--publish'])==0
    before=status(example_engine,identifier)
    assert cli.main(['--file',str(path),'--publish'])==0
    assert status(example_engine,identifier)==before


def test_database_content_changed_after_review_is_rejected(cli,reviewed,example_engine):
    path,identifier=reviewed
    with example_engine.begin() as conn:
        conn.execute(text("UPDATE public_examples SET answer='changed answer [1]' WHERE example_id=:id"),{'id':identifier})
    assert cli.main(['--file',str(path),'--publish'])==1
    assert status(example_engine,identifier)['status']=='draft'


def test_file_changed_after_review_is_rejected(cli,reviewed,example_engine):
    path,identifier=reviewed
    payload=json.loads(path.read_text(encoding='utf-8'));payload['answer']='changed after approval [1]'
    path.write_text(json.dumps(payload),encoding='utf-8')
    assert cli.main(['--file',str(path),'--publish'])==1
    assert status(example_engine,identifier)['status']=='draft'


def test_pending_import_cannot_be_published(cli,reviewed,example_engine):
    path,identifier=reviewed
    receipt=json.loads(path.with_suffix('.import.json').read_text(encoding='utf-8'));receipt['status']='submission_started'
    path.with_suffix('.import.json').write_text(json.dumps(receipt),encoding='utf-8')
    assert cli.main(['--file',str(path),'--publish'])==1
    assert status(example_engine,identifier)['status']=='draft'


def test_withdrawn_snapshot_cannot_be_republished(cli,reviewed,example_engine):
    path,identifier=reviewed
    with example_engine.begin() as conn:
        conn.execute(text("UPDATE public_examples SET status='withdrawn' WHERE example_id=:id"),{'id':identifier})
    assert cli.main(['--file',str(path),'--publish'])==1
    assert status(example_engine,identifier)['status']=='withdrawn'


def test_error_after_update_rolls_back_whole_transaction(cli,reviewed,example_engine,monkeypatch,capsys):
    path,identifier=reviewed
    original=cli.publish_public_example
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise SQLAlchemyError('private database error')
    monkeypatch.setattr(cli,'publish_public_example',fail)
    assert cli.main(['--file',str(path),'--publish'])==1
    assert status(example_engine,identifier)['status']=='draft'
    assert 'private database error' not in capsys.readouterr().out
