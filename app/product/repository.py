"""Owner-scoped Core persistence. Legacy QA tables stay outside this metadata."""
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
from uuid import uuid4

from sqlalchemy import and_, or_, column, select, table, func
from sqlalchemy.exc import IntegrityError

from ..schemas import Reference, RetrievalInfo
from .tables import conversations, messages, roles, feedback, message_sources

qa = table('qa_records', *(column(name) for name in (
    'request_id', 'owner_user_id', 'answer', 'references_json', 'retrieval_json',
    'status', 'http_status', 'error_stage', 'error_message', 'llm_generated', 'duration_ms',
    'question', 'request_mode', 'created_at', 'updated_at', 'corpus_id', 'idempotency_key')))


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def public_dates(row):
    result = dict(row)
    for key in ('created_at', 'updated_at'):
        if isinstance(result.get(key), datetime):
            result[key] = result[key].replace(tzinfo=timezone.utc).isoformat()
    return result


def get_role(engine, user_id):
    with engine.connect() as conn:
        role = conn.execute(select(roles.c.role).where(roles.c.user_id == user_id)).scalar_one_or_none()
    return role if role in ('user', 'admin') else 'user'


def create_conversation(engine, owner, title):
    stamp = now()
    row = dict(id=str(uuid4()), owner_user_id=owner, title=title, created_at=stamp, updated_at=stamp)
    with engine.begin() as conn:
        conn.execute(conversations.insert().values(**row))
    return public_dates(row)


def get_conversation(engine, conversation_id, owner):
    with engine.connect() as conn:
        row = conn.execute(select(conversations).where(
            conversations.c.id == conversation_id, conversations.c.owner_user_id == owner)).mappings().first()
    return public_dates(row) if row else None


def list_conversations(engine, owner, query='', limit=30, offset=0):
    statement = select(conversations).where(conversations.c.owner_user_id == owner)
    if query:
        message_match = select(messages.c.id).where(messages.c.conversation_id == conversations.c.id,
            messages.c.owner_user_id == owner, messages.c.question.contains(query, autoescape=True)).exists()
        statement = statement.where(or_(conversations.c.title.contains(query, autoescape=True), message_match))
    statement = statement.order_by(conversations.c.updated_at.desc(), conversations.c.id.desc()).limit(limit + 1).offset(offset)
    with engine.connect() as conn:
        rows = conn.execute(statement).mappings().all()
    return dict(items=[public_dates(row) for row in rows[:limit]], limit=limit, offset=offset,
        has_more=len(rows) > limit, next_offset=offset + limit if len(rows) > limit else None)


def operation_message(engine, owner, key):
    with engine.connect() as conn:
        row = conn.execute(select(messages).where(messages.c.owner_user_id == owner,
            messages.c.operation_key == key)).mappings().first()
    return dict(row) if row else None


def recent_questions(engine, owner, conversation_id, knowledge_base='frozen'):
    with engine.connect() as conn:
        rows = conn.execute(select(messages.c.question).select_from(messages.outerjoin(message_sources,
            message_sources.c.message_id == messages.c.id)).where(messages.c.owner_user_id == owner,
            messages.c.conversation_id == conversation_id,
            func.coalesce(message_sources.c.knowledge_base, 'frozen') == knowledge_base).order_by(messages.c.created_at.desc(),
            messages.c.id.desc()).limit(2)).scalars().all()
    return list(reversed(rows))


def reserve_message(engine, owner, conversation_id, question, mode, key, query_text, context_method, knowledge_base='frozen'):
    row = dict(id=str(uuid4()), conversation_id=conversation_id, owner_user_id=owner,
        request_id=None, operation_key=key, question=question, mode=mode, query_text=query_text,
        context_method=context_method, status='processing', created_at=now())
    try:
        with engine.begin() as conn:
            conn.execute(messages.insert().values(**row))
            conn.execute(message_sources.insert().values(message_id=row['id'], knowledge_base=knowledge_base))
            conn.execute(conversations.update().where(conversations.c.id == conversation_id,
                conversations.c.owner_user_id == owner).values(updated_at=now()))
    except IntegrityError:
        existing = operation_message(engine, owner, key)
        if existing is None:
            raise
        return existing
    return row


def selected_source(engine, message_id):
    with engine.connect() as conn:
        value = conn.execute(select(message_sources.c.knowledge_base).where(message_sources.c.message_id == message_id)).scalar_one_or_none()
    return value or 'frozen'


def attach_record(engine, owner, message_id, record):
    with engine.begin() as conn:
        conn.execute(messages.update().where(messages.c.id == message_id,
            messages.c.owner_user_id == owner).values(request_id=record['request_id'], status=record['status']))


def decode_json(value, default):
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def sanitized_references(value):
    result = []
    for item in decode_json(value, []):
        reference = Reference.model_validate(item).model_dump()
        # Only a display filename crosses the product boundary; never a local source path.
        reference['file_path'] = PurePosixPath(reference['file_path'].replace('\\', '/')).name
        result.append(reference)
    return result


