"""Keep API tests independent of private database credentials."""
import pytest
from sqlalchemy import create_engine, event, text

from app.database_config import DatabaseSettings

TEST_USER_ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def existing_route_tests_use_explicit_test_identity(request, monkeypatch):
    """Old route unit tests isolate their subject; permission integration tests do not override auth."""
    route_unit_files = {
        "test_idempotency_route.py", "test_lightrag_client.py", "test_optimized_route.py",
        "test_persisted_route.py", "test_questions.py", "test_record_list_route.py",
        "test_record_route.py", "test_request_observability.py",
    }
    if request.path.name not in route_unit_files:
        yield
        return
    from app import main, auth_http
    from app.auth_schemas import CurrentUserResponse
    identity = CurrentUserResponse(user_id=TEST_USER_ID, username="testuser")
    original = dict(main.app.dependency_overrides)
    main.app.dependency_overrides[main.read_current_user] = lambda: identity
    monkeypatch.setattr(auth_http, "require_trusted_json", lambda request: None)
    try:
        yield
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(original)


@pytest.fixture(autouse=True)
def isolate_api_database_configuration(monkeypatch):
    from app import main

    monkeypatch.setattr(
        main,
        "load_database_settings",
        lambda: DatabaseSettings("127.0.0.1", 1, "offline_test", "test", "dummy"),
        raising=False,
    )


@pytest.fixture
def record_engine(tmp_path):
    """Portable history table; real MySQL types are checked in manual smoke tests."""
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "records.db"))
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE qa_records (
                request_id CHAR(36) PRIMARY KEY,
                owner_user_id CHAR(36) NULL,
                idempotency_key CHAR(36) NULL,
                question TEXT NOT NULL,
                corpus_id VARCHAR(64) NOT NULL,
                request_mode VARCHAR(8) NOT NULL DEFAULT 'mix',
                status VARCHAR(20) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                answer TEXT NULL,
                references_json TEXT NULL,
                retrieval_json TEXT NULL,
                http_status INTEGER NULL,
                llm_generated INTEGER NULL,
                duration_ms INTEGER NULL,
                error_stage VARCHAR(32) NULL,
                error_message TEXT NULL,
                UNIQUE(owner_user_id, idempotency_key)
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX uq_qa_records_legacy_key ON qa_records(idempotency_key) WHERE owner_user_id IS NULL"))
    yield engine
    engine.dispose()


@pytest.fixture
def user_engine(tmp_path):
    """Temporary account table; never loads real MySQL account data."""
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "users.db"))
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE app_users (
                user_id CHAR(36) PRIMARY KEY,
                username VARCHAR(32) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
    yield engine
    engine.dispose()


@pytest.fixture
def session_engine(user_engine):
    """Session repository tests include real foreign-key/expiry constraints."""
    def enable_foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()
    event.listen(user_engine, 'connect', enable_foreign_keys)
    with user_engine.begin() as conn:
        conn.exec_driver_sql('PRAGMA foreign_keys=ON')
        conn.execute(text('''
            CREATE TABLE app_sessions (
                session_id CHAR(36) PRIMARY KEY,
                token_hash CHAR(64) NOT NULL UNIQUE,
                user_id CHAR(36) NOT NULL REFERENCES app_users(user_id),
                created_at DATETIME NOT NULL,
                expires_at DATETIME NOT NULL,
                revoked_at DATETIME NULL,
                CHECK (expires_at > created_at)
            )
        '''))
    try:
        yield user_engine
    finally:
        event.remove(user_engine, 'connect', enable_foreign_keys)


@pytest.fixture
def example_engine(tmp_path):
    """Only synthetic public snapshots in a separate temporary database."""
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'examples.db'))
    with engine.begin() as conn:
        conn.execute(text('''
            CREATE TABLE public_examples (
                example_id CHAR(36) PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                references_json TEXT NOT NULL,
                corpus_id VARCHAR(64) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'published', 'withdrawn')),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                published_at DATETIME NULL,
                CHECK (status <> 'published' OR published_at IS NOT NULL)
            )
        '''))
    yield engine
    engine.dispose()
