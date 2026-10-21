"""Real MySQL ownership/session smoke, isolated by a rolled-back outer transaction.

Does not start a server or call providers. Test credentials and tokens stay in memory.
This validates MySQL constraints and HTTP integration; committed transaction behavior
is separately covered by repository tests (the outer transaction here is deliberate).
"""
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import text

from . import main, auth_http
from .auth_config import AuthSettings, SESSION_COOKIE_NAME
from .database import create_db_engine
from .database_config import load_database_settings
from .qa_records import create_processing_record, save_completed_record
from .recorded_qa import run_recorded_qa
from .schemas import AskResponse
from .users import create_user


class BorrowedTransaction:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        # A nested savepoint supports duplicate-key exception recovery, while
        # every successful fixture write still belongs to the outer rollback.
        with self.connection.begin_nested():
            yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection

    def dispose(self):
        pass


def counts(connection):
    return {table: connection.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar_one()
            for table in ('app_users', 'app_sessions', 'qa_records')}


def main_check():
    report = {'kind': 'mysql_identity_rollback_not_model_evaluation', 'provider_requests': 0, 'checks': [], 'status': 'started'}
    engine = create_db_engine(load_database_settings())
    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        report['checks'].append(label)
    def forbidden(*args, **kwargs):
        raise AssertionError('Provider call forbidden')
    try:
        with engine.connect() as conn:
            report['before'] = counts(conn)
            conn.rollback()
            outer = conn.begin()
            try:
                borrowed = BorrowedTransaction(conn)
                prefix = 'authcheck_' + uuid4().hex[:10]
                alice = create_user(borrowed, username=prefix+'a', password='Fake!123')
                bob = create_user(borrowed, username=prefix+'b', password='Fake!123')
                result = AskResponse(response='Synthetic MySQL ownership test', references=[], llm_generated=False)
                key = str(uuid4())
                aid, _ = run_recorded_qa(borrowed, question='a', corpus_id='auth_smoke', answer_fn=lambda: result, owner_user_id=alice, idempotency_key=key)
                bid, _ = run_recorded_qa(borrowed, question='b', corpus_id='auth_smoke', answer_fn=lambda: result, owner_user_id=bob, idempotency_key=key)
                check(aid != bid, 'MySQL owner-key unique constraint separates accounts')
                replay, _ = run_recorded_qa(borrowed, question='a', corpus_id='auth_smoke', answer_fn=forbidden, owner_user_id=alice, idempotency_key=key)
                check(replay == aid, 'MySQL same-account duplicate reuses original answer')
                legacy=create_processing_record(borrowed, question='unassigned synthetic',corpus_id='auth_smoke')
                save_completed_record(borrowed, legacy, result=result, duration_ms=0)
                with patch.object(main,'create_db_engine',return_value=borrowed), \
                     patch.object(auth_http,'load_auth_settings',return_value=AuthSettings('http://127.0.0.1:8001',False,7200)), \
                     patch.object(main,'make_qa_client',side_effect=forbidden), \
                     patch.object(main.LightRAGClient,'ask',side_effect=forbidden):
                    with TestClient(main.app,base_url='http://127.0.0.1:8001') as client:
                        client.headers['Origin']='http://127.0.0.1:8001'
                        check(client.get('/records').status_code == 401, 'anonymous history denied')
                        response=client.post('/auth/login',json={'username':prefix+'a','password':'Fake!123'})
                        check(response.status_code == 200, 'real MySQL credential verification and session insert')
                        check(client.get('/auth/me').json()['user_id'] == alice, 'real MySQL session identity lookup')
                        ids=[item['request_id'] for item in client.get('/records').json()['items']]
                        check(ids == [aid], 'real MySQL history filters before pagination')
                        check(client.get('/records/'+bid).status_code == 404, 'foreign record hidden')
                        check(client.get('/records/'+legacy).status_code == 404, 'unassigned record hidden')
                        token=client.cookies.get(SESSION_COOKIE_NAME)
                        check(client.post('/auth/logout',json={}).status_code == 204, 'real MySQL logout update')
                        client.cookies.clear()
                        client.cookies.set(SESSION_COOKIE_NAME,token)
                        check(client.get('/auth/me').status_code == 401, 'captured old credential rejected after logout')
            finally:
                outer.rollback()
            report['after']=counts(conn)
            check(report['before'] == report['after'], 'all test rows rolled back; existing counts unchanged')
        report['status']='passed'
    except Exception as error:
        report['status']='failed'
        report['error_type']=type(error).__name__
        # Never serialize raw database exceptions, request bodies, or credentials.
    finally:
        engine.dispose()
    target=Path(__file__).resolve().parent.parent/'evaluation'/'runs'/(
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_identity_mysql.json')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Status:',report['status'],'Checks:',len(report['checks']))
    print('Report:',target)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main_check())
