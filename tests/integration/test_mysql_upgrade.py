"""Real InnoDB verification in a disposable schema on the upgrade MySQL ONLY."""
import os
from pathlib import Path
import re
from uuid import uuid4

import pytest
from sqlalchemy import URL, create_engine, text

pytestmark = pytest.mark.mysql
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mysql_engine():
    if os.environ.get('DOCTRACE_MYSQL_INTEGRATION') != '1':
        pytest.skip('Explicit opt-in to the isolated upgrade MySQL is required')
    from dotenv import dotenv_values
    from app.upgrade_setup import legacy_metadata
    from app.product.tables import metadata
    from app.knowledge.repository import metadata as knowledge_metadata
    values = dotenv_values(ROOT/'runtime/upgrade/.env', interpolate=False)
    assert values.get('MYSQL_DATABASE') == 'doctrace_upgrade' and values.get('MYSQL_PORT') == '3310'
    name = 'doctrace_upgrade_test_'+uuid4().hex[:12]
    assert re.fullmatch('doctrace_upgrade_test_[a-f0-9]{12}', name)
    url = URL.create('mysql+pymysql', username='root', password=values['MYSQL_ROOT_PASSWORD'],
        host='127.0.0.1', port=3310, database='mysql', query={'charset': 'utf8mb4'})
    admin = create_engine(url, hide_parameters=True, pool_pre_ping=True)
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci'))
        engine = create_engine(url.set(database=name), hide_parameters=True, pool_pre_ping=True)
        legacy_metadata.create_all(engine)
        metadata.create_all(engine)
        knowledge_metadata.create_all(engine)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
            # Only this fixture-created random schema can be removed. Never doctrace_upgrade or doctrace.
            assert re.fullmatch('doctrace_upgrade_test_[a-f0-9]{12}', name)
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE `{name}`'))
        admin.dispose()


def test_real_mysql_utf8_json_and_owner_filter(mysql_engine):
    from app.users import create_user
    from app.qa_records import create_processing_record, save_completed_record, get_qa_record
    from app.schemas import AskResponse
    alice = create_user(mysql_engine, username='mysql_alice', password='TestOnlyPass234!')
    bob = create_user(mysql_engine, username='mysql_bob', password='TestOnlyPass234!')
    rid = create_processing_record(mysql_engine, question='中文制度与表情🧪', corpus_id='test', owner_user_id=alice)
    save_completed_record(mysql_engine, rid, result=AskResponse(response='中文答案🧪', references=[
        {'reference_id': '1', 'file_path': 'policy.md', 'content': ['中文原文']}], llm_generated=False), duration_ms=3)
    own = get_qa_record(mysql_engine, rid, owner_user_id=alice)
    assert own['question'] == '中文制度与表情🧪' and own['answer'] == '中文答案🧪'
    assert get_qa_record(mysql_engine, rid, owner_user_id=bob) is None
    with mysql_engine.connect() as connection:
        assert connection.execute(text('SELECT JSON_VALID(references_json) FROM qa_records')).scalar_one() == 1


def test_real_mysql_concurrent_idempotency_invokes_answer_once(mysql_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    import time
    from app.users import create_user
    from app.recorded_qa import run_recorded_qa, RecordedQAError
    from app.schemas import AskResponse
    owner = create_user(mysql_engine, username='mysql_alice', password='TestOnlyPass234!')
    key, called, lock = str(uuid4()), [], Lock()
    def answer():
        with lock:
            called.append(1)
        time.sleep(.1)
        return AskResponse(response='Synthetic database integration answer', references=[], llm_generated=False)
    def execute(_):
        try:
            return run_recorded_qa(mysql_engine, question='Synthetic duplicate operation', corpus_id='test',
                answer_fn=answer, owner_user_id=owner, idempotency_key=key, request_mode='naive')[0]
        except RecordedQAError as error:
            assert error.status_code == 409
            return error.request_id
    with ThreadPoolExecutor(max_workers=8) as workers:
        ids = list(workers.map(execute, range(8)))
    assert len(called) == 1 and len(set(ids)) == 1
    with mysql_engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM qa_records')).scalar_one() == 1


def test_real_mysql_document_enqueue_is_idempotent_under_row_lock(mysql_engine):
    from concurrent.futures import ThreadPoolExecutor
    from app.knowledge.repository import KnowledgeRepository
    repo = KnowledgeRepository(mysql_engine)
    document = repo.create('integration.md', 'Synthetic integration document; worker uses another database.')
    with ThreadPoolExecutor(max_workers=8) as workers:
        jobs = list(workers.map(lambda _: repo.enqueue(document['doc_id'])['task_id'], range(8)))
    assert len(set(jobs)) == 1
    with mysql_engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM managed_index_jobs')).scalar_one() == 1
