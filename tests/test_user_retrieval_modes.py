"""No provider calls: verify request validation and single-chain dispatch."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import qa_pipeline, schemas
from app.schemas import AskResponse, MediumAskResponse


def test_optimized_request_defaults_to_naive():
    assert schemas.OptimizedAskRequest(question='Question').mode == 'naive'


@pytest.mark.parametrize('mode', ['naive', 'mix'])
def test_explicit_supported_mode(mode):
    assert schemas.OptimizedAskRequest(question='Question', mode=mode).mode == mode


@pytest.mark.parametrize('mode', ['hybrid', 'auto', 123, None])
def test_unsupported_mode_rejected(mode):
    with pytest.raises(ValidationError):
        schemas.OptimizedAskRequest(question='Question', mode=mode)


def test_mix_dispatch_does_not_run_naive_or_load_naive_configuration(monkeypatch):
    expected = MediumAskResponse(response='Mix', references=[], llm_generated=True)
    calls = []
    monkeypatch.setattr(qa_pipeline, 'run_medium_qa_pipeline',
        lambda *args, **kwargs: calls.append(kwargs) or expected)
    monkeypatch.setattr(qa_pipeline, 'run_qa_pipeline', lambda *args, **kwargs: pytest.fail('No naive call'))
    result = qa_pipeline.run_selected_qa_pipeline('Question', object(), object(), object(), mode='mix', max_total_tokens=40000)
    assert result is expected and calls == [{'max_total_tokens': 40000}]


def test_naive_dispatch_has_actual_mode_metadata_and_does_not_run_mix(monkeypatch):
    monkeypatch.setattr(qa_pipeline, 'load_pipeline_settings',
        lambda: SimpleNamespace(max_chars=30000, min_score=0.3))
    rerank = object()
    monkeypatch.setattr(qa_pipeline, 'load_rerank_settings', lambda: rerank)
    calls = []
    monkeypatch.setattr(qa_pipeline, 'run_qa_pipeline', lambda *args, **kwargs:
        calls.append((args, kwargs)) or AskResponse(response='Naive', references=[], llm_generated=False))
    monkeypatch.setattr(qa_pipeline, 'run_medium_qa_pipeline', lambda *args, **kwargs: pytest.fail('No mix call'))
    result = qa_pipeline.run_selected_qa_pipeline('Question', object(), object(), object(), mode='naive')
    assert result.response == 'Naive' and result.retrieval.mode == 'naive'
    assert result.retrieval.degraded is False
    assert calls[0][0][3] is rerank
    assert calls[0][1] == {'max_chars': 30000, 'min_score': 0.3}


def test_invalid_dispatch_never_starts_retrieval():
    with pytest.raises(ValueError):
        qa_pipeline.run_selected_qa_pipeline('Question', object(), object(), object(), mode='hybrid')
