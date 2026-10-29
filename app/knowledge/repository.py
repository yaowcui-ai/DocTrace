"""SQLAlchemy Core persistence; DDL is invoked only by the product migration CLI."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import PurePath
from unicodedata import category
from uuid import uuid4

from sqlalchemy import (MetaData, Table, Column, String, Integer, Text, DateTime,
                        UniqueConstraint, ForeignKey, select, update, insert)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.exc import IntegrityError

CORPUS_ID = 'doctrace_managed_v1'
metadata = MetaData()
documents = Table('managed_documents', metadata,
    Column('doc_id', String(36), primary_key=True),
    Column('corpus_id', String(64), nullable=False),
    Column('version', Integer, nullable=False),
    Column('active_version', Integer),
    Column('state', String(32), nullable=False),
    Column('created_at', DateTime, nullable=False), Column('updated_at', DateTime, nullable=False))
versions = Table('managed_document_versions', metadata,
    Column('version_id', String(36), primary_key=True),
    Column('doc_id', String(36), ForeignKey('managed_documents.doc_id'), nullable=False),
    Column('version', Integer, nullable=False), Column('filename', String(255), nullable=False),
    Column('content', Text().with_variant(LONGTEXT(), 'mysql'), nullable=False),
    Column('content_hash', String(64), nullable=False, unique=True),
    Column('state', String(32), nullable=False), Column('upstream_id', String(255)),
    Column('track_id', String(255)), Column('failure', String(80)),
    UniqueConstraint('doc_id', 'version', name='uq_managed_doc_version'))
jobs = Table('managed_index_jobs', metadata,
    Column('task_id', String(36), primary_key=True),
    Column('version_id', String(36), ForeignKey('managed_document_versions.version_id'), nullable=False),
    Column('kind', String(16), nullable=False), Column('state', String(32), nullable=False),
    Column('failure', String(80)), Column('created_at', DateTime, nullable=False),
    Column('updated_at', DateTime, nullable=False))
locks = Table('managed_worker_lock', metadata,
    Column('corpus_id', String(64), primary_key=True), Column('owner', String(36)))


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def validate_document(filename, content):
    if not isinstance(filename, str) or not isinstance(content, str):
        raise ValueError('文件名及正文必须为文本。')
    if (not filename or filename.startswith('.') or filename != filename.strip()
            or len(filename) > 180 or any(c in filename for c in '/\\:')
            or any(category(c).startswith('C') or c in '\ufffe\uffff' for c in filename)
            or PurePath(filename).suffix.lower() not in {'.txt', '.md'}):
        raise ValueError('仅支持安全文件名的 .txt 或 .md 文件。')
    try:
        encoded = content.encode('utf-8', errors='strict')
        filename.encode('utf-8', errors='strict')
    except UnicodeError:
        raise ValueError('文件必须为有效 UTF-8 文本。') from None
    if not content.strip() or len(encoded) > 1048576 or '\x00' in content:
        raise ValueError('正文不能为空，且 UTF-8 大小须不超过 1 MiB。')
    # LightRAG strips whitespace before content-addressing; match that identity.
    return sha256(content.strip().encode('utf-8')).hexdigest()


class KnowledgeRepository:
    def __init__(self, engine):
        self.engine = engine

    def _doc(self, conn, doc_id, *, lock=False):
        stmt = select(documents).where(documents.c.doc_id == doc_id)
        row = conn.execute(stmt.with_for_update() if lock else stmt).mappings().first()
        if row is None:
            raise KeyError(doc_id)
        return dict(row)

    def _version(self, conn, doc):
        return dict(conn.execute(select(versions).where(versions.c.doc_id == doc['doc_id'],
            versions.c.version == doc['version'])).mappings().one())

    def get(self, doc_id):
        with self.engine.connect() as conn:
            doc = self._doc(conn, doc_id)
            version = self._version(conn, doc)
            return {**doc, **{k: v for k, v in version.items() if k not in {'state', 'doc_id'}}}

    def list(self):
        with self.engine.connect() as conn:
            ids = conn.execute(select(documents.c.doc_id).order_by(documents.c.created_at.desc()).limit(500)).scalars().all()
        return [{k: v for k, v in self.get(doc_id).items() if k != 'content'} for doc_id in ids]

    def create(self, filename, content):
        digest = validate_document(filename, content)
        try:
            with self.engine.begin() as conn:
                duplicate = conn.execute(select(versions.c.doc_id).where(versions.c.content_hash == digest)).scalar()
                if duplicate:
                    doc_id = duplicate
                else:
                    doc_id = str(uuid4())
                    conn.execute(insert(documents).values(doc_id=doc_id, corpus_id=CORPUS_ID,
                        version=1, state='draft', created_at=now(), updated_at=now()))
                    conn.execute(insert(versions).values(version_id=str(uuid4()), doc_id=doc_id,
                        version=1, filename=filename, content=content, content_hash=digest, state='draft'))
        except IntegrityError:
            # Concurrent equal uploads meet the unique content hash constraint.
            with self.engine.connect() as conn:
                doc_id = conn.execute(select(versions.c.doc_id).where(versions.c.content_hash == digest)).scalar()
            if not doc_id:
                raise
        return self.get(doc_id)

    def update(self, doc_id, filename, content):
        digest = validate_document(filename, content)
        with self.engine.begin() as conn:
            doc = self._doc(conn, doc_id, lock=True)
            old = self._version(conn, doc)
            if digest == old['content_hash']:
                pass
            else:
                if doc['state'] not in {'draft', 'processed', 'failed'}:
                    raise ValueError('文档正在处理或已停用，不能更新。')
                if conn.execute(select(versions.c.version_id).where(versions.c.content_hash == digest)).scalar():
                    raise ValueError('相同正文已存在，请使用现有文档。')
                version = doc['version'] + 1
                conn.execute(insert(versions).values(version_id=str(uuid4()), doc_id=doc_id, version=version,
                    filename=filename, content=content, content_hash=digest, state='draft'))
                conn.execute(update(documents).where(documents.c.doc_id == doc_id).values(
                    version=version, state='draft', updated_at=now()))
        return self.get(doc_id)

    def _new_job(self, conn, version_id, kind):
        task_id = str(uuid4())
        conn.execute(insert(jobs).values(task_id=task_id, version_id=version_id, kind=kind,
            state='queued', created_at=now(), updated_at=now()))
        return task_id

    def enqueue(self, doc_id):
        with self.engine.begin() as conn:
            doc = self._doc(conn, doc_id, lock=True)
            version = self._version(conn, doc)
            existing = conn.execute(select(jobs).where(jobs.c.version_id == version['version_id'],
                jobs.c.kind == 'index').order_by(jobs.c.created_at.desc())).mappings().first()
            if existing and existing['state'] != 'failed':
                return dict(existing)
            if doc['state'] not in {'draft', 'failed'}:
                raise ValueError('文档当前状态不能索引。')
            task_id = self._new_job(conn, version['version_id'], 'index')
            conn.execute(update(documents).where(documents.c.doc_id == doc_id).values(state='queued', updated_at=now()))
            conn.execute(update(versions).where(versions.c.version_id == version['version_id']).values(state='queued', failure=None))
        return self.task(task_id)

    def tasks(self):
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(select(jobs).order_by(jobs.c.created_at.desc()).limit(500)).mappings()]

    def task(self, task_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(jobs).where(jobs.c.task_id == task_id)).mappings().first()
            if not row:
                raise KeyError(task_id)
            return dict(row)

    def job_version(self, task):
        with self.engine.connect() as conn:
            return dict(conn.execute(select(versions).where(versions.c.version_id == task['version_id'])).mappings().one())

    def acquire(self, owner):
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(locks).values(corpus_id=CORPUS_ID))
        except IntegrityError:
            pass
        with self.engine.begin() as conn:
            return conn.execute(update(locks).where(locks.c.corpus_id == CORPUS_ID, locks.c.owner.is_(None)).values(owner=owner)).rowcount == 1

    def release(self, owner):
        with self.engine.begin() as conn:
            conn.execute(update(locks).where(locks.c.corpus_id == CORPUS_ID, locks.c.owner == owner).values(owner=None))

    def claim(self):
        with self.engine.begin() as conn:
            row = conn.execute(select(jobs).where(jobs.c.state.in_(['indexing', 'deleting', 'queued']))
                .order_by(jobs.c.created_at).limit(1)).mappings().first()
            if not row:
                return None
            next_state = 'claimed' if row['state'] == 'queued' else 'polling'
            if conn.execute(update(jobs).where(jobs.c.task_id == row['task_id'], jobs.c.state == row['state'])
                    .values(state=next_state, updated_at=now())).rowcount != 1:
                return None
            return {**dict(row), 'previous_state': row['state'], 'state': next_state}

    def set_job(self, task, state, *, failure=None, track_id=None, upstream_id=None):
        with self.engine.begin() as conn:
            version = dict(conn.execute(select(versions).where(versions.c.version_id == task['version_id'])).mappings().one())
            conn.execute(update(jobs).where(jobs.c.task_id == task['task_id']).values(state=state, failure=failure, updated_at=now()))
            values = {'state': state, 'failure': failure}
            if track_id:
                values['track_id'] = track_id
            if upstream_id:
                values['upstream_id'] = upstream_id
            conn.execute(update(versions).where(versions.c.version_id == task['version_id']).values(**values))
            conn.execute(update(documents).where(documents.c.doc_id == version['doc_id'],
                documents.c.version == version['version'], documents.c.state != 'retiring').values(state=state, updated_at=now()))

    def complete_index(self, task_id, upstream_id):
        with self.engine.begin() as conn:
            task = conn.execute(select(jobs).where(jobs.c.task_id == task_id)).mappings().one()
            version = conn.execute(select(versions).where(versions.c.version_id == task['version_id'])).mappings().one()
            self._doc(conn, version['doc_id'], lock=True)
            conn.execute(update(jobs).where(jobs.c.task_id == task_id).values(state='processed', failure=None, updated_at=now()))
            conn.execute(update(versions).where(versions.c.version_id == version['version_id']).values(state='processed', upstream_id=upstream_id, failure=None))
            conn.execute(update(documents).where(documents.c.doc_id == version['doc_id']).values(state='processed',
                active_version=version['version'], updated_at=now()))
            old_versions = conn.execute(select(versions).where(versions.c.doc_id == version['doc_id'],
                versions.c.version < version['version'], versions.c.state == 'processed')).mappings().all()
            for old in old_versions:
                conn.execute(update(versions).where(versions.c.version_id == old['version_id']).values(state='retiring'))
                self._new_job(conn, old['version_id'], 'delete')

    def retire(self, doc_id):
        with self.engine.begin() as conn:
            doc = self._doc(conn, doc_id, lock=True)
            if doc['state'] in {'retired', 'retiring'}:
                return doc
            if doc['state'] not in {'draft', 'processed', 'failed'}:
                raise ValueError('文档处理结果未确认，不能停用。')
            rows = conn.execute(select(versions).where(versions.c.doc_id == doc_id,
                versions.c.upstream_id.is_not(None), versions.c.state != 'retired')).mappings().all()
            for version in rows:
                if version['state'] not in {'retiring', 'deleting'}:
                    self._new_job(conn, version['version_id'], 'delete')
                    conn.execute(update(versions).where(versions.c.version_id == version['version_id']).values(state='retiring'))
            conn.execute(update(documents).where(documents.c.doc_id == doc_id).values(
                state='retiring' if rows else 'retired', active_version=doc['active_version'] if rows else None, updated_at=now()))
        return self.get(doc_id)

    def complete_delete(self, task):
        with self.engine.begin() as conn:
            version = conn.execute(select(versions).where(versions.c.version_id == task['version_id'])).mappings().one()
            doc = self._doc(conn, version['doc_id'], lock=True)
            conn.execute(update(jobs).where(jobs.c.task_id == task['task_id']).values(state='processed', failure=None, updated_at=now()))
            conn.execute(update(versions).where(versions.c.version_id == task['version_id']).values(state='retired', failure=None))
            remaining = conn.execute(select(versions.c.version_id).where(versions.c.doc_id == version['doc_id'],
                versions.c.upstream_id.is_not(None), versions.c.state != 'retired')).first()
            if doc['state'] == 'retiring' and not remaining:
                conn.execute(update(documents).where(documents.c.doc_id == version['doc_id']).values(state='retired', active_version=None, updated_at=now()))
