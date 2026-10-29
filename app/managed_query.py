"""Query only published active managed-policy versions; never use the frozen corpus for writes."""
import hashlib
import json
import time
from contextlib import nullcontext

from fastapi import HTTPException
from sqlalchemy import select

from .config import Settings
from .context_builder import build_evidence_context
from .context_selection import select_context
from .answer_client import collect_answer
from .retrieval_client import collect_retrieval
from .rerank_client import collect_rerank
from .qa_pipeline import require_stage_success, insufficient_evidence_response
from .recorded_qa import run_recorded_qa, RecordedQAError
from .schemas import MediumAskResponse, RecordedAskResponse
from .knowledge.repository import documents, versions, CORPUS_ID
from .knowledge.upstream import load_managed_settings, ManagedClient
from .qa_logging import qa_stage


def active_sources(engine):
    statement = select(versions).join(documents, versions.c.doc_id == documents.c.doc_id).where(
        documents.c.corpus_id == CORPUS_ID,
        documents.c.active_version == versions.c.version,
        versions.c.state == 'processed',
        documents.c.state.not_in(['retiring', 'retired']))
    with engine.connect() as conn:
        rows = conn.execute(statement).mappings().all()
    active = {ManagedClient.file_source(row): dict(row) for row in rows}
    fingerprint = 'managed-' + hashlib.sha256(json.dumps(sorted((key, value['content_hash'])
        for key, value in active.items())).encode()).hexdigest()[:24]
    return active, fingerprint


def filter_active_chunks(chunks, active):
    # Match exact server-assigned sources; never accept a path supplied by the browser.
    return [dict(chunk) for chunk in chunks if chunk.get('file_path') in active]


def require_snapshot(actual, expected):
    if actual != expected:
        from .lightrag_client import UpstreamError
        raise UpstreamError(409, '知识库在处理期间已更新，请发起新的问题。', stage='知识库版本')


def run_managed_pipeline(engine, question, mode, client, settings, rerank_settings, answer_settings,
                         *, expected_fingerprint=None):
    started = time.perf_counter()
    active, fingerprint = active_sources(engine)
    if expected_fingerprint is not None:
        require_snapshot(fingerprint, expected_fingerprint)
    if not active:
        result = insufficient_evidence_response(started)
        return MediumAskResponse(**result.model_dump(), retrieval={
            'mode': mode, 'policy_version': fingerprint, 'strategy': 'no_active_managed_documents', 'degraded': False})
    with qa_stage('托管库检索'):
        retrieval = collect_retrieval(client, Settings(settings.url, settings.api_key), question,
                                      mode=mode, max_total_tokens=40000)
        require_stage_success(retrieval, '检索')
        chunks = filter_active_chunks(retrieval['chunks'], active)
    if not chunks:
        result = insufficient_evidence_response(started)
        return MediumAskResponse(**result.model_dump(), retrieval={
            'mode': mode, 'policy_version': fingerprint, 'strategy': 'active_source_filter_empty', 'degraded': False})
    with qa_stage('托管库重排'):
        rerank = collect_rerank(client, rerank_settings, question, chunks)
        degraded = rerank['error_kind'] is not None
        ranked = rerank['ranked_chunks'] if not degraded else [{**chunk, 'rerank_score': 1.0} for chunk in chunks]
        selection = select_context(ranked, max_chars=30000, min_score=0 if degraded else .3)
    require_snapshot(active_sources(engine)[1], fingerprint)
    selected = selection['selected_chunks']
    if not selected:
        result = insufficient_evidence_response(started)
    else:
        with qa_stage('回答模型'):
            generated = collect_answer(client, answer_settings, question, build_evidence_context(selected))
            require_stage_success(generated, '回答模型')
        from .schemas import AskResponse
        result = AskResponse.model_validate(generated['result'])
    require_snapshot(active_sources(engine)[1], fingerprint)
    return MediumAskResponse(**result.model_dump(), retrieval={
        'mode': mode, 'policy_version': fingerprint, 'strategy': 'managed_active_vector_graph_rerank', 'degraded': degraded})


def managed_runner(*, request, http_request, user, idempotency_key):
    from .main import make_qa_client
    from .answer_config import load_answer_settings
    from .rerank_config import load_rerank_settings
    engine = http_request.app.state.db_engine
    active, fingerprint = active_sources(engine)
    def answer_fn():
        if not active:
            # A truthful local refusal requires neither supplier credentials nor network.
            return run_managed_pipeline(engine, request.question, request.mode, None, None, None, None,
                                        expected_fingerprint=fingerprint)
        settings = load_managed_settings()
        answer, rerank = load_answer_settings(), load_rerank_settings()
        admission = getattr(http_request.app.state, 'qa_admission', None)
        with (admission.slot(str(user.user_id)) if admission else nullcontext()), make_qa_client() as client:
            return run_managed_pipeline(engine, request.question, request.mode, client, settings, rerank, answer,
                                        expected_fingerprint=fingerprint)
    try:
        record_id, result = run_recorded_qa(engine, question=request.question, corpus_id=fingerprint,
            answer_fn=answer_fn, owner_user_id=str(user.user_id), idempotency_key=str(idempotency_key), request_mode=request.mode)
    except RecordedQAError as error:
        http_request.state.qa_record_id = error.request_id
        raise HTTPException(error.status_code, {'message': error.detail, 'request_id': error.request_id}) from None
    http_request.state.qa_record_id = record_id
    return RecordedAskResponse(request_id=record_id, **result.model_dump())
