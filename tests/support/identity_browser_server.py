"""Isolated browser fixture: temporary SQLite, synthetic users/answers, no providers."""
import sys
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from sqlalchemy import create_engine, text

from app import main, auth_http
from app.auth_config import AuthSettings
from app.qa_records import create_processing_record, save_completed_record
from app.schemas import AskResponse, MediumAskResponse
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
    for username in ('alice', 'bob'):
        uid=create_user(engine,username=username,password='Fake!123')
        rid=create_processing_record(engine,question=f'{username} synthetic private question',corpus_id='browser_fixture',owner_user_id=uid)
        save_completed_record(engine,rid,result=AskResponse(response=f'{username} synthetic private answer [1]',references=[{'reference_id':'1','file_path':'synthetic.md','content':['Synthetic evidence only']}],llm_generated=False),duration_ms=0)

    @asynccontextmanager
    async def lifespan(app):
        app.state.db_engine=engine
        yield
        app.state.db_engine=None
        engine.dispose()
    main.app.router.lifespan_context=lifespan
    auth_http.load_auth_settings=lambda: AuthSettings(f'http://127.0.0.1:{port}',False,7200)
    main.load_medium_settings=lambda: SimpleNamespace(corpus_id='browser_fixture',rag_settings=None,max_total_tokens=40000)
    main.load_answer_settings=lambda: None
    main.make_qa_client=lambda: nullcontext(None)
    main.load_pipeline_settings=lambda: None
    main.load_rerank_settings=lambda: None
    main.run_selected_qa_pipeline=lambda *args, mode, **kwargs: MediumAskResponse(response='Synthetic new answer',references=[],llm_generated=False,retrieval={'mode':mode,'policy_version':'fixture','strategy':'fixture','degraded':False})
    def forbidden(*args,**kwargs):
        raise AssertionError('Provider calls forbidden in browser fixture')
    main.LightRAGClient.ask=forbidden
    uvicorn.run(main.app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':
    serve(Path(sys.argv[1]),int(sys.argv[2]))
