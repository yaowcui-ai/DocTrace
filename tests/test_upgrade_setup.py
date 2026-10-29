"""Portable setup tests; never connect to MySQL, old databases, or providers."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text

from app.database_config import DatabaseSettings

ROOT = Path(__file__).resolve().parents[1]


def module():
    assert (ROOT / 'app/upgrade_setup.py').exists(), 'Explicit isolated database setup module is missing'
    from app import upgrade_setup
    return upgrade_setup


def settings(database='doctrace_upgrade', host='127.0.0.1', port=3310):
    return DatabaseSettings(host, port, database, 'upgrade_app', 'not-a-real-credential')


@pytest.mark.parametrize('database,host,port', [
    ('doctrace', '127.0.0.1', 3306), ('doctrace_upgrade', '127.0.0.1', 3306),
    ('doctrace_upgrade', 'db.example', 3310), ('doctrace_backup', 'mysql', 3306)])
def test_initialize_refuses_non_isolated_target_before_connection(database, host, port):
    setup = module()
    with pytest.raises(ValueError):
        setup.validate_target(settings(database, host, port))


@pytest.mark.parametrize('host,port', [('127.0.0.1', 3310), ('localhost', 3310), ('::1', 3310), ('mysql', 3306)])
def test_initialize_accepts_only_documented_isolated_targets(host, port):
    module().validate_target(settings(host=host, port=port))


def test_tables_only_needs_exact_database_confirmation():
    setup = module()
    with pytest.raises(ValueError):
        setup.validate_target(settings('doctrace', port=3306), tables_only=True)
    setup.validate_target(settings('doctrace', port=3306), tables_only=True, confirm_database='doctrace')


def test_initialize_requires_explicit_admin_before_creating_tables(tmp_path):
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'test.db'))
    with pytest.raises(ValueError):
        module().initialize(engine, settings())
    assert inspect(engine).get_table_names() == []
    engine.dispose()


def test_initialize_creates_compatible_tables_unicode_and_explicit_admin(tmp_path):
    setup = module()
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'test.db'))
    result = setup.initialize(engine, settings(), admin_username='upgrade_admin', password='Upgrade!Password42')
    required = {'app_users', 'app_sessions', 'qa_records', 'public_examples', 'product_roles',
        'product_conversations', 'product_messages', 'product_feedback', 'managed_documents', 'managed_document_versions',
        'managed_index_jobs', 'managed_worker_lock'}
    assert required <= set(inspect(engine).get_table_names())
    from app.users import get_user_by_username
    from app.product.repository import get_role
    user = get_user_by_username(engine, 'upgrade_admin')
    assert user and get_role(engine, user['user_id']) == 'admin'
    from app.qa_records import create_processing_record, get_qa_record
    rid = create_processing_record(engine, question='中文政策 🇨🇳', corpus_id='offline', owner_user_id=user['user_id'])
    assert get_qa_record(engine, rid, owner_user_id=user['user_id'])['question'] == '中文政策 🇨🇳'
    assert result['admin_created'] is True
    assert 'password' not in result
    engine.dispose()


def test_repeat_setup_preserves_existing_password_hash(tmp_path):
    setup = module()
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'test.db'))
    setup.initialize(engine, settings(), admin_username='upgrade_admin', password='First!Password42')
    from app.users import get_user_by_username
    before = get_user_by_username(engine, 'upgrade_admin')['password_hash']
    setup.initialize(engine, settings(), admin_username='upgrade_admin', password='Different!Password42')
    after = get_user_by_username(engine, 'upgrade_admin')['password_hash']
    assert before == after
    engine.dispose()


def test_existing_normal_user_requires_explicit_grant(tmp_path):
    setup = module()
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'test.db'))
    setup.initialize(engine, settings(), admin_username='upgrade_admin', password='First!Password42')
    from app.users import create_user
    from app.product.repository import get_role
    user = create_user(engine, username='normal_user', password='Normal!Password42')
    with pytest.raises(ValueError):
        setup.initialize(engine, settings(), admin_username='normal_user', password='Unused!Password42')
    assert get_role(engine, user) == 'user'
    setup.initialize(engine, settings(), admin_username='normal_user', grant_existing_admin=True)
    assert get_role(engine, user) == 'admin'
    engine.dispose()


def test_tables_only_never_creates_legacy_tables(tmp_path):
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'test.db'))
    module().initialize(engine, settings('doctrace', port=3306), tables_only=True, confirm_database='doctrace')
    names = set(inspect(engine).get_table_names())
    assert 'product_roles' in names and 'managed_documents' in names
    assert not names.intersection({'app_users', 'app_sessions', 'qa_records', 'public_examples'})
    engine.dispose()


def test_normal_account_creation_never_gets_admin_role(tmp_path):
    setup = module()
    engine = create_engine('sqlite+pysqlite:///' + str(tmp_path / 'test.db'))
    setup.initialize(engine, settings(), admin_username='upgrade_admin', password='Admin!Password42')
    setup.create_normal_user(engine, username='normal_user', password='Normal!Password42')
    from app.users import get_user_by_username
    from app.product.repository import get_role
    assert get_role(engine, get_user_by_username(engine, 'normal_user')['user_id']) == 'user'
    engine.dispose()


def config_module():
    path = ROOT / 'scripts/init_upgrade_config.py'
    assert path.exists(), 'Private upgrade config generator is missing'
    spec = importlib.util.spec_from_file_location('init_upgrade_config', path)
    imported = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(imported)
    return imported


def test_private_config_only_copies_provider_allowlist_and_never_overwrites(tmp_path):
    from dotenv import dotenv_values
    source = tmp_path / 'source.env'
    source.write_text('ANSWER_API_KEY=secret-provider-value\nANSWER_URL=https://provider.invalid/chat\n'
        'ANSWER_MODEL=synthetic\nMYSQL_PASSWORD=original-db-secret\nEXTRA_PRIVATE=do-not-copy\n', encoding='utf-8')
    target = tmp_path / 'runtime/upgrade/.env'
    config_module().generate(source, target)
    values = dotenv_values(target, interpolate=False)
    assert values['MYSQL_DATABASE'] == 'doctrace_upgrade'
    assert values['MYSQL_PORT'] == '3310'
    assert values['AUTH_ALLOWED_ORIGIN'] == 'http://127.0.0.1:8005'
    assert values['DOCTRACE_SESSION_COOKIE'] == 'doctrace_upgrade_session'
    assert values['ANSWER_API_KEY'] == 'secret-provider-value'
    assert values['MYSQL_PASSWORD'] != 'original-db-secret'
    assert len(values['MYSQL_PASSWORD']) >= 24 and len(values['UPGRADE_ADMIN_PASSWORD']) >= 20
    assert 'EXTRA_PRIVATE' not in values
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        config_module().generate(source, target)
    assert target.read_bytes() == original


def test_cli_rejection_does_not_print_password_or_connect(monkeypatch, capsys):
    setup = module()
    monkeypatch.setenv('UPGRADE_ADMIN_PASSWORD', 'private-never-printed')
    monkeypatch.setattr(setup, 'load_database_settings', lambda env_path: settings('doctrace', port=3306))
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid target attempted a database connection')
    monkeypatch.setattr(setup, 'create_db_engine', forbidden)
    assert setup.main(['--initialize', '--admin', 'upgrade_admin']) == 1
    assert 'private-never-printed' not in capsys.readouterr().out
