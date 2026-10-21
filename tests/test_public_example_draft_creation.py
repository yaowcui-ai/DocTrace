"""Saving a draft never publishes it; synthetic temporary SQLite only."""
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError

from app import public_examples


@pytest.fixture
def payload():
    return {'question':'synthetic question','answer':'synthetic answer [1]','corpus_id':'synthetic',
            'references':[{'reference_id':'1','file_path':'synthetic.md','content':['synthetic evidence']}]}


def create(engine,payload):
    function=getattr(public_examples,'create_public_example_draft',None)
    assert callable(function),'Add create_public_example_draft() to app/public_examples.py'
    return function(engine,payload=payload)


def test_draft_is_committed_with_snapshot_and_no_publication_time(example_engine,payload):
    import json
    identifier=create(example_engine,payload)
    assert str(UUID(identifier))==identifier
    with example_engine.connect() as conn:
        row=conn.execute(text('SELECT * FROM public_examples')).mappings().one()
    assert row['status']=='draft' and row['published_at'] is None
    assert row['question']==payload['question'] and row['answer']==payload['answer']
    assert json.loads(row['references_json'])==payload['references']
    assert row['created_at']==row['updated_at']


def test_draft_is_not_readable_through_public_lookup(example_engine,payload):
    identifier=create(example_engine,payload)
    assert public_examples.get_published_example(example_engine,identifier) is None
    assert public_examples.list_published_examples(example_engine)['items']==[]


def test_new_drafts_are_independent_snapshots(example_engine,payload):
    first=create(example_engine,payload)
    payload['answer']='edited synthetic answer [1]'
    second=create(example_engine,payload)
    assert first!=second
    with example_engine.connect() as conn:
        assert conn.execute(text('SELECT answer FROM public_examples WHERE example_id=:id'),{'id':first}).scalar_one()=='synthetic answer [1]'


@pytest.mark.parametrize('field',['status','owner_user_id'])
def test_caller_cannot_add_publish_state_or_private_metadata(example_engine,payload,field):
    payload[field]='published' if field=='status' else 'private-user'
    with pytest.raises(ValueError):create(example_engine,payload)
    with example_engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM public_examples')).scalar_one()==0


def test_invalid_evidence_does_not_write(example_engine,payload):
    payload['references']=[]
    with pytest.raises(ValueError):create(example_engine,payload)
    with example_engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM public_examples')).scalar_one()==0


def test_database_failure_is_not_reported_as_creation(example_engine,payload,monkeypatch):
    def fail():raise SQLAlchemyError('synthetic outage')
    monkeypatch.setattr(example_engine,'begin',fail)
    with pytest.raises(SQLAlchemyError):create(example_engine,payload)


def test_failed_insert_rolls_back(example_engine,payload):
    def fail(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('INSERT'):
            raise SQLAlchemyError('synthetic failure after insert')
    event.listen(example_engine,'after_cursor_execute',fail)
    try:
        with pytest.raises(SQLAlchemyError):create(example_engine,payload)
    finally:event.remove(example_engine,'after_cursor_execute',fail)
    with example_engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM public_examples')).scalar_one()==0
