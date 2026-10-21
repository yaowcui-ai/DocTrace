import httpx2 as httpx
import pytest


def test_probe_accepts_health_and_anonymous_denial():
    from app.check_local_service import probe
    def handler(request):
        if request.url.path == '/health':
            return httpx.Response(200,json={'status':'ok','service':'DocTrace'})
        return httpx.Response(401,json={'detail':'please login'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report=probe(client)
    assert report['status']=='passed'
    assert [item['http_status'] for item in report['probes']]==[200,401]


@pytest.mark.parametrize('status',[200,503])
def test_probe_does_not_treat_access_failure_as_success(status):
    from app.check_local_service import probe
    def handler(request):
        return httpx.Response(200,json={'status':'ok','service':'DocTrace'}) if request.url.path=='/health' else httpx.Response(status)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert probe(client)['status']=='failed'


def test_client_disables_system_proxy(monkeypatch):
    from app import check_local_service
    original=httpx.Client
    def factory(**kwargs):
        assert kwargs['trust_env'] is False
        assert kwargs['follow_redirects'] is False
        return original(transport=httpx.MockTransport(lambda request:httpx.Response(401)),**kwargs)
    monkeypatch.setattr(check_local_service.httpx,'Client',factory)
    with check_local_service.make_client() as client:
        assert probe_dummy(client)==401


def probe_dummy(client):
    return client.get('http://127.0.0.1:8001/records').status_code
