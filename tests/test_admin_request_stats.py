from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_admin_stats_are_aggregated_without_private_questions(record_engine):
    from app.upgrade_reports import stats_router
    from app.product.api import require_admin
    from app.qa_records import create_processing_record, save_completed_record
    from app.schemas import AskResponse
    rid = create_processing_record(record_engine, question='Private employee question', corpus_id='test')
    save_completed_record(record_engine, rid, result=AskResponse(response='Answer', references=[], llm_generated=False), duration_ms=123)
    create_processing_record(record_engine, question='[SYNTHETIC LOAD exclude]', corpus_id='test')
    app = FastAPI()
    app.state.db_engine = record_engine
    app.include_router(stats_router)
    app.dependency_overrides[require_admin] = lambda: object()
    with TestClient(app) as client:
        response = client.get('/api/v1/admin/stats')
    assert response.status_code == 200
    data = response.json()['data']
    assert data['completed'] == 1 and data['synthetic_excluded'] == 1
    assert data['recorded_latency_ms']['p50'] == 123
    assert 'Private employee' not in response.text and rid not in response.text
