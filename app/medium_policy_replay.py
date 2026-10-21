"""Apply actual upstream token rules to saved policy variants without network."""
import argparse, json, sys, subprocess, hashlib
from pathlib import Path
from datetime import datetime, timezone
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from .medium_policy_selector import PROGRAM
from app.evaluate import check_evidence_group_coverage


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path);args=p.parse_args()
    source=json.loads(args.source.read_text(encoding='utf-8'))
    dataset_path=PROJECT/source['dataset_file'];assert hashlib.sha256(dataset_path.read_bytes()).hexdigest()==source['dataset_sha256']
    cases={c['id']:c for c in json.loads(dataset_path.read_text(encoding='utf-8'))['cases']}
    baseline=json.loads((PROJECT/source['baseline_file']).read_text(encoding='utf-8'))
    assert hashlib.sha256((PROJECT/source['baseline_file']).read_bytes()).hexdigest()==source['baseline_sha256']
    originals={r['case_id']:r['result']['data']['chunks'] for r in baseline['records']}
    reference=PROJECT/'evaluation/diagnostics/20261016T044508Z_38dfaa7a_utils.py.txt'
    actual=subprocess.check_output(['docker','exec','doctrace-hr-v3-lightrag_hr_v3-1','sha256sum','/app/lightrag/utils.py'],text=True).split()[0]
    assert actual==hashlib.sha256(reference.read_bytes()).hexdigest(), 'Upstream token selector changed'
    inputs=[]
    for r in source['records']:
        assert r['policy']['ranked_chunks'] is not None
        top=r['chunk_top_k'];inputs.append({'case_id':r['case_id'],'tokenizer':r['tokenizer'],
            'limit':r['budget']['available_chunk_tokens'],'variants':{'original':r['original_chunks'][:top],
            'whole':r['policy']['whole']['ranked_chunks'][:top],'policy':r['policy']['ranked_chunks'][:top]}})
    result=subprocess.run(['docker','exec','-i','doctrace-hr-v3-lightrag_hr_v3-1','/app/.venv/bin/python','-c',PROGRAM],input=json.dumps(inputs),capture_output=True,text=True,encoding='utf-8',check=True)
    measurements=json.loads(result.stdout);rows=[]
    for r,measured in zip(source['records'],measurements):
        assert r['case_id']==measured['case_id'];row={'case_id':r['case_id'],'strategy':r['policy']['strategy'],'variants':{}}
        for name,chunks in [('original',r['original_chunks']),('whole',r['policy']['whole']['ranked_chunks']),('policy',r['policy']['ranked_chunks'])]:
            m=measured['variants'][name];by={c['chunk_id']:c for c in chunks};selected=[by[k] for k in m['selected_ids']]
            coverage=check_evidence_group_coverage(cases[r['case_id']]['evidence_groups'],[{'file_path':c['file_path'],'content':[c['content']]} for c in selected])
            row['variants'][name]={**m,'coverage':coverage}
        assert row['variants']['original']['selected_ids']==[c['chunk_id'] for c in originals[r['case_id']]]
        rows.append(row)
    summary={}
    for name in ['original','whole','policy']:
        summary[name]={'matched':sum(r['variants'][name]['coverage']['matched_count'] for r in rows),
                       'expected':sum(r['variants'][name]['coverage']['expected_count'] for r in rows),
                       'complete':sum(r['variants'][name]['coverage']['coverage']==1 for r in rows),'cases':len(rows)}
    report={'created_at_utc':datetime.now(timezone.utc).isoformat(),'source_file':str(args.source),
            'source_sha256':hashlib.sha256(args.source.read_bytes()).hexdigest(),'dataset_sha256':source['dataset_sha256'],
            'summary':summary,'records':rows,'network_calls':0,'min_score':None,'utils_sha256':actual}
    out=args.output or args.source.with_name(args.source.stem+'_comparison.json')
    with out.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps(summary));print('Report:',out)


if __name__=='__main__':main()
