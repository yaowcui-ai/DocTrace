import hashlib
from importlib import import_module
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


@pytest.fixture
def reviewed_file(tmp_path):
    payload={'question':'synthetic question','answer':'synthetic answer [1]','corpus_id':'synthetic',
             'references':[{'reference_id':'1','file_path':'synthetic.md','content':['synthetic evidence']}]}
    path=tmp_path/'example.json'
    path.write_text(json.dumps(payload),encoding='utf-8')
    digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    path.with_suffix('.review.json').write_text(json.dumps({'review_status':'approved','payload_sha256':digest}),encoding='utf-8')
    return path


@pytest.fixture
def cli(example_engine,monkeypatch):
    module=import_module('app.create_example_draft')
    monkeypatch.setattr(module,'load_database_settings',lambda:object())
    monkeypatch.setattr(module,'create_db_engine',lambda settings:example_engine)
    return module


def test_preview_checks_review_without_database(cli,reviewed_file,monkeypatch,capsys):
    monkeypatch.setattr(cli,'create_db_engine',lambda settings:pytest.fail('Preview must not open DB'))
    assert cli.main(['--file',str(reviewed_file)])==0
    assert 'Validation passed' in capsys.readouterr().out
    assert not reviewed_file.with_suffix('.import.json').exists()


@pytest.mark.parametrize('change',['missing_review','unapproved','changed_content'])
def test_bad_approval_stops_before_database(cli,reviewed_file,monkeypatch,change):
    if change=='missing_review':reviewed_file.with_suffix('.review.json').unlink()
    elif change=='unapproved':reviewed_file.with_suffix('.review.json').write_text('{}',encoding='utf-8')
    else:
        payload=json.loads(reviewed_file.read_text(encoding='utf-8'))
        payload['answer']='changed after review [1]'
        reviewed_file.write_text(json.dumps(payload),encoding='utf-8')
    monkeypatch.setattr(cli,'create_db_engine',lambda settings:pytest.fail('No DB before review validation'))
    assert cli.main(['--file',str(reviewed_file),'--submit'])==1
    assert not reviewed_file.with_suffix('.import.json').exists()


def test_submit_creates_draft_and_receipt_but_not_publication(cli,reviewed_file,example_engine,capsys):
    assert cli.main(['--file',str(reviewed_file),'--submit'])==0
    receipt=json.loads(reviewed_file.with_suffix('.import.json').read_text(encoding='utf-8'))
    assert receipt['status']=='created'
    assert receipt['example_id'] in capsys.readouterr().out
    with example_engine.connect() as conn:
        row=conn.execute(text('SELECT * FROM public_examples')).mappings().one()
    assert row['example_id']==receipt['example_id']
    assert row['status']=='draft' and row['published_at'] is None


def test_second_submit_does_not_create_another_draft(cli,reviewed_file,example_engine):
    assert cli.main(['--file',str(reviewed_file),'--submit'])==0
    assert cli.main(['--file',str(reviewed_file),'--submit'])==1
    with example_engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM public_examples')).scalar_one()==1


def test_uncertain_submission_keeps_marker_and_refuses_retry(cli,reviewed_file,monkeypatch,capsys):
    def fail(*args,**kwargs):raise SQLAlchemyError('private SQL details')
    monkeypatch.setattr(cli,'create_public_example_draft',fail)
    assert cli.main(['--file',str(reviewed_file),'--submit'])==1
    receipt=json.loads(reviewed_file.with_suffix('.import.json').read_text(encoding='utf-8'))
    assert receipt['status']=='submission_started'
    assert 'private SQL details' not in capsys.readouterr().out
    assert cli.main(['--file',str(reviewed_file),'--submit'])==1
