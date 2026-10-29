import pytest


def test_managed_query_only_uses_active_approved_source_names(record_engine):
    from app.knowledge.repository import metadata, KnowledgeRepository, documents, versions
    from app.managed_query import active_sources, filter_active_chunks
    metadata.create_all(record_engine)
    repo = KnowledgeRepository(record_engine)
    doc = repo.create('policy.md', 'A complete source policy.')
    with record_engine.begin() as conn:
        conn.execute(documents.update().values(active_version=1, state='processed'))
        conn.execute(versions.update().values(state='processed', upstream_id='upstream-doc'))
    active, fingerprint = active_sources(record_engine)
    source = next(iter(active))
    chunks = [{'chunk_id': 'valid', 'file_path': source, 'content': 'A complete source policy.'},
              {'chunk_id': 'old', 'file_path': 'unknown.md', 'content': 'An expired version.'}]
    assert [c['chunk_id'] for c in filter_active_chunks(chunks, active)] == ['valid']
    assert fingerprint.startswith('managed-')
    repo.retire(doc['doc_id'])
    assert active_sources(record_engine)[0] == {}


def test_wrong_workspace_urls_fail_closed_before_any_request():
    from app.knowledge.upstream import ManagedSettings
    from app.config import ConfigurationError
    with pytest.raises(ConfigurationError):
        ManagedSettings('http://127.0.0.1:9624', 'test-key')


def test_container_managed_target_has_exact_guard():
    from app.knowledge.upstream import ManagedSettings
    from app.config import ConfigurationError
    assert ManagedSettings('http://host.docker.internal:9631', 'test-key').url.endswith(':9631')
    with pytest.raises(ConfigurationError):
        ManagedSettings('http://host.docker.internal:9624', 'test-key')


def test_empty_managed_corpus_does_not_call_retrieval_or_model(record_engine):
    from app.knowledge.repository import metadata
    from app.managed_query import run_managed_pipeline
    metadata.create_all(record_engine)
    class Forbidden:
        def post(self, *args, **kwargs):
            raise AssertionError('Empty active corpus must not invoke a provider')
    result = run_managed_pipeline(record_engine, 'What is the rule?', 'naive', Forbidden(), None, None, None)
    assert result.llm_generated is False and result.references == []


def test_managed_snapshot_changed_before_retrieval_fails_closed(record_engine, monkeypatch):
    import app.managed_query as module
    from app.lightrag_client import UpstreamError
    monkeypatch.setattr(module, 'active_sources', lambda engine: ({'new.md': {}}, 'managed-new'))
    with pytest.raises(UpstreamError) as caught:
        module.run_managed_pipeline(record_engine, 'rule?', 'naive', None, None, None, None,
                                    expected_fingerprint='managed-old')
    assert caught.value.status_code == 409


def test_managed_snapshot_changed_during_generation_is_not_returned(record_engine, monkeypatch):
    import app.managed_query as module
    from app.lightrag_client import UpstreamError
    from types import SimpleNamespace
    snapshots = iter([({'policy.md': {}}, 'same'), ({'policy.md': {}}, 'same'), ({}, 'changed')])
    monkeypatch.setattr(module, 'active_sources', lambda engine: next(snapshots))
    monkeypatch.setattr(module, 'collect_retrieval', lambda *a, **kw: {'chunks': [{'file_path': 'policy.md'}]})
    monkeypatch.setattr(module, 'require_stage_success', lambda *a: None)
    monkeypatch.setattr(module, 'collect_rerank', lambda *a: {'error_kind': None, 'ranked_chunks': []})
    monkeypatch.setattr(module, 'select_context', lambda *a, **kw: {'selected_chunks': [{'content': 'policy'}]})
    monkeypatch.setattr(module, 'build_evidence_context', lambda *a: 'policy')
    monkeypatch.setattr(module, 'collect_answer', lambda *a: {'result': {
        'response': 'Answer from withdrawn policy', 'references': [], 'llm_generated': True, 'response_time': 1}})
    with pytest.raises(UpstreamError):
        module.run_managed_pipeline(record_engine, 'rule?', 'naive', None,
                                    SimpleNamespace(url='http://127.0.0.1:9631', api_key='test'), None, None)
