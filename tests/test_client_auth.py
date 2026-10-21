import json

import httpx2 as httpx
import pytest

from app import client_auth, evaluate
from app.auth_config import AuthSettings
from app.config import ConfigurationError


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(client_auth,'load_auth_settings',lambda:AuthSettings('http://127.0.0.1:8001',False,7200))
    monkeypatch.setattr(client_auth.getpass,'getpass',lambda _: 'Fake!123')


def test_cli_login_keeps_credential_only_in_client_cookie():
    def handler(request):
        assert request.headers['Origin']=='http://127.0.0.1:8001'
        assert json.loads(request.content)=={'username':'alice','password':'Fake!123'}
        return httpx.Response(200,json={'user_id':'00000000-0000-4000-8000-000000000001','username':'alice'},headers={'Set-Cookie':'doctrace_session='+'x'*43+'; HttpOnly; Path=/; SameSite=Strict'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        client_auth.login_evaluation_client(client,'http://127.0.0.1:8001','alice')
        assert client.cookies.get('doctrace_session')=='x'*43
        assert client.headers['X-DocTrace-User-ID']=='00000000-0000-4000-8000-000000000001'


@pytest.mark.parametrize('status',[401,403,503])
def test_failed_login_stops_before_question(status):
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status,json={'detail':'private'}))) as client:
        with pytest.raises(ConfigurationError,match='no question submitted'):
            client_auth.login_evaluation_client(client,'http://127.0.0.1:8001','alice')


def test_login_refuses_unconfigured_destination_without_prompt(monkeypatch):
    monkeypatch.setattr(client_auth.getpass,'getpass',lambda _:pytest.fail('No password prompt for untrusted target'))
    with pytest.raises(ConfigurationError):
        client_auth.login_evaluation_client(None,'https://attacker.example','alice')


def test_end_to_end_requires_account_before_http_client(monkeypatch):
    monkeypatch.setattr(evaluate.httpx,'Client',lambda **kwargs:pytest.fail('Must not create client'))
    with pytest.raises(SystemExit):
        evaluate.main(['--all'])
