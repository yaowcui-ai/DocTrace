import pytest
from sqlalchemy import create_engine, select


@pytest.fixture
def repo(tmp_path):
    from app.knowledge.repository import KnowledgeRepository, metadata
    engine = create_engine('sqlite:///' + str(tmp_path / 'knowledge.db'))
    metadata.create_all(engine)
    yield KnowledgeRepository(engine)
    engine.dispose()


def test_create_deduplicates_content_without_queueing(repo):
    first = repo.create('policy.md', 'The policy')
    second = repo.create('copy.txt', 'The policy')
    assert second['doc_id'] == first['doc_id']
    assert first['corpus_id'] == 'doctrace_managed_v1'
    assert repo.tasks() == []
    assert repo.get(first['doc_id'])['content'] == 'The policy'


@pytest.mark.parametrize('filename', ['../a.md', '/a.txt', 'C:a.txt', 'a\\b.md', '.hidden.md', 'x\x00.md', 'x.pdf'])
def test_rejects_unsafe_names(repo, filename):
    with pytest.raises(ValueError):
        repo.create(filename, 'policy')


def test_rejects_empty_oversized_and_invalid_utf8(repo):
    for content in (' ', '中' * 350000, '\ud800'):
        with pytest.raises(ValueError):
            repo.create('policy.md', content)


def test_rejects_unicode_controls_and_graph_unsafe_filename_characters(repo):
    for filename in ('a\x85.md', 'a\u202e.md', 'a\uffff.md', 'a\ufffe.md'):
        with pytest.raises(ValueError):
            repo.create(filename, 'policy')


def test_same_update_preserves_version_and_task_is_idempotent(repo):
    doc = repo.create('policy.txt', 'policy')
    assert repo.update(doc['doc_id'], 'policy.txt', 'policy')['version'] == 1
    task = repo.enqueue(doc['doc_id'])
    assert repo.enqueue(doc['doc_id'])['task_id'] == task['task_id']
    assert len(repo.tasks()) == 1
    with pytest.raises(ValueError):
        repo.update(doc['doc_id'], 'policy.txt', 'changed while indexing')


def test_update_keeps_old_active_until_new_processed(repo):
    from app.knowledge.repository import versions
    doc = repo.create('policy.md', 'v1')
    job = repo.enqueue(doc['doc_id'])
    repo.complete_index(job['task_id'], 'upstream-1')
    changed = repo.update(doc['doc_id'], 'policy.md', 'v2')
    assert changed['active_version'] == 1
    job2 = repo.enqueue(doc['doc_id'])
    repo.complete_index(job2['task_id'], 'upstream-2')
    assert repo.get(doc['doc_id'])['active_version'] == 2
    with repo.engine.connect() as conn:
        old = conn.execute(select(versions).where(versions.c.doc_id == doc['doc_id'], versions.c.version == 1)).mappings().one()
    assert old['state'] == 'retiring'
    assert any(t['kind'] == 'delete' and t['state'] == 'queued' for t in repo.tasks())


def test_draft_delete_is_local_and_failed_index_is_explicit_retry(repo):
    doc = repo.create('a.txt', 'a')
    repo.retire(doc['doc_id'])
    assert repo.get(doc['doc_id'])['state'] == 'retired'
    with pytest.raises(ValueError):
        repo.enqueue(doc['doc_id'])


def test_worker_claim_is_exclusive_and_persistent(repo):
    doc = repo.create('a.txt', 'a')
    task = repo.enqueue(doc['doc_id'])
    assert repo.acquire('worker1')
    assert not repo.acquire('worker2')
    assert repo.claim()['task_id'] == task['task_id']
    assert repo.claim() is None
    repo.release('worker2')
    assert not repo.acquire('worker3')
    repo.release('worker1')
    assert repo.acquire('worker3')
