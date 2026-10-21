import hashlib
import json

import pytest

from app.ingest_hr_v2 import build_batch, submit_once


def make_corpus(tmp_path):
    (tmp_path / 'cleaned').mkdir()
    documents = []
    for name in ('hr_canada_benefits', 'hr_us_benefits'):
        content = ('# ' + name + '\n政策正文\n').encode('utf-8')
        (tmp_path / 'cleaned' / (name + '.md')).write_bytes(content)
        documents.append({'document_id': name, 'cleaned_file': 'cleaned/' + name + '.md',
                          'cleaned_sha256': hashlib.sha256(content).hexdigest()})
    (tmp_path / 'processing_manifest.json').write_text(json.dumps(
        {'corpus_id': 'gitlab_hr_v2', 'documents': documents}), encoding='utf-8')
    return tmp_path


def test_explicit_fixed_chunking_and_source_mapping(tmp_path):
    payload, files = build_batch(make_corpus(tmp_path), 1)
    assert payload['file_sources'] == ['hr_canada_benefits.md', 'hr_us_benefits.md']
    assert payload['texts'][0].startswith('# hr_canada_benefits')
    assert payload['chunking'] == {'strategy': 'fixed_token', 'params': {
        'chunk_token_size': 1200, 'chunk_overlap_token_size': 100}}
    assert len(files) == 2


def test_changed_source_is_rejected_before_submission(tmp_path):
    root = make_corpus(tmp_path)
    (root / 'cleaned/hr_canada_benefits.md').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='hash'):
        build_batch(root, 1)


def test_manifest_cannot_escape_corpus_directory(tmp_path):
    root = make_corpus(tmp_path)
    manifest = root / 'processing_manifest.json'
    data = json.loads(manifest.read_text(encoding='utf-8'))
    data['documents'][0]['cleaned_file'] = '../outside.md'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='path'):
        build_batch(root, 1)


def test_timeout_is_recorded_as_unknown_and_not_retried():
    import httpx2 as httpx

    class Client:
        calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            raise httpx.ReadTimeout('private provider message')

    client = Client()
    result = submit_once(client, {'texts': ['policy']}, 'secret')
    assert client.calls == 1
    assert result['status'] == 'submission_unknown'
    assert 'secret' not in json.dumps(result)
    assert 'private provider message' not in json.dumps(result)


def test_success_means_accepted_not_processed():
    import httpx2 as httpx

    class Client:
        def post(self, url, **kwargs):
            assert url == 'http://127.0.0.1:9623/documents/texts'
            assert kwargs['headers']['X-API-Key'] == 'secret'
            return httpx.Response(200, json={'status': 'success', 'track_id': 'insert_test'})

    result = submit_once(Client(), {'texts': ['policy']}, 'secret')
    assert result['status'] == 'accepted_pending_processing'
    assert result['track_id'] == 'insert_test'
