"""Verify frozen artifacts and pinned LightRAG bytes; read-only, no provider calls."""
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'ghcr.io/hkuds/lightrag@sha256:5bdbd524931b011df246fe20888d110cef691e6804c12cde636a2b746d7de27e'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    output = ROOT/'evaluation'/'upgrade'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_audit_'+uuid4().hex[:8])
    output.mkdir(parents=True)
    upstream = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', IMAGE, '/app/lightrag/operate.py'])
    deployed = subprocess.check_output(['docker', 'exec', 'doctrace-hr-v3-lightrag_hr_v3-1', 'cat', '/app/lightrag/operate.py'])
    built = (ROOT/'runtime/hr_prelimit/operate.py').read_bytes()
    build = json.loads((ROOT/'runtime/hr_prelimit/build.json').read_text(encoding='utf-8'))
    # Do not copy the full upstream into public project; preserve a compact actual patch.
    patch = ''.join(difflib.unified_diff(upstream.decode().splitlines(True), built.decode().splitlines(True), fromfile='pinned-image/lightrag/operate.py', tofile='doctrace-generated/lightrag/operate.py'))
    (output/'operate.patch').write_text(patch, encoding='utf-8')
    corpus = ROOT/'data/gitlab_hr/v3'
    manifest = json.loads((corpus/'processing_manifest.json').read_text(encoding='utf-8'))
    checks = []
    for item in manifest['documents']:
        row = {'document_id': item.get('document_id')}
        for field, hash_field in [('raw_file', 'raw_sha256'), ('cleaned_file', 'cleaned_sha256')]:
            if field in item:
                path = (corpus/item[field]).resolve()
                row[field] = path.is_relative_to(corpus.resolve()) and path.is_file() and digest(path.read_bytes()) == item[hash_field]
        checks.append(row)
    frozen = {}
    for directory in ['evaluation/history', 'evaluation/freezes', 'data/gitlab_hr/v3/cleaned']:
        for path in sorted((ROOT/directory).rglob('*')):
            if path.is_file():
                frozen[path.relative_to(ROOT).as_posix()] = digest(path.read_bytes())
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'image': IMAGE,
              'provider_calls': 0, 'upstream_sha256': digest(upstream), 'built_sha256': digest(built),
              'deployed_sha256': digest(deployed),
              'upstream_matches_build': digest(upstream) == build['upstream_sha256'],
              'deployed_matches_built': deployed == built, 'corpus_checks': checks,
              'frozen_artifact_hashes': frozen,
              'note': 'Snapshot taken during audit; application source changes are tracked separately in Git.'}
    (output/'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert report['upstream_matches_build'] and report['deployed_matches_built']
    assert all(all(value is True for key, value in row.items() if key != 'document_id') for row in checks)
    print('Verified corpus documents:', len(checks))
    print('Pinned original/build/deployed bytes verified; provider calls: 0')
    print('Report:', output)


if __name__ == '__main__':
    main()
