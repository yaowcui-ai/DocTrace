import json
import pytest
import httpx2 as httpx
from app.prelimit_adapter import apply_policy


def chunks():
    return [{'chunk_id': k, 'content': 'text '+k, 'file_path': k+'.md'} for k in 'AB']


def configure(monkeypatch, tmp_path):
    for k,v in {'DOCTRACE_PRELIMIT_ENABLED':'1', 'DOCTRACE_RERANK_URL':'https://example.test/rerank',
                'DOCTRACE_RERANK_MODEL':'test', 'DOCTRACE_RERANK_API_KEY':'private-test-key',
                'DOCTRACE_POLICY_CACHE_DIR':str(tmp_path)}.items():
        monkeypatch.setenv(k,v)


def test_disabled_and_naive_do_not_contact_provider(monkeypatch, tmp_path):
    configure(monkeypatch,tmp_path)
    def forbidden(*a, **kw): pytest.fail('Unexpected provider request')
    monkeypatch.setattr('app.prelimit_adapter.httpx.Client', forbidden)
    assert apply_policy('q',chunks(),mode='naive')[1]['strategy']=='disabled'
    monkeypatch.setenv('DOCTRACE_PRELIMIT_ENABLED','0')
    assert apply_policy('q',chunks(),mode='mix')[0]==chunks()


def test_complete_ranking_is_cached_without_secret_and_preserves_metadata(monkeypatch,tmp_path):
    configure(monkeypatch,tmp_path)
    calls=[]
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'results':[{'index':1,'relevance_score':0.2},{'index':0,'relevance_score':0.1}]})
    real=httpx.Client
    monkeypatch.setattr('app.prelimit_adapter.httpx.Client',lambda **kw:real(transport=httpx.MockTransport(respond)))
    a,meta=apply_policy('q',chunks(),mode='mix')
    b,cached=apply_policy('q',chunks(),mode='mix')
    assert [x['chunk_id'] for x in a]==['B','A']
    assert a==b and meta['provider_calls']==1 and cached['provider_calls']==0
    assert cached['cache_hits']==1
    assert calls[0]['top_n']==2
    assert 'private-test-key' not in ''.join(p.read_text() for p in tmp_path.rglob('*.json'))


@pytest.mark.parametrize('reply',[{'results':[{'index':0,'relevance_score':1}]}, {'results':[{'index':0,'relevance_score':1},{'index':0,'relevance_score':0}]}])
def test_invalid_mapping_falls_back_to_original_and_reports_failure(monkeypatch,tmp_path,reply):
    configure(monkeypatch,tmp_path)
    real=httpx.Client
    monkeypatch.setattr('app.prelimit_adapter.httpx.Client',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=reply))))
    output,meta=apply_policy('q',chunks(),mode='mix')
    assert output==chunks()
    assert meta['strategy']=='fallback_original'
    assert meta['error_kind']=='invalid_response'


def test_missing_credentials_are_explicit_fallback(monkeypatch,tmp_path):
    configure(monkeypatch,tmp_path);monkeypatch.delenv('DOCTRACE_RERANK_API_KEY')
    output,meta=apply_policy('q',chunks(),mode='mix')
    assert output==chunks() and meta['error_kind']=='configuration_error'


@pytest.mark.parametrize('corruption',['{broken','[]','null'])
def test_corrupt_branch_cache_keeps_successful_whole_ranking(monkeypatch,tmp_path,corruption):
    configure(monkeypatch,tmp_path)
    real=httpx.Client
    monkeypatch.setattr('app.prelimit_adapter.httpx.Client',lambda **kw:real(transport=httpx.MockTransport(
        lambda r:httpx.Response(200,json={'results':[{'index':1,'relevance_score':0.2},{'index':0,'relevance_score':0.1}]}))))
    question='甲如何处理？乙多久更新？请结合说明。'
    apply_policy(question,chunks(),mode='mix')
    for path in tmp_path.glob('*.json'):
        if json.loads(path.read_text(encoding='utf-8'))['query']=='甲如何处理？':
            path.write_text(corruption,encoding='utf-8')
    output,meta=apply_policy(question,chunks(),mode='mix')
    assert [c['chunk_id'] for c in output]==['B','A']
    assert meta['strategy']=='fallback_whole_query'
    assert meta['provider_calls']==0
