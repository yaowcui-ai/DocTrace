"""Seed the live cache from verified experiment responses, with no provider calls."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.rerank_config import load_rerank_settings
from app.rerank import map_rerank_results

def provider_matches(record, settings):
    return record.get('model')==settings.rerank_model and record.get('provider_url')==settings.rerank_url

def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',required=True,type=Path);p.add_argument('--journal',required=True,type=Path);a=p.parse_args()
    read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    digest=lambda d:hashlib.sha256(json.dumps(d,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    settings=load_rerank_settings();plan=read(a.plan);snapshots={};jobs=[]
    for entry in plan['entries']:
        path=ROOT/entry['snapshot_file'];assert sha(path)==entry['snapshot_sha256']
        snapshots[entry['snapshot_sha256']]=read(path)
    for line in a.journal.read_text(encoding='utf-8').splitlines():
        event=json.loads(line)
        if event['event']=='report_saved':
            assert sha(event['report_file'])==event['report_sha256']
            report=read(event['report_file'])
            if provider_matches(report,settings):
                jobs.append((report['candidate_snapshot_sha256'],report['question'],report['collection'],event['report_sha256']))
    for path in (ROOT/'runtime/diagnostics/hr_autonomy/rerank_cache').glob('*.json'):
        event=read(path)
        if event['snapshot_sha256'] in snapshots and provider_matches(event,settings):
            jobs.append((event['snapshot_sha256'],event['query'],event['collection'],sha(path)))
    out=ROOT/'runtime/hr_prelimit/cache';out.mkdir(parents=True,exist_ok=True);count=0
    for snapshot_sha,query,collection,source_sha in jobs:
        if collection['error_kind'] is not None:continue
        chunks=snapshots[snapshot_sha]['merged_chunks'];raw=collection['raw_response']
        map_rerank_results(chunks,raw['results'])
        pool=digest([{k:c.get(k) for k in ('chunk_id','file_path','content','content_headings')} for c in chunks])
        key=digest({'url':settings.rerank_url,'model':settings.rerank_model,'query':query,'pool_sha256':pool})
        event={'key':key,'query':query,'model':settings.rerank_model,'pool_sha256':pool,'error_kind':None,
               'http_status':collection['http_status'],'raw_response':raw,'elapsed_seconds':collection['elapsed_seconds'],
               'seeded_from_sha256':source_sha,'snapshot_sha256':snapshot_sha}
        target=out/(key+'.json')
        if not target.exists():
            with target.open('x',encoding='utf-8') as f:json.dump(event,f,ensure_ascii=False,indent=2)
            count+=1
    print('New verified cache entries:',count,'Provider calls: 0')

if __name__=='__main__':main()