def message_statement(owner):
    return select(messages, func.coalesce(message_sources.c.knowledge_base, 'frozen').label('knowledge_base'), qa.c.corpus_id, qa.c.answer, qa.c.references_json, qa.c.retrieval_json,
        qa.c.status.label('qa_status'), qa.c.http_status, qa.c.error_stage,
        qa.c.llm_generated, qa.c.duration_ms, feedback.c.helpful.label('feedback_helpful'),
        feedback.c.comment.label('feedback_comment')).select_from(messages.outerjoin(qa, and_(
            messages.c.request_id == qa.c.request_id, qa.c.owner_user_id == owner)).outerjoin(feedback,
            and_(feedback.c.request_id == qa.c.request_id, feedback.c.user_id == owner)).outerjoin(message_sources,
            message_sources.c.message_id == messages.c.id)).where(
                messages.c.owner_user_id == owner,
                or_(messages.c.request_id.is_(None), qa.c.request_id.is_not(None)))


def serialize_message(row):
    result = public_dates(row)
    result['status'] = result.pop('qa_status') or result['status']
    result['references'] = sanitized_references(result.pop('references_json'))
    retrieval = decode_json(result.pop('retrieval_json'), None)
    result['retrieval'] = RetrievalInfo.model_validate(retrieval).model_dump() if retrieval is not None else None
    result['historical_import'] = result['context_method'] == 'legacy_import'
    result['actual_mode'] = (result['retrieval']['mode'] if result['retrieval'] is not None
        and result['retrieval']['mode'] in ('naive', 'mix') else None if result['historical_import'] else result['mode'])
    helpful, comment = result.pop('feedback_helpful'), result.pop('feedback_comment')
    result['feedback'] = {'helpful': bool(helpful), 'comment': comment} if helpful is not None else None
    if result['llm_generated'] is not None:
        result['llm_generated'] = bool(result['llm_generated'])
    result.pop('operation_key', None)
    result.pop('owner_user_id', None)
    return result


def get_message(engine, owner, *, message_id=None, request_id=None):
    statement = message_statement(owner)
    statement = statement.where(messages.c.id == message_id) if message_id else statement.where(messages.c.request_id == request_id)
    with engine.connect() as conn:
        row = conn.execute(statement).mappings().first()
    return serialize_message(row) if row else None


def list_messages(engine, owner, conversation_id, limit=100, offset=0):
    statement = message_statement(owner).where(messages.c.conversation_id == conversation_id).order_by(
        messages.c.created_at.desc(), messages.c.id.desc()).limit(limit + 1).offset(offset)
    with engine.connect() as conn:
        rows = conn.execute(statement).mappings().all()
    return [serialize_message(row) for row in reversed(rows[:limit])], len(rows) > limit


def save_feedback(engine, owner, request_id, helpful, comment):
    values = dict(helpful=helpful, comment=comment, updated_at=now())
    criteria = and_(feedback.c.request_id == request_id, feedback.c.user_id == owner)
    try:
        with engine.begin() as conn:
            existing = conn.execute(select(feedback.c.request_id).where(criteria)).first()
            if existing:
                conn.execute(feedback.update().where(criteria).values(**values))
            else:
                conn.execute(feedback.insert().values(request_id=request_id, user_id=owner, **values))
    except IntegrityError:
        # Concurrent first PUTs race on the composite primary key; last committed update wins.
        with engine.begin() as conn:
            conn.execute(feedback.update().where(criteria).values(**values))
    return public_dates(dict(request_id=request_id, helpful=helpful, comment=comment, updated_at=values['updated_at']))


def import_legacy_records(engine, owner, limit=100):
    """Create product associations only; existing private QA rows are never changed."""
    joined = qa.outerjoin(messages, or_(messages.c.request_id == qa.c.request_id,
        and_(messages.c.owner_user_id == qa.c.owner_user_id,
             messages.c.operation_key == qa.c.idempotency_key)))
    eligible = select(qa.c.request_id, qa.c.question, qa.c.request_mode, qa.c.status,
        qa.c.created_at, qa.c.updated_at).select_from(joined).where(
            qa.c.owner_user_id == owner, messages.c.id.is_(None)).order_by(
                qa.c.created_at.desc(), qa.c.request_id.desc()).limit(limit + 1)
    with engine.connect() as conn:
        rows = conn.execute(eligible).mappings().all()
        skipped = conn.execute(select(func.count(func.distinct(qa.c.request_id))).select_from(joined).where(
            qa.c.owner_user_id == owner, messages.c.id.is_not(None))).scalar_one()
    imported = 0
    for row in rows[:limit]:
        conversation_id = str(uuid4())
        created = row['created_at']
        updated = row['updated_at']
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        if isinstance(updated, str):
            updated = datetime.fromisoformat(updated)
        try:
            with engine.begin() as conn:
                conn.execute(conversations.insert().values(id=conversation_id, owner_user_id=owner,
                    title=row['question'].strip()[:100] or '历史问答', created_at=created, updated_at=updated))
                conn.execute(messages.insert().values(id=str(uuid4()), conversation_id=conversation_id,
                    owner_user_id=owner, request_id=row['request_id'], operation_key=str(uuid4()),
                    question=row['question'], mode=row['request_mode'], query_text=row['question'],
                    context_method='legacy_import', status=row['status'], created_at=created))
        except IntegrityError:
            # A concurrent import may already have linked this exact request. Its
            # unique request_id rolls back the conversation and message together.
            with engine.connect() as conn:
                associated = conn.execute(select(messages.c.id).where(
                    messages.c.request_id == row['request_id'])).first()
            if associated is None:
                raise
            skipped += 1
        else:
            imported += 1
    return {'imported': imported, 'skipped': skipped, 'has_more': len(rows) > limit}
