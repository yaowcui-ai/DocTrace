"""Retain medium-pipeline degradation in saved observations without changing legacy ones."""
import httpx2 as httpx
import pytest

from app.evaluate import evaluate_case
from app.facet_policy import POLICY_VERSION

CASE={'id':'C1','question':'Question','expected_behavior':'answer','required_points':[],
      'failure_conditions':[],'evidence':[]}
BASE={'response':'Rule [1]','references':[{'reference_id':'1','file_path':'policy.md','content':['Rule']}],
      'response_time':1.0,'llm_generated':True}


@pytest.mark.parametrize('strategy,degraded',[('whole_query_rerank',False),('fallback_original',True)])
def test_evaluation_preserves_medium_strategy_and_degradation(strategy,degraded):
    payload={**BASE,'retrieval':{'mode':'mix','policy_version':POLICY_VERSION,'strategy':strategy,'degraded':degraded}}
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))) as client:
        record=evaluate_case(client,'http://app.test',CASE,endpoint='/ask/optimized')
    assert record['error_kind'] is None
    assert record['result']==payload
    assert record['review']['answer_correct'] is None


def test_empty_medium_response_retains_explicit_null_metadata():
    payload={'response':'Insufficient evidence','references':[],'response_time':1.0,
             'llm_generated':False,'retrieval':None}
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))) as client:
        record=evaluate_case(client,'http://app.test',CASE,endpoint='/ask/optimized')
    assert record['result']==payload


def test_invalid_medium_metadata_is_not_silently_dropped():
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={**BASE,'retrieval':[]}))) as client:
        record=evaluate_case(client,'http://app.test',CASE,endpoint='/ask/optimized')
    assert record['error_kind']=='invalid_response'
    assert record['result'] is None


def test_policy_stage_is_retained_without_raw_error_text():
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(502,json={
        'detail':{'stage':'检索策略','message':'private-debug-value'}}))) as client:
        record=evaluate_case(client,'http://app.test',CASE,endpoint='/ask/optimized')
    assert record['error_stage']=='检索策略'
    assert 'private-debug-value' not in str(record)


def test_evaluation_preserves_persisted_response_identifier():
    payload={**BASE,'retrieval':None,'request_id':'f3e01a1a-c497-401a-811c-40413cc05dbb'}
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))) as client:
        record=evaluate_case(client,'http://app.test',CASE,endpoint='/ask/optimized')
    assert record['error_kind'] is None
    assert record['result']==payload


@pytest.mark.parametrize('stage',['记录保存','内部处理'])
def test_evaluation_keeps_failure_identifier_and_stage_without_message(stage):
    request_id='f3e01a1a-c497-401a-811c-40413cc05dbb'
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(503,json={
        'detail':{'stage':stage,'message':'private-debug-value','request_id':request_id}}))) as client:
        record=evaluate_case(client,'http://app.test',CASE,endpoint='/ask/optimized')
    assert record['error_stage']==stage
    assert record['request_id']==request_id
    assert 'private-debug-value' not in str(record)


def test_invalid_persisted_response_identifier_is_rejected():
    payload={**BASE,'retrieval':None,'request_id':123}
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))) as client:
        record=evaluate_case(client,'http://app.test',CASE,endpoint='/ask/optimized')
    assert record['error_kind']=='invalid_response'
