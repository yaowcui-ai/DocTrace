"""Anonymous examples are independent from personal records and never call models."""
import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


@pytest.fixture
def api(example_engine, monkeypatch):
    from app import main
    monkeypatch.setattr(main,'create_db_engine',lambda settings:example_engine)
    def forbidden(*args,**kwargs):
        pytest.fail('Public read called private history or model generation')
    for name in ('get_qa_record','list_qa_records','make_qa_client','run_medium_qa_pipeline'):
        monkeypatch.setattr(main,name,forbidden)
    with TestClient(main.app) as client:
        yield client


def seed(engine):
    with engine.begin() as conn:
        for number,status in [(1,'published'),(2,'draft'),(3,'published'),(4,'withdrawn'),(5,'published')]:
            conn.execute(text('''INSERT INTO public_examples
                (example_id,question,answer,references_json,corpus_id,status,created_at,updated_at,published_at)
                VALUES (:id,:question,'synthetic answer',:refs,'synthetic',:status,
                '2026-10-17 00:00:00','2026-10-17 00:00:00',:published)'''),{
                    'id':str(UUID(int=number)), 'question':f'synthetic question {number}', 'status':status,
                    'published':None if status=='draft' else '2026-10-17 00:00:00',
                    'refs':json.dumps([{'reference_id':'1','file_path':'synthetic.md','content':['synthetic evidence']}]),
                })


def test_empty_public_list_is_anonymous_and_does_not_create_data(api,example_engine):
    response=api.get('/examples')
    assert response.status_code==200
    assert response.json()=={'items':[],'limit':10,'offset':0,'has_more':False,'next_offset':None}
    assert response.headers['cache-control']=='no-store'
    with example_engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM public_examples')).scalar_one()==0


def test_list_filters_before_pagination_and_uses_stable_tiebreak(api,example_engine):
    seed(example_engine)
    first=api.get('/examples?limit=2&offset=0').json()
    assert [item['example_id'] for item in first['items']]==[str(UUID(int=5)),str(UUID(int=3))]
    assert first['has_more'] and first['next_offset']==2
    assert set(first['items'][0])=={'example_id','question','corpus_id','published_at'}
    last=api.get('/examples?limit=2&offset=2').json()
    assert [item['example_id'] for item in last['items']]==[str(UUID(int=1))]
    assert last['next_offset'] is None


def test_published_detail_returns_snapshot_evidence_without_private_metadata(api,example_engine):
    seed(example_engine)
    response=api.get('/examples/'+str(UUID(int=1)))
    assert response.status_code==200
    body=response.json()
    assert set(body)=={'example_id','question','answer','references','corpus_id','published_at'}
    assert body['references'][0]['content']==['synthetic evidence']
    assert body['published_at'].endswith('Z')
    assert response.headers['cache-control']=='no-store'


@pytest.mark.parametrize('identifier',[2,4,999])
def test_draft_withdrawn_and_unknown_details_all_404(api,example_engine,identifier):
    seed(example_engine)
    response=api.get('/examples/'+str(UUID(int=identifier)))
    assert response.status_code==404
    assert response.json()=={'detail':'公开示例不存在。'}


@pytest.mark.parametrize('query',['?limit=0','?limit=101','?offset=-1'])
def test_invalid_page_parameters_rejected(api,query):
    assert api.get('/examples'+query).status_code==422


def test_public_routes_do_not_open_private_records(api):
    assert api.get('/records').status_code==401
    assert api.get('/records/'+str(UUID(int=1))).status_code==401
    assert api.post('/examples',json={'status':'published'}).status_code==405


def test_database_failure_is_safe_503(api,example_engine,monkeypatch):
    def fail():raise SQLAlchemyError('private database details')
    monkeypatch.setattr(example_engine,'connect',fail)
    for path in ('/examples','/examples/'+str(UUID(int=1))):
        response=api.get(path)
        assert response.status_code==503
        assert 'private database details' not in response.text


def test_invalid_saved_evidence_is_safe_500(api,example_engine):
    seed(example_engine)
    with example_engine.begin() as conn:
        conn.execute(text("UPDATE public_examples SET references_json='private-malformed-json' WHERE example_id=:id"),{'id':str(UUID(int=1))})
    response=api.get('/examples/'+str(UUID(int=1)))
    assert response.status_code==500
    assert 'private-malformed-json' not in response.text
