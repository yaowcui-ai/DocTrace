"""Clone the frozen index and build a capture-only override; never modify its source."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
IMAGE = 'ghcr.io/hkuds/lightrag@sha256:5bdbd524931b011df246fe20888d110cef691e6804c12cde636a2b746d7de27e'


def main():
    from scripts.init_upgrade_config import _quoted
    from dotenv import dotenv_values
    source = ROOT/'runtime/gitlab_hr_v3/rag_storage/gitlab_hr_v3'
    target = ROOT/'runtime/upgrade/probe/rag_storage/gitlab_hr_v3'
    home = target.parent.parent
    marker = home/'clone.json'
    if target.exists() and not marker.exists():
        raise RuntimeError('Unverified existing target; refusing to overwrite it')
    if not target.exists():
        status = json.loads((source/'kv_store_doc_status.json').read_text(encoding='utf-8'))
        chunks = json.loads((source/'kv_store_text_chunks.json').read_text(encoding='utf-8'))
        assert len(status) == 68 and len(chunks) == 318 and all(d['status'] == 'processed' for d in status.values())
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('kv_store_llm_response_cache.json'))
        files = {}
        for path in target.iterdir():
            if path.is_file():
                before = hashlib.sha256((source/path.name).read_bytes()).hexdigest()
                assert before == hashlib.sha256(path.read_bytes()).hexdigest()
                files[path.name] = before
        marker.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), 'documents': 68,
            'chunks': 318, 'files_sha256': files, 'source_modified': False}, indent=2), encoding='utf-8')
    raw = subprocess.check_output(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', IMAGE, '/app/lightrag/operate.py'])
    upstream_sha = hashlib.sha256(raw).hexdigest()
    assert upstream_sha == 'fecb70d27b860efacb57d7b1bc16a706d7d68bd18de9ac80571fcd4628305047'
    text = raw.decode()
    boundary = '    # Apply token truncation to chunks using the dynamic limit\n    truncated_chunks = await process_chunks_unified('
    assert text.count(boundary) == 1
    capture = '''    # Capture only: preserve every original candidate and all original selection behavior.
    doctrace_probe = {"query": query, "original_chunks": merged_chunks,
        "chunk_top_k": query_param.chunk_top_k, "tokenizer": "gpt-4o-mini",
        "budget": {"total_tokens": query_param.max_total_tokens,
                   "available_chunk_tokens": available_chunk_tokens}}
'''
    text = text.replace(boundary, capture+boundary)
    final = '    final_data_payload = final_data.get("data", {})'
    assert text.count(final) == 1
    text = text.replace(final, '    final_data.setdefault("metadata", {})["doctrace_probe"] = doctrace_probe\n'+final)
    compile(text, 'operate.py', 'exec')
    (home/'operate.py').write_text(text, encoding='utf-8')
    values = dotenv_values(ROOT/'runtime/upgrade/managed-lightrag.env', interpolate=False)
    app = dotenv_values(ROOT/'runtime/upgrade/.env', interpolate=False)
    values['LIGHTRAG_API_KEY'] = app['LIGHTRAG_API_KEY']
    env_file = home/'lightrag.env'
    if not env_file.exists():
        with env_file.open('x', encoding='utf-8') as stream:
            stream.write('\n'.join(f'{key}={_quoted(value)}' for key, value in values.items() if value is not None)+'\n')
    print('Probe clone verified: 68 documents, 318 chunks; original untouched, provider calls 0.')


if __name__ == '__main__':
    main()
