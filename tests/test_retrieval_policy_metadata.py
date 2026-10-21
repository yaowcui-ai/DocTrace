"""A successful retrieval can report degraded ordering; do not erase that signal."""
import httpx2 as httpx
import pytest

from app.config import Settings
from app.retrieval_client import collect_retrieval

SETTINGS = Settings('http://rag.test', 'test-key')
CHUNK = {'chunk_id':'A','reference_id':'1','file_path':'policy.md','content':'Policy evidence'}


def retrieve(extra):
    body = {'status':'success','data':{'chunks':[CHUNK]}, **extra}
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body))) as client:
        return collect_retrieval(client, SETTINGS, 'Question', mode='mix', max_total_tokens=40000)


def test_preserves_strategy_version_and_call_information():
    policy = {'version':'facet_interleave_v1','strategy':'whole_query_rerank','provider_calls':1,'cache_hits':0}
    record = retrieve({'metadata':{'doctrace_policy':policy}})
    assert record['error_kind'] is None
    assert record['policy_metadata'] == policy
    assert record['chunks'] == [CHUNK]


def test_fallback_is_preserved_instead_of_misreported_as_normal_reranking():
    policy = {'version':'facet_interleave_v1','strategy':'fallback_original','error_kind':'timeout',
              'provider_calls':1,'cache_hits':0}
    record = retrieve({'metadata':{'doctrace_policy':policy}})
    assert record['http_status'] == 200
    assert record['error_kind'] is None  # Retrieval succeeded; ordering degraded separately.
    assert record['policy_metadata']['strategy'] == 'fallback_original'
    assert record['policy_metadata']['error_kind'] == 'timeout'
    assert record['chunks'] == [CHUNK]


def test_legacy_response_without_policy_is_explicitly_unknown():
    record = retrieve({})
    assert record['error_kind'] is None
    assert record['policy_metadata'] is None


@pytest.mark.parametrize('metadata', [None, [], {'doctrace_policy':[]}, {'doctrace_policy':'enabled'}])
def test_malformed_metadata_is_not_accepted_as_valid_policy(metadata):
    record = retrieve({'metadata':metadata})
    assert record['error_kind'] == 'invalid_response'
    assert record['chunks'] is None
    assert record['policy_metadata'] is None
