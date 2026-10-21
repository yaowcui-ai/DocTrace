"""Do not bypass legacy processing merely because upstream returned HTTP 200."""
import pytest

from app import qa_pipeline
from app.facet_policy import POLICY_VERSION
from app.lightrag_client import UpstreamError


@pytest.mark.parametrize('strategy,degraded', [
    ('whole_query_rerank',False),
    ('facet_interleave_v1',False),
    ('fallback_whole_query',True),
    ('fallback_original',True),
])
def test_supported_policy_distinguishes_normal_and_degraded_execution(strategy,degraded):
    metadata={'version':POLICY_VERSION,'strategy':strategy}
    assert qa_pipeline.require_medium_policy(metadata) is degraded


@pytest.mark.parametrize('metadata', [
    None, {},
    {'version':'unreviewed-v2','strategy':'whole_query_rerank'},
    {'version':POLICY_VERSION,'strategy':'disabled'},
    {'version':POLICY_VERSION,'strategy':'unrecognized'},
    {'version':POLICY_VERSION,'strategy':[]},
])
def test_missing_disabled_or_unknown_policy_is_not_silently_trusted(metadata):
    with pytest.raises(UpstreamError) as error:
        qa_pipeline.require_medium_policy(metadata)
    assert error.value.status_code == 502
    assert error.value.stage == '检索策略'
