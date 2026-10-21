"""User-run, fixed-target incremental ingestion; preview unless --submit is explicit."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx

from .config import load_settings


PROJECT = Path(__file__).resolve().parent.parent
CORPUS = PROJECT / 'data/gitlab_hr/v2'
BASE_URL = 'http://127.0.0.1:9623'
BATCHES = {
    1: ('hr_canada_benefits', 'hr_us_benefits'),
    2: ('hr_netherlands_benefits', 'hr_germany_benefits'),
    3: ('hr_france_remote_work', 'hr_relocation'),
    4: ('hr_travel_expenses', 'hr_development_tax'),
}


def build_batch(root: Path, batch: int) -> tuple[dict, list]:
    root = root.resolve()
    manifest = json.loads((root / 'processing_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('corpus_id') != 'gitlab_hr_v2' or batch not in BATCHES:
        raise ValueError('Unexpected corpus or batch')
    records = manifest['documents']
    payload = {'texts': [], 'file_sources': [], 'chunking': {
        'strategy': 'fixed_token', 'params': {
            'chunk_token_size': 1200, 'chunk_overlap_token_size': 100}}}
    files = []
    for document_id in BATCHES[batch]:
        matches = [d for d in records if d['document_id'] == document_id]
        if len(matches) != 1:
            raise ValueError('Missing or duplicate document: ' + document_id)
        item = matches[0]
        path = (root / item['cleaned_file']).resolve()
        if not path.is_relative_to(root) or path.name != document_id + '.md':
            raise ValueError('Unexpected source path')
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != item['cleaned_sha256']:
            raise ValueError('Source hash mismatch: ' + document_id)
        text = content.decode('utf-8')
        if not text.strip():
            raise ValueError('Empty source document')
        payload['texts'].append(text)
        payload['file_sources'].append(path.name)
        files.append({'file_name': path.name, 'sha256': digest, 'characters': len(text)})
    return payload, files


def submit_once(client, payload: dict, api_key: str) -> dict:
    try:
        response = client.post(BASE_URL + '/documents/texts', json=payload,
                               headers={'X-API-Key': api_key})
    except httpx.TransportError:
        return {'status': 'submission_unknown', 'http_status': None,
                'error': 'transport_error_check_server_before_resubmitting'}
    result = {'status': 'submission_unknown', 'http_status': response.status_code}
    try:
        data = response.json()
    except ValueError:
        result['error'] = 'non_json_response_check_server_before_resubmitting'
        return result
    result['response'] = data
    if response.is_success and isinstance(data, dict) and data.get('status') == 'success' and data.get('track_id'):
        result.update(status='accepted_pending_processing', track_id=data['track_id'])
    else:
        result['error'] = 'unexpected_response_check_server_before_resubmitting'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=int, choices=sorted(BATCHES), required=True)
    parser.add_argument('--submit', action='store_true', help='Send one paid indexing submission')
    args = parser.parse_args()
    payload, files = build_batch(CORPUS, args.batch)
    print('Target:', BASE_URL, 'workspace: gitlab_hr_v2')
    print('Chunking: fixed_token, size=1200, overlap=100')
    for item in files:
        print(item['file_name'], 'characters:', item['characters'])
    if not args.submit:
        print('Preview only. No requests sent. Add --submit to submit this batch.')
        return

    status_path = PROJECT / 'runtime/gitlab_hr_v2/rag_storage/gitlab_hr_v2/kv_store_doc_status.json'
    statuses = json.loads(status_path.read_text(encoding='utf-8'))
    if len(statuses) < 6 or any(d.get('status') != 'processed' for d in statuses.values()):
        raise ValueError('Cloned corpus must be present and all existing documents processed first')
    existing = {Path(d.get('file_path', '')).name for d in statuses.values()}
    if existing.intersection(payload['file_sources']):
        raise ValueError('Batch already has stored documents; inspect status instead of resubmitting')
    jobs = CORPUS / 'jobs'
    jobs.mkdir(exist_ok=True)
    for previous_path in jobs.glob('*.json'):
        previous = json.loads(previous_path.read_text(encoding='utf-8'))
        if previous.get('batch') == args.batch:
            raise ValueError('Submission record already exists; inspect track/status before any resubmission')

    settings = load_settings()
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=5.0), trust_env=False,
                      follow_redirects=False) as client:
        health = client.get(BASE_URL + '/health', headers={'X-API-Key': settings.lightrag_api_key})
        health.raise_for_status()
        info = health.json()
        if info.get('status') != 'healthy' or info.get('webui_title') != 'DocTrace HR Knowledge Base v2':
            raise ValueError('Unexpected target service')
        if info.get('pipeline_busy') or info.get('pipeline_active'):
            raise ValueError('Target pipeline is busy; wait before submitting')
        now = datetime.now(timezone.utc)
        job_path = jobs / (now.strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8] + '.json')
        report = {'corpus_id': 'gitlab_hr_v2', 'batch': args.batch, 'base_url': BASE_URL,
                  'created_at_utc': now.isoformat(), 'files': files, 'payload': payload,
                  'status': 'submission_unknown',
                  'note': 'Record saved before POST. Not proof of submission or processing.'}
        with job_path.open('x', encoding='utf-8') as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
        print('Report:', job_path, flush=True)
        result = submit_once(client, payload, settings.lightrag_api_key)
        report.update(result)
        report['completed_request_at_utc'] = datetime.now(timezone.utc).isoformat()
        job_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Status:', result['status'])
        print('HTTP:', result['http_status'])
        print('Track ID:', result.get('track_id'))
        print('Wait for processed status; do not repeat this command on timeout.')


if __name__ == '__main__':
    main()
