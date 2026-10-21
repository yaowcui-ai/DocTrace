"""Public lookup never exposes draft or withdrawn snapshots; no real data/model."""
from importlib import import_module
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


PUBLISHED = '00000000-0000-4000-8000-000000000001'
DRAFT = '00000000-0000-4000-8000-000000000002'
WITHDRAWN = '00000000-0000-4000-8000-000000000003'


@pytest.fixture
def examples(example_engine):
    with example_engine.begin() as conn:
        for identifier, status in [(PUBLISHED,'published'),(DRAFT,'draft'),(WITHDRAWN,'withdrawn')]:
            conn.execute(text('''
                INSERT INTO public_examples
                (example_id,question,answer,references_json,corpus_id,status,created_at,updated_at,published_at)
                VALUES (:id,:question,:answer,:refs,'synthetic_corpus',:status,
                        '2026-10-17 00:00:00','2026-10-17 00:00:00',:published)
            '''),{
                'id':identifier, 'status':status,
                'question':status+' synthetic question', 'answer':status+' synthetic answer',
                'refs':json.dumps([{'reference_id':'1','file_path':'synthetic.md','content':['synthetic evidence']}]),
                'published':None if status=='draft' else '2026-10-17 00:00:00',
            })
    return import_module('app.public_examples')


def test_published_snapshot_returns_answer_and_evidence(example_engine, examples):
    row=examples.get_published_example(example_engine,PUBLISHED)
    assert isinstance(row,dict)
    assert row['example_id']==PUBLISHED
    assert row['answer']=='published synthetic answer'
    assert json.loads(row['references_json'])[0]['content']==['synthetic evidence']


@pytest.mark.parametrize('identifier',[DRAFT,WITHDRAWN])
def test_known_unpublished_identifiers_return_nothing(example_engine, examples, identifier):
    assert examples.get_published_example(example_engine,identifier) is None


@pytest.mark.parametrize('identifier',['00000000-0000-4000-8000-999999999999',"' OR 1=1 --"])
def test_unknown_or_injected_identifier_does_not_match(example_engine, examples, identifier):
    assert examples.get_published_example(example_engine,identifier) is None


def test_explicit_projection_and_read_does_not_change_snapshot(example_engine, examples):
    with example_engine.connect() as conn:
        before=dict(conn.execute(text('SELECT * FROM public_examples WHERE example_id=:id'),{'id':PUBLISHED}).mappings().one())
    row=examples.get_published_example(example_engine,PUBLISHED)
    assert set(row)=={'example_id','question','answer','references_json','corpus_id','published_at'}
    with example_engine.connect() as conn:
        after=dict(conn.execute(text('SELECT * FROM public_examples WHERE example_id=:id'),{'id':PUBLISHED}).mappings().one())
    assert before==after


def test_database_failure_is_not_misreported_as_missing_example(example_engine, examples, monkeypatch):
    def fail():
        raise SQLAlchemyError('synthetic database unavailable')
    monkeypatch.setattr(example_engine,'connect',fail)
    with pytest.raises(SQLAlchemyError):
        examples.get_published_example(example_engine,PUBLISHED)
