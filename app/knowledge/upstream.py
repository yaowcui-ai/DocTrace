"""Fail-closed transport to the managed LightRAG instance only."""
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit, quote

import httpx2 as httpx
from dotenv import dotenv_values

from app.config import ConfigurationError, DEFAULT_ENV_PATH
from .repository import CORPUS_ID

MANAGED_TITLE = 'DocTrace Managed Knowledge v1'


@dataclass(frozen=True)
class ManagedSettings:
    url: str
    api_key: str = field(repr=False)

    def __post_init__(self):
        try:
            parsed = urlsplit(self.url)
            valid = (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1', 'host.docker.internal'}
                and parsed.port == 9631 and parsed.path in {'', '/'} and not parsed.query
                and not parsed.fragment and not parsed.username and not parsed.password
                and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in self.url)
                and not any(c in self.url for c in '\\?#'))
        except ValueError:
            valid = False
        if not valid:
            raise ConfigurationError('MANAGED_LIGHTRAG_URL must be the dedicated local HTTP service on port 9631.')
        if not self.api_key or any(ord(c) < 32 or ord(c) == 127 for c in self.api_key):
            raise ConfigurationError('MANAGED_LIGHTRAG_API_KEY is required and must be valid.')


def load_managed_settings(env_path=DEFAULT_ENV_PATH):
    values = dotenv_values(env_path, encoding='utf-8', interpolate=False)
    return ManagedSettings(os.environ.get('MANAGED_LIGHTRAG_URL', values.get('MANAGED_LIGHTRAG_URL')) or '',
        os.environ.get('MANAGED_LIGHTRAG_API_KEY', values.get('MANAGED_LIGHTRAG_API_KEY')) or '')


class ManagedFailure(Exception):
    def __init__(self, code, *, uncertain=False):
        self.code, self.uncertain = code, uncertain
        super().__init__(code)


class ManagedClient:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    def _request(self, method, path, *, payload=None):
        mutation = method != 'GET'
        try:
            with httpx.Client(timeout=httpx.Timeout(30, connect=5), trust_env=False,
                    follow_redirects=False, transport=self.transport) as client:
                response = client.request(method, self.settings.url.rstrip('/') + path,
                    headers={'X-API-Key': self.settings.api_key}, json=payload)
        except httpx.RequestError:
            raise ManagedFailure('upstream_transport_unavailable', uncertain=mutation) from None
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            raise ManagedFailure('upstream_response_unconfirmed', uncertain=mutation)
        if not 200 <= response.status_code < 300:
            raise ManagedFailure('upstream_request_rejected')
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (ValueError, TypeError):
            raise ManagedFailure('upstream_invalid_response', uncertain=mutation) from None

    def verify(self):
        data = self._request('GET', '/health')
        config = data.get('configuration')
        if (data.get('status') != 'healthy' or data.get('webui_title') != MANAGED_TITLE
                or not isinstance(config, dict) or config.get('workspace') != CORPUS_ID):
            raise ManagedFailure('upstream_identity_mismatch')
        # If the server reports effective storage workspaces, each must agree.
        workspaces = config.get('storage_workspaces', {})
        if not isinstance(workspaces, dict) or any(v != CORPUS_ID for v in workspaces.values()):
            raise ManagedFailure('upstream_identity_mismatch')

    def submit(self, version):
        self.verify()
        data = self._request('POST', '/documents/text', payload={
            'text': version['content'], 'file_source': self.file_source(version)})
        track = data.get('track_id')
        if data.get('status') != 'success' or not isinstance(track, str) or not 1 <= len(track) <= 255 or any(ord(c) < 32 for c in track):
            raise ManagedFailure('upstream_submission_unconfirmed', uncertain=True)
        return track

    @staticmethod
    def file_source(version):
        return f"{version['doc_id']}_v{version['version']}_{version['filename']}"

    def poll(self, version):
        self.verify()
        data = self._request('GET', '/documents/track_status/' + quote(version['track_id'], safe=''))
        rows = data.get('documents')
        if (data.get('track_id') != version['track_id'] or not isinstance(rows, list)
                or type(data.get('total_count')) is not int or data['total_count'] != len(rows)
                or any(not isinstance(row, dict) for row in rows)):
            raise ManagedFailure('upstream_invalid_track_response')
        return rows

    def delete(self, version):
        self.verify()
        data = self._request('DELETE', '/documents/delete_document', payload={
            'doc_ids': [version['upstream_id']], 'delete_file': False, 'delete_llm_cache': False})
        if data.get('status') == 'busy':
            raise ManagedFailure('upstream_busy')
        if data.get('status') != 'deletion_started':
            raise ManagedFailure('upstream_deletion_unconfirmed', uncertain=True)
