import json
import pytest
import httpx2 as httpx
from test_knowledge_repository import repo


def client(handler):
    from app.knowledge.upstream import ManagedClient, ManagedSettings
    return ManagedClient(ManagedSettings('http://127.0.0.1:9631', 'test-secret'), transport=httpx.MockTransport(handler))


def health():
    return httpx.Response(200, json={'status': 'healthy', 'webui_title': 'DocTrace Managed Knowledge v1',
        'configuration': {'workspace': 'doctrace_managed_v1'}})


def test_config_rejects_frozen_and_nonlocal_targets(tmp_path, monkeypatch):
    from app.knowledge.upstream import load_managed_settings
    monkeypatch.setenv('MANAGED_LIGHTRAG_API_KEY', 'secret')
    for url in ['http://localhost:9624', 'http://localhost:9622', 'http://localhost:9623',
                'http://localhost:9630', 'http://evil.example:9631', 'http://localhost:9631/query', 'http://localhost:9631?x=1']:
        monkeypatch.setenv('MANAGED_LIGHTRAG_URL', url)
        with pytest.raises(ValueError):
            load_managed_settings(tmp_path / 'absent.env')
    monkeypatch.delenv('MANAGED_LIGHTRAG_URL')
    with pytest.raises(ValueError):
        load_managed_settings(tmp_path / 'absent.env')


def test_health_mismatch_prevents_upload(repo):
    from app.knowledge.worker import run_once
    task = repo.enqueue(repo.create('a.md', 'a')['doc_id'])
    calls = []
    def handle(req):
        calls.append(req.method)
        return httpx.Response(200, json={'status': 'healthy', 'webui_title': 'Frozen corpus'})
    run_once(repo, client(handle))
    assert calls == ['GET']
    assert repo.task(task['task_id'])['state'] == 'failed'
    assert repo.task(task['task_id'])['failure'] == 'upstream_identity_mismatch'


def test_submission_unknown_never_automatically_requeues(repo):
    from app.knowledge.worker import run_once
    doc = repo.create('a.md', 'a')
    task = repo.enqueue(doc['doc_id'])
    posts = []
    def handle(req):
        if req.url.path == '/health':
            return health()
        posts.append(req)
        raise httpx.ReadTimeout('secret provider exception', request=req)
    run_once(repo, client(handle))
    assert repo.task(task['task_id'])['state'] == 'submission_unknown'
    assert 'secret' not in str(repo.tasks())
    assert repo.enqueue(doc['doc_id'])['task_id'] == task['task_id']
    assert not run_once(repo, client(handle))
    assert len(posts) == 1


def test_upload_poll_processed_and_retirement_need_confirmation(repo):
    from app.knowledge.worker import run_once
    doc = repo.create('a.md', 'hello')
    task = repo.enqueue(doc['doc_id'])
    stage = {'deleted': False}
    def handle(req):
        assert req.headers['X-API-Key'] == 'test-secret'
        if req.url.path == '/health':
            return health()
        if req.method == 'POST':
            payload = json.loads(req.content)
            assert payload == {'text': 'hello', 'file_source': doc['doc_id'] + '_v1_a.md'}
            return httpx.Response(200, json={'status': 'success', 'track_id': 'track-1'})
        if req.method == 'DELETE':
            assert json.loads(req.content) == {'doc_ids': ['upstream-1'], 'delete_file': False, 'delete_llm_cache': False}
            return httpx.Response(200, json={'status': 'deletion_started'})
        rows = [] if stage['deleted'] else [{'id': 'upstream-1', 'status': 'processed', 'file_path': doc['doc_id'] + '_v1_a.md'}]
        return httpx.Response(200, json={'track_id': 'track-1', 'documents': rows, 'total_count': len(rows)})
    upstream = client(handle)
    run_once(repo, upstream)
    assert repo.get(doc['doc_id'])['state'] == 'indexing'
    run_once(repo, upstream)
    assert repo.task(task['task_id'])['state'] == 'processed'
    assert repo.get(doc['doc_id'])['active_version'] == 1
    repo.retire(doc['doc_id'])
    run_once(repo, upstream)
    assert repo.get(doc['doc_id'])['state'] == 'retiring'
    run_once(repo, upstream)
    assert repo.get(doc['doc_id'])['state'] == 'retiring'
    stage['deleted'] = True
    run_once(repo, upstream)
    assert repo.get(doc['doc_id'])['state'] == 'retired'


def test_foreign_poll_result_cannot_activate_document(repo):
    from app.knowledge.worker import run_once
    doc = repo.create('a.md', 'hello')
    task = repo.enqueue(doc['doc_id'])
    def handle(req):
        if req.url.path == '/health':
            return health()
        if req.method == 'POST':
            return httpx.Response(200, json={'status': 'success', 'track_id': 'track-1'})
        return httpx.Response(200, json={'track_id': 'track-1', 'documents': [{'id': 'foreign', 'status': 'processed', 'file_path': 'foreign.txt'}], 'total_count': 1})
    run_once(repo, client(handle))
    run_once(repo, client(handle))
    assert repo.get(doc['doc_id'])['active_version'] is None
    assert repo.task(task['task_id'])['state'] == 'indexing'


def test_failed_poll_uses_safe_failure_and_requires_explicit_retry(repo):
    from app.knowledge.worker import run_once
    doc = repo.create('a.md', 'hello')
    task = repo.enqueue(doc['doc_id'])
    def handle(req):
        if req.url.path == '/health':
            return health()
        if req.method == 'POST':
            return httpx.Response(200, json={'status': 'success', 'track_id': 'track-1'})
        return httpx.Response(200, json={'track_id': 'track-1', 'documents': [{'id': 'upstream-1', 'status': 'failed',
            'file_path': doc['doc_id'] + '_v1_a.md', 'error_msg': 'provider key secret'}], 'total_count': 1})
    run_once(repo, client(handle))
    run_once(repo, client(handle))
    assert repo.task(task['task_id'])['failure'] == 'upstream_processing_failed'
    assert not run_once(repo, client(handle))
    # Retain upstream identity for deletion; uncertain partial data must be reconciled.
    assert repo.get(doc['doc_id'])['upstream_id'] == 'upstream-1'


def test_poll_outage_preserves_track_and_never_uploads_again(repo):
    from app.knowledge.worker import run_once
    doc = repo.create('a.md', 'hello')
    task = repo.enqueue(doc['doc_id'])
    count = {'post': 0}
    def handle(req):
        if req.url.path == '/health':
            return health()
        if req.method == 'POST':
            count['post'] += 1
            return httpx.Response(200, json={'status': 'success', 'track_id': 'track-1'})
        raise httpx.ConnectError('offline', request=req)
    for _ in range(3):
        run_once(repo, client(handle))
    assert repo.task(task['task_id'])['state'] == 'indexing'
    assert repo.get(doc['doc_id'])['track_id'] == 'track-1'
    assert count['post'] == 1
