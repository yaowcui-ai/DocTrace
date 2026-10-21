"""Request options are explicit; invalid settings must never reach the network."""
import json

import httpx2 as httpx
import pytest

from app.config import Settings
from app.retrieval_client import collect_retrieval

SETTINGS = Settings('http://rag.test', 'test-service-key')


def test_mix_request_sends_explicit_token_budget_without_native_rerank():
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == 'http://rag.test/query/data'
        assert json.loads(request.content) == {
            'query': 'Question', 'mode': 'mix',
            'enable_rerank': False, 'max_total_tokens': 40000,
        }
        return httpx.Response(200, json={'status': 'success', 'data': {'chunks': []}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect_retrieval(client, SETTINGS, 'Question', mode='mix', max_total_tokens=40000)
    assert len(calls) == 1
    assert result['error_kind'] is None
    assert result['chunks'] == []


@pytest.mark.parametrize('mode', ['hybrid', '', None])
def test_unsupported_business_mode_is_rejected_before_http(mode):
    def forbidden(request):
        pytest.fail('Invalid configuration must not issue requests')

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(ValueError):
            collect_retrieval(client, SETTINGS, 'Question', mode=mode)


@pytest.mark.parametrize('budget', [0, -1, True, 1.5, '40000'])
def test_invalid_token_budget_is_rejected_before_http(budget):
    def forbidden(request):
        pytest.fail('Invalid configuration must not issue requests')

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(ValueError):
            collect_retrieval(client, SETTINGS, 'Question', max_total_tokens=budget)
