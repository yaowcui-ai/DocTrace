"""Only a draft may transition to published; no real snapshots are released."""
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError

from app import public_examples


@pytest.fixture
def draft(example_engine):
    identifier=public_examples.create_public_example_draft(example_engine,payload={
        'question':'synthetic question','answer':'synthetic answer [1]','corpus_id':'synthetic',
        'references':[{'reference_id':'1','file_path':'synthetic.md','content':['synthetic evidence']}],
    })
    return identifier


def publish(engine,identifier):
    function=getattr(public_examples,'publish_public_example',None)
    assert callable(function),'Add publish_public_example() to app/public_examples.py'
    return function(engine,identifier)


def row(engine,identifier):
    with engine.connect() as conn:
        return dict(conn.execute(text('SELECT * FROM public_examples WHERE example_id=:id'),{'id':identifier}).mappings().one())


def test_publish_commits_state_and_time_without_changing_snapshot(example_engine,draft):
    before=row(example_engine,draft)
    assert publish(example_engine,draft) is True
    after=row(example_engine,draft)
    assert after['status']=='published'
    assert after['published_at'] is not None and after['published_at']==after['updated_at']
    for name in ('question','answer','references_json','corpus_id','created_at'):
        assert before[name]==after[name]


def test_public_read_only_sees_content_after_publish(example_engine,draft):
    assert public_examples.get_published_example(example_engine,draft) is None
    assert publish(example_engine,draft) is True
    assert public_examples.get_published_example(example_engine,draft)['answer']=='synthetic answer [1]'


def test_repeat_publish_keeps_original_time(example_engine,draft):
    assert publish(example_engine,draft) is True
    before=row(example_engine,draft)
    assert publish(example_engine,draft) is False
    assert row(example_engine,draft)==before


def test_unknown_identifier_is_not_success(example_engine,draft):
    assert publish(example_engine,'00000000-0000-4000-8000-999999999999') is False
    assert row(example_engine,draft)['status']=='draft'


def test_withdrawn_example_cannot_be_republished_by_this_operation(example_engine,draft):
    with example_engine.begin() as conn:
        conn.execute(text("UPDATE public_examples SET status='withdrawn' WHERE example_id=:id"),{'id':draft})
    before=row(example_engine,draft)
    assert publish(example_engine,draft) is False
    assert row(example_engine,draft)==before


def test_only_requested_draft_changes(example_engine,draft):
    other=public_examples.create_public_example_draft(example_engine,payload={
        'question':'another question','answer':'another answer [1]','corpus_id':'synthetic',
        'references':[{'reference_id':'1','file_path':'synthetic.md','content':['synthetic evidence']}],
    })
    assert publish(example_engine,draft) is True
    assert row(example_engine,other)['status']=='draft'


def test_database_error_is_not_false_state_result(example_engine,draft,monkeypatch):
    def fail():raise SQLAlchemyError('synthetic outage')
    monkeypatch.setattr(example_engine,'begin',fail)
    with pytest.raises(SQLAlchemyError):publish(example_engine,draft)


def test_update_failure_rolls_back(example_engine,draft):
    def fail(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('UPDATE'):
            raise SQLAlchemyError('synthetic update failure')
    event.listen(example_engine,'after_cursor_execute',fail)
    try:
        with pytest.raises(SQLAlchemyError):publish(example_engine,draft)
    finally:event.remove(example_engine,'after_cursor_execute',fail)
    assert row(example_engine,draft)['status']=='draft'
    assert row(example_engine,draft)['published_at'] is None
