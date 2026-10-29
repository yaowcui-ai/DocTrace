"""Real HTTP/auth/SQL product browser fixture; ONLY provider calls are synthetic."""
import sys
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from sqlalchemy import create_engine, text

from app import main, auth_http
from app.auth_config import AuthSettings
from app.product.tables import metadata, roles
from app.knowledge.repository import metadata as knowledge_metadata
from app.qa_records import create_processing_record, save_completed_record
from app.schemas import MediumAskResponse
from app.security_limits import SlidingWindowLimiter
from app.users import create_user


def serve(database_path, port):
    engine = create_engine('sqlite+pysqlite:///' + str(database_path))
    with engine.begin() as conn:
        conn.execute(text('''CREATE TABLE app_users (
            user_id CHAR(36) PRIMARY KEY, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,is_active INTEGER NOT NULL,
            created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL)'''))
        conn.execute(text('''CREATE TABLE app_sessions (
            session_id CHAR(36) PRIMARY KEY,token_hash CHAR(64) UNIQUE NOT NULL,
            user_id CHAR(36) NOT NULL,created_at DATETIME NOT NULL,
            expires_at DATETIME NOT NULL,revoked_at DATETIME)'''))
        conn.execute(text('''CREATE TABLE qa_records (
            request_id CHAR(36) PRIMARY KEY,owner_user_id CHAR(36),idempotency_key CHAR(36),
            question TEXT NOT NULL,corpus_id TEXT NOT NULL,status TEXT NOT NULL,
            request_mode TEXT NOT NULL DEFAULT 'mix',
            created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL,answer TEXT,
            references_json TEXT,retrieval_json TEXT,http_status INTEGER,
            llm_generated INTEGER,duration_ms INTEGER,error_stage TEXT,error_message TEXT,
            UNIQUE(owner_user_id,idempotency_key))'''))
    metadata.create_all(engine)
    knowledge_metadata.create_all(engine)
    for username in ('alice', 'bob', 'admin'):
        uid = create_user(engine, username=username, password='FixturePass123!')
        if username == 'admin':
            with engine.begin() as conn:
                conn.execute(roles.insert().values(user_id=uid, role='admin'))
        rid = create_processing_record(engine, question=f'{username} legacy policy question',
                                      corpus_id='offline_fixture', owner_user_id=uid)
        save_completed_record(engine, rid, result=MediumAskResponse(response='Offline policy answer [1]',
            references=[{'reference_id': '1', 'file_path': 'policy.md', 'content': ['Fixture policy evidence']}],
            llm_generated=False), duration_ms=0)

    @asynccontextmanager
    async def lifespan(application):
        application.state.db_engine = engine
        application.state.product_frozen_corpus_id = 'offline_fixture'
        application.state.login_limiter = SlidingWindowLimiter()
        yield
        application.state.db_engine = None
        engine.dispose()
    main.app.router.lifespan_context = lifespan
    auth_http.load_auth_settings = lambda: AuthSettings(f'http://127.0.0.1:{port}', False, 7200)
    main.load_medium_settings = lambda: SimpleNamespace(corpus_id='offline_fixture', rag_settings=None, max_total_tokens=40000)
    main.load_answer_settings = lambda: None
    main.load_pipeline_settings = lambda: None
    main.load_rerank_settings = lambda: None
    main.make_qa_client = lambda: nullcontext(None)
    main.run_selected_qa_pipeline = lambda *args, mode, **kwargs: MediumAskResponse(
        response='Offline policy answer [1]',
        references=[{'reference_id': '1', 'file_path': 'policy.md', 'content': ['Fixture policy evidence']}],
        llm_generated=False, retrieval={'mode': mode, 'policy_version': 'offline-fixture', 'strategy': 'mock_provider', 'degraded': False})
    def forbidden(*args, **kwargs):
        raise AssertionError('External providers forbidden in browser fixture')
    main.LightRAGClient.ask = forbidden
    uvicorn.run(main.app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    serve(Path(sys.argv[1]), int(sys.argv[2]))
