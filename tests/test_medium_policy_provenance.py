import json
from types import SimpleNamespace
from deploy.seed_hr_prelimit_cache import provider_matches
from app.medium_policy_experiment import safe_error_record


def test_seed_rejects_different_or_missing_provider_provenance():
    settings=SimpleNamespace(rerank_model='model-B',rerank_url='https://provider-B/rerank')
    assert not provider_matches({'model':'model-A','provider_url':settings.rerank_url},settings)
    assert not provider_matches({'model':settings.rerank_model,'provider_url':'https://provider-A/rerank'},settings)
    assert not provider_matches({'model':settings.rerank_model},settings)
    assert provider_matches({'model':settings.rerank_model,'provider_url':settings.rerank_url},settings)


def test_experiment_error_record_does_not_resave_echoed_credentials():
    original={'http_status':401,'error_kind':'http_error','elapsed_seconds':1,
              'raw_response':{'echo':'Bearer private-secret'},'raw_response_text':'private-secret'}
    safe=safe_error_record(original)
    assert 'private-secret' not in json.dumps(safe)
    assert safe['http_status']==401 and safe['elapsed_seconds']==1
    assert original['raw_response']['echo']=='Bearer private-secret'
