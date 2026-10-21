"""Read-only local liveness/auth probe; bypass system proxies, never send a question."""
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import httpx2 as httpx

BASE_URL = 'http://127.0.0.1:8001'


def make_client():
    return httpx.Client(trust_env=False,follow_redirects=False,timeout=3.0)


def probe(client):
    report={'kind':'direct_local_service_probe','provider_requests':0,'probes':[],'status':'passed'}
    for path, expected in (('/health',200),('/records',401)):
        started=perf_counter()
        item={'path':path,'expected_http_status':expected}
        try:
            response=client.get(BASE_URL+path)
            item['http_status']=response.status_code
            valid=response.status_code==expected
            if path=='/health' and valid:
                valid=response.json()=={'status':'ok','service':'DocTrace'}
            item['passed']=valid
        except (httpx.RequestError,ValueError) as error:
            item.update(http_status=None,passed=False,error_type=type(error).__name__)
        item['milliseconds']=round((perf_counter()-started)*1000)
        report['probes'].append(item)
        if not item['passed']:
            report['status']='failed'
    return report


def main():
    with make_client() as client:
        report=probe(client)
    target=Path(__file__).resolve().parent.parent/'evaluation/runs'/(
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_local_service_check.json')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    print('Report:',target)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
