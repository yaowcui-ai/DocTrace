"""Explicit bootstrap for the isolated upgrade database. No import-time writes."""
import argparse
from getpass import GetPassWarning, getpass
import os
from pathlib import Path
import warnings

from dotenv import dotenv_values
from sqlalchemy import (MetaData, Table, Column, String, Text, DateTime, Boolean,
    Integer, BigInteger, JSON, ForeignKey, UniqueConstraint, CheckConstraint, Index, Computed, select)
from sqlalchemy.dialects.mysql import MEDIUMTEXT, DATETIME
from sqlalchemy.exc import SQLAlchemyError

from .config import ConfigurationError, DEFAULT_ENV_PATH
from .database import create_db_engine
from .database_config import load_database_settings
from .users import create_user, get_user_by_username
from .product.tables import metadata as product_metadata, roles

ISOLATED_DATABASE = 'doctrace_upgrade'
PRIVATE_ENV = Path(__file__).resolve().parents[1] / 'runtime/upgrade/.env'
legacy_metadata = MetaData()
timestamp = DateTime().with_variant(DATETIME(fsp=6), 'mysql')
large_text = Text().with_variant(MEDIUMTEXT(), 'mysql')
table_options = dict(mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_0900_ai_ci')

app_users = Table('app_users', legacy_metadata,
    Column('user_id', String(36), primary_key=True), Column('username', String(32), nullable=False, unique=True),
    Column('password_hash', String(255), nullable=False), Column('is_active', Boolean, nullable=False, server_default='1'),
    Column('created_at', timestamp, nullable=False), Column('updated_at', timestamp, nullable=False),
    CheckConstraint('is_active IN (0, 1)', name='chk_app_users_active'), **table_options)
app_sessions = Table('app_sessions', legacy_metadata,
    Column('session_id', String(36), primary_key=True), Column('token_hash', String(64), nullable=False, unique=True),
    Column('user_id', String(36), ForeignKey('app_users.user_id'), nullable=False),
    Column('created_at', timestamp, nullable=False), Column('expires_at', timestamp, nullable=False), Column('revoked_at', timestamp),
    Index('idx_app_sessions_user', 'user_id'), Index('idx_app_sessions_expiry', 'expires_at'),
    CheckConstraint('expires_at > created_at', name='chk_app_sessions_expiry'), **table_options)
qa_records = Table('qa_records', legacy_metadata,
    Column('request_id', String(36), primary_key=True),
    Column('owner_user_id', String(36), ForeignKey('app_users.user_id')),
    Column('idempotency_key', String(36)),
    Column('legacy_idempotency_key', String(36), Computed(
        'CASE WHEN owner_user_id IS NULL THEN idempotency_key ELSE NULL END', persisted=True)),
    Column('question', Text, nullable=False), Column('answer', large_text),
    Column('references_json', JSON), Column('retrieval_json', JSON),
    Column('corpus_id', String(64), nullable=False), Column('request_mode', String(8), nullable=False, server_default='mix'),
    Column('status', String(20), nullable=False, server_default='processing'), Column('http_status', Integer),
    Column('error_stage', String(32)), Column('error_message', Text), Column('llm_generated', Boolean),
    Column('duration_ms', BigInteger), Column('created_at', timestamp, nullable=False), Column('updated_at', timestamp, nullable=False),
    UniqueConstraint('owner_user_id', 'idempotency_key', name='uq_qa_records_owner_key'),
    UniqueConstraint('legacy_idempotency_key', name='uq_qa_records_legacy_key'),
    Index('ix_qa_records_owner_created', 'owner_user_id', 'created_at', 'request_id'),
    CheckConstraint("status IN ('processing', 'completed', 'failed')", name='chk_qa_records_status'),
    CheckConstraint('duration_ms IS NULL OR duration_ms >= 0', name='chk_qa_records_duration'), **table_options)
public_examples = Table('public_examples', legacy_metadata,
    Column('example_id', String(36), primary_key=True), Column('question', Text, nullable=False),
    Column('answer', large_text, nullable=False), Column('references_json', JSON, nullable=False),
    Column('corpus_id', String(64), nullable=False), Column('status', String(20), nullable=False, server_default='draft'),
    Column('created_at', timestamp, nullable=False), Column('updated_at', timestamp, nullable=False), Column('published_at', timestamp),
    Index('idx_public_examples_status_published', 'status', 'published_at', 'example_id'),
    CheckConstraint("status IN ('draft', 'published', 'withdrawn')", name='chk_public_examples_status'),
    CheckConstraint("status <> 'published' OR published_at IS NOT NULL", name='chk_public_examples_published_time'), **table_options)


def validate_target(settings, *, tables_only=False, confirm_database=None):
    if tables_only:
        if not confirm_database or confirm_database != settings.database:
            raise ValueError('Tables-only setup requires --confirm-database matching MYSQL_DATABASE exactly.')
        return
    allowed = ((settings.host in {'127.0.0.1', 'localhost', '::1'} and settings.port == 3310)
        or (settings.host == 'mysql' and settings.port == 3306))
    if settings.database != ISOLATED_DATABASE or not allowed:
        raise ValueError('Initialization only supports doctrace_upgrade on loopback:3310 or Compose mysql:3306.')


def _grant_admin(engine, user_id):
    with engine.begin() as conn:
        existing = conn.execute(select(roles.c.role).where(roles.c.user_id == user_id)).scalar_one_or_none()
        if existing is None:
            conn.execute(roles.insert().values(user_id=user_id, role='admin'))
        elif existing != 'admin':
            conn.execute(roles.update().where(roles.c.user_id == user_id).values(role='admin'))


def initialize(engine, settings, *, admin_username=None, password=None, grant_existing_admin=False,
        tables_only=False, confirm_database=None):
    validate_target(settings, tables_only=tables_only, confirm_database=confirm_database)
    if tables_only:
        if admin_username:
            raise ValueError('Tables-only mode never creates or elevates accounts.')
    elif not admin_username:
        raise ValueError('Initialization requires an explicit --admin username.')
    if not tables_only:
        legacy_metadata.create_all(engine)
    product_metadata.create_all(engine)
    from .knowledge.repository import metadata as knowledge_metadata
    knowledge_metadata.create_all(engine)
    if tables_only:
        return {'tables_only': True}
    user = get_user_by_username(engine, admin_username)
    created = user is None
    if user is not None:
        if not user['is_active']:
            raise ValueError('Existing inactive accounts cannot be used as the bootstrap administrator.')
        with engine.connect() as conn:
            role = conn.execute(select(roles.c.role).where(roles.c.user_id == user['user_id'])).scalar_one_or_none()
        if role != 'admin' and not grant_existing_admin:
            raise ValueError('Existing ordinary account requires explicit --grant-existing-admin; its password will not change.')
        user_id = user['user_id']
    else:
        if not password:
            raise ValueError('A private password is required to create the administrator.')
        user_id = create_user(engine, username=admin_username, password=password)
    _grant_admin(engine, user_id)
    return {'tables_only': False, 'admin_created': created, 'user_id': user_id}


def create_normal_user(engine, *, username, password):
    existing = get_user_by_username(engine, username)
    if existing is not None:
        raise ValueError('That account already exists; its password and role were not changed.')
    return create_user(engine, username=username, password=password)


def _password(name, prompt, file_values=None):
    value = os.environ.get(name) or (file_values or {}).get(name)
    if value:
        return value
    with warnings.catch_warnings():
        warnings.simplefilter('error', GetPassWarning)
        return getpass(prompt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--initialize', action='store_true')
    operation.add_argument('--tables-only', action='store_true')
    operation.add_argument('--create-user', metavar='USERNAME')
    parser.add_argument('--admin')
    parser.add_argument('--grant-existing-admin', action='store_true')
    parser.add_argument('--confirm-database')
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args(argv)
    engine = None
    try:
        env_path = args.env_file or (PRIVATE_ENV if PRIVATE_ENV.is_file() else DEFAULT_ENV_PATH)
        # All loaders apply OS-over-file precedence without mutating global settings.
        private_values = dotenv_values(env_path, encoding='utf-8', interpolate=False) if env_path.is_file() else {}
        settings = load_database_settings(env_path)
        validate_target(settings, tables_only=args.tables_only, confirm_database=args.confirm_database)
        if args.initialize and not args.admin:
            raise ValueError('Initialization requires --admin.')
        if args.tables_only and args.admin:
            raise ValueError('Tables-only mode never changes accounts.')
        password = None
        if args.initialize:
            password = _password('UPGRADE_ADMIN_PASSWORD', 'Upgrade administrator password (hidden): ', private_values)
        elif args.create_user:
            password = _password('UPGRADE_USER_PASSWORD', 'New ordinary account password (hidden): ', private_values)
        engine = create_db_engine(settings)
        if args.create_user:
            create_normal_user(engine, username=args.create_user, password=password)
        else:
            initialize(engine, settings, admin_username=args.admin, password=password,
                grant_existing_admin=args.grant_existing_admin, tables_only=args.tables_only,
                confirm_database=args.confirm_database)
        print('Upgrade setup completed. No credentials are displayed.')
        return 0
    except (ConfigurationError, ValueError, SQLAlchemyError, GetPassWarning, EOFError):
        print('Upgrade setup refused or unavailable. Check the isolated target, explicit account options, and private configuration.')
        return 1
    except KeyboardInterrupt:
        print('Upgrade setup cancelled.')
        return 130
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
