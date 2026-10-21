"""Opt-in LightRAG pre-limit ordering. No answers, new retrieval or automatic retries."""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    import httpx2 as httpx  # DocTrace host environment
except ImportError:
    import httpx  # Pinned LightRAG image

from .facet_policy import rank_with_facets, POLICY_VERSION
from .rerank import map_rerank_results


def apply_policy(question, chunks, *, mode):
    started = time.perf_counter()
    meta = {'version': POLICY_VERSION, 'strategy': 'disabled', 'provider_calls': 0, 'cache_hits': 0}
    if mode != 'mix' or os.environ.get('DOCTRACE_PRELIMIT_ENABLED') != '1' or not chunks:
        return chunks, meta
    values = [os.environ.get('DOCTRACE_RERANK_'+k,'').strip() for k in ('URL','MODEL','API_KEY')]
    if not all(values):
        return chunks, {**meta, 'strategy':'fallback_original', 'error_kind':'configuration_error'}
    url, model, secret = values
    cache = Path(os.environ.get('DOCTRACE_POLICY_CACHE_DIR','/app/data/doctrace_policy_cache'))
    def digest(value):
        return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    pool_hash = digest([{k:c.get(k) for k in ('chunk_id','file_path','content','content_headings')} for c in chunks])
    try:
        cache.mkdir(parents=True,exist_ok=True)
        with httpx.Client(timeout=httpx.Timeout(120,connect=15,write=30,pool=5),trust_env=False) as client:
            def rank_impl(query, pool):
                key = digest({'url':url,'model':model,'query':query,'pool_sha256':pool_hash})
                path = cache/(key+'.json')
                if path.exists():
                    event = json.loads(path.read_text(encoding='utf-8')); meta['cache_hits'] += 1
                    if not isinstance(event,dict) or event.get('key') != key:
                        raise ValueError('Cache identity mismatch')
                else:
                    event = {'key':key,'created_at_utc':datetime.now(timezone.utc).isoformat(),
                             'query':query,'model':model,'pool_sha256':pool_hash,
                             'http_status':None,'error_kind':None,'raw_response':None}
                    call_start = time.perf_counter();meta['provider_calls'] += 1
                    try:
                        response = client.post(url, headers={'Authorization':'Bearer '+secret},
                            json={'model':model,'query':query,'documents':[c['content'] for c in pool],
                                  'top_n':len(pool),'return_documents':False})
                        event['http_status'] = response.status_code
                        # Provider error text is not logged: it may echo authorization data.
                        if response.status_code == 200:
                            event['raw_response'] = response.json()
                            map_rerank_results(pool,event['raw_response']['results'])
                        else:
                            event['error_kind'] = 'http_error'
                    except httpx.TimeoutException:
                        event['error_kind'] = 'timeout'
                    except httpx.RequestError:
                        event['error_kind'] = 'transport_error'
                    except (ValueError,KeyError,TypeError):
                        event['error_kind'] = 'invalid_response'
                    event['elapsed_seconds'] = round(time.perf_counter()-call_start,3)
                    # Atomic publication; incomplete files cannot become cache hits.
                    temp = cache/(key+'.'+uuid4().hex+'.tmp')
                    temp.write_text(json.dumps(event,ensure_ascii=False,indent=2),encoding='utf-8')
                    temp.replace(path)
                if event['error_kind']:
                    return {**event,'ranked_chunks':None}
                return {**event,'ranked_chunks':map_rerank_results(pool,event['raw_response']['results'])}
            def rank(query, pool):
                try:
                    return rank_impl(query,pool)
                except (OSError,ValueError,KeyError,TypeError):
                    # A branch cache failure must not discard a successful whole ranking.
                    return {'http_status':None,'error_kind':'cache_error','ranked_chunks':None}
            result = rank_with_facets(question,chunks,rank)
        meta['strategy'] = result['strategy']
        meta['subqueries'] = result.get('subqueries',[])
        if result.get('fallback_reason'):
            meta['fallback_reason'] = result['fallback_reason']
        if result['ranked_chunks'] is None:
            meta.update(strategy='fallback_original',error_kind=result['whole'].get('error_kind'))
            ordered = chunks
        else:
            ordered = result['ranked_chunks']
        meta['elapsed_seconds'] = round(time.perf_counter()-started,3)
        audit = {'created_at_utc':datetime.now(timezone.utc).isoformat(),'question':question,
                 'pool_sha256':pool_hash,'metadata':meta,'ordered_ids':[c['chunk_id'] for c in ordered]}
        decisions = cache/'decisions';decisions.mkdir(exist_ok=True)
        with (decisions/(uuid4().hex+'.json')).open('x',encoding='utf-8') as f:
            json.dump(audit,f,ensure_ascii=False,indent=2)
        return ordered,meta
    except (OSError,ValueError,KeyError,TypeError):
        # No evidence is invented or silently discarded when caching/configuration fails.
        return chunks,{**meta,'strategy':'fallback_original','error_kind':'adapter_error',
                       'elapsed_seconds':round(time.perf_counter()-started,3)}
