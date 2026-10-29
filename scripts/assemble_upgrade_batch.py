"""Read-only assembly: original failures remain in history after a successful recovery."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    folder = args.run.resolve()
    if not folder.is_relative_to((ROOT/'evaluation/upgrade/new_retrieval').resolve()):
        raise ValueError('Unexpected experiment path')
    dataset_path = ROOT/'evaluation/upgrade_dataset/internal-test-v1/dataset.json'
    dataset = json.loads(dataset_path.read_text(encoding='utf-8'))
    records, failures, attempts = [], [], []
    for case in dataset['cases']:
        original = folder/(case['id']+'.json')
        paths = ([original] if original.exists() else [])+sorted((folder/'retries').glob(case['id']+'_*.json'))
        resolved = None
        for path in paths:
            value = json.loads(path.read_text(encoding='utf-8'))
            attempts.append({'case_id': case['id'], 'path': path.relative_to(ROOT).as_posix(),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'status': value['status'], 'error_kind': value.get('error_kind')})
            if value['status'] == 'completed':
                resolved = value['record']
        if resolved:
            records.append(resolved)
        else:
            failures.append({'case_id': case['id'], 'status': 'not_attempted' if not paths else json.loads(paths[-1].read_text(encoding='utf-8'))['status']})
    result = {'dataset_file': dataset_path.relative_to(ROOT).as_posix(), 'dataset_sha256': hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        'status': 'partial' if failures else 'completed', 'records': records, 'failures': failures,
        'test_count': len(dataset['cases']), 'scorable_count': len(records), 'all_attempts': attempts,
        'created_at': datetime.now(timezone.utc).isoformat(), 'assembly_provider_calls': 0}
    output = folder/('assembled_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:6]+'.json')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print('Scorable:', len(records), 'unresolved:', len(failures), 'attempt records:', len(attempts))
    print('Source:', output)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
