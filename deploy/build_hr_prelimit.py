"""Build a guarded source override from the exact pinned image, without starting a server."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
IMAGE='ghcr.io/hkuds/lightrag@sha256:5bdbd524931b011df246fe20888d110cef691e6804c12cde636a2b746d7de27e'


def build():
    raw=subprocess.check_output(['docker','run','--rm','--entrypoint','cat',IMAGE,'/app/lightrag/operate.py'])
    source=raw.decode('utf-8')
    marker='    # Apply token truncation to chunks using the dynamic limit\n    truncated_chunks = await process_chunks_unified('
    hook='''    # DocTrace: order the complete merged pool BEFORE top-k and token limits.
    # Graph retrieval, graph context, token accounting and reference assembly stay upstream.
    from dataclasses import replace
    from doctrace_ext.prelimit_adapter import apply_policy
    policy_chunks, policy_meta = await asyncio.to_thread(
        apply_policy, query, merged_chunks, mode=query_param.mode
    )
    selection_param = query_param
    if policy_meta["strategy"] != "disabled":
        selection_param = replace(query_param, enable_rerank=False)
    logger.info("DOCTRACE_POLICY strategy=%s calls=%s cache_hits=%s",
                policy_meta["strategy"], policy_meta["provider_calls"], policy_meta["cache_hits"])
    # Apply token truncation to chunks using the dynamic limit
    truncated_chunks = await process_chunks_unified('''
    assert source.count(marker)==1, 'Pinned integration boundary changed'
    source=source.replace(marker,hook)
    start=source.index(hook);end=source.index('    # Generate reference list',start)
    section=source[start:end]
    assert section.count('unique_chunks=merged_chunks,')==1 and section.count('query_param=query_param,')==1
    source=source[:start]+section.replace('unique_chunks=merged_chunks,','unique_chunks=policy_chunks,').replace('query_param=query_param,','query_param=selection_param,')+source[end:]
    marker2='    final_data_payload = final_data.get("data", {})'
    assert source.count(marker2)==1
    source=source.replace(marker2,'    final_data.setdefault("metadata", {})["doctrace_policy"] = policy_meta\n'+marker2)
    compile(source,'operate.py','exec')
    out=ROOT/'runtime/hr_prelimit';out.mkdir(parents=True,exist_ok=True)
    (out/'operate.py').write_text(source,encoding='utf-8')
    manifest={'image':IMAGE,'upstream_sha256':hashlib.sha256(raw).hexdigest(),
              'patched_sha256':hashlib.sha256((out/'operate.py').read_bytes()).hexdigest(),
              'boundary':'merged candidates before process_chunks_unified',
              'source_files':['app/prelimit_adapter.py','app/facet_policy.py','app/rerank.py']}
    (out/'build.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Built guarded pre-limit override:',out/'operate.py')


if __name__=='__main__':build()
