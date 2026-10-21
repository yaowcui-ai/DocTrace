"""Medium-corpus evidence must reach generation without a second rerank/filter."""
import json

import httpx2 as httpx
import pytest

from app import qa_pipeline
from app.answer_config import AnswerSettings
from app.config import Settings
from app.facet_policy import POLICY_VERSION
from app.lightrag_client import UpstreamError
from app.schemas import MediumAskResponse

RAG = Settings('http://rag.test', 'service-key')
ANSWER = AnswerSettings('https://answer.test/chat/completions', 'answer-model', 'answer-key')
CHUNKS = [
    {'chunk_id':'A','reference_id':'9','file_path':'a.md','content':'A'*31000,'rerank_score':0.01},
    {'chunk_id':'B','reference_id':'3','file_path':'b.md','content':'Required qualification'},
]


def policy(strategy='whole_query_rerank'):
    return {'version':POLICY_VERSION,'strategy':strategy}


def response_body(metadata):
    return {'status':'success','data':{'chunks':CHUNKS},'metadata':{'doctrace_policy':metadata}}


def answer_response():
    return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'Rule [1] [2]'},'finish_reason':'stop'}]})


def run(handler):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return qa_pipeline.run_medium_qa_pipeline('Question',client,RAG,ANSWER,max_total_tokens=40000)


def test_response_can_carry_degraded_retrieval_information():
    result=MediumAskResponse.model_validate({'response':'Rule','references':[],'llm_generated':True,
        'retrieval':{'mode':'mix','policy_version':POLICY_VERSION,'strategy':'fallback_original','degraded':True}})
    assert result.retrieval.degraded is True
    assert result.model_dump()['retrieval']['strategy']=='fallback_original'


def test_all_selected_evidence_reaches_answer_without_local_rerank_or_old_filters():
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.host=='rag.test':
            assert json.loads(request.content)=={'query':'Question','mode':'mix','enable_rerank':False,'max_total_tokens':40000}
            return httpx.Response(200,json=response_body(policy()))
        assert request.url.host=='answer.test', 'Unexpected local rerank request'
        evidence=json.loads(json.loads(request.content)['messages'][1]['content'])['evidence']
        assert [x['chunk_id'] for x in evidence]==['A','B']
        assert [x['reference_id'] for x in evidence]==['1','2']
        assert [x['content'] for x in evidence]==[x['content'] for x in CHUNKS]
        return answer_response()
    result=run(handler)
    assert len(calls)==2
    assert [r.file_path for r in result.references]==['a.md','b.md']
    assert result.retrieval.degraded is False
    assert result.retrieval.policy_version==POLICY_VERSION
    assert result.response_time>=0


@pytest.mark.parametrize('strategy',['fallback_whole_query','fallback_original'])
def test_degradation_is_reported_and_does_not_trigger_another_rerank(strategy):
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.host=='rag.test':return httpx.Response(200,json=response_body(policy(strategy)))
        assert request.url.host=='answer.test'
        return answer_response()
    result=run(handler)
    assert len(calls)==2
    assert result.retrieval.degraded is True
    assert result.retrieval.strategy==strategy


def test_empty_evidence_does_not_call_answer_or_require_a_rerank_state():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'status':'success','data':{'chunks':[]}})
    result=run(handler)
    assert len(calls)==1
    assert result.llm_generated is False
    assert result.references==[]


@pytest.mark.parametrize('metadata',[None,policy('disabled')])
def test_unconfirmed_policy_stops_before_generation(metadata):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json=response_body(metadata))
    with pytest.raises(UpstreamError) as error:run(handler)
    assert len(calls)==1
    assert error.value.stage=='检索策略'


def test_retrieval_timeout_does_not_become_an_insufficient_evidence_answer():
    def handler(request):raise httpx.ReadTimeout('mock timeout',request=request)
    with pytest.raises(UpstreamError) as error:run(handler)
    assert error.value.status_code==504
    assert error.value.stage=='检索'


def test_answer_service_error_keeps_its_stage():
    def handler(request):
        if request.url.host=='rag.test':return httpx.Response(200,json=response_body(policy()))
        return httpx.Response(503)
    with pytest.raises(UpstreamError) as error:run(handler)
    assert error.value.status_code==502
    assert error.value.stage=='回答模型'
