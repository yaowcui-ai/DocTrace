"""Admin-only, allowlisted public experiment reports; no arbitrary file access."""
import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from .product.api import ProductRoute, require_admin, get_engine

REPORT_DIR = Path(__file__).resolve().parents[1]/'evaluation/upgrade/reports'
REGISTRY = {
    'baseline': ('baseline.json', '旧实验与升级基线（非新实验）'),
    'retrieval': ('retrieval.json', '检索重放与可评估范围'),
    'engineering': ('engineering.json', '工程、安全与浏览器验证'),
    'performance': ('performance.json', '本机并发测试与资源边界'),
    'business': ('business.json', '模拟业务任务基准'),
    'retrieval-internal': ('retrieval_internal.json', '新内部测试：检索四方案对照'),
    'generation': ('generation.json', '受控生成样本与失败核查'),
}
router = APIRouter(prefix='/api/v1/admin/reports', tags=['evaluation'], route_class=ProductRoute,
                   dependencies=[Depends(require_admin)])
stats_router = APIRouter(prefix='/api/v1/admin', tags=['statistics'], route_class=ProductRoute,
                         dependencies=[Depends(require_admin)])


@stats_router.get('/stats')
def request_stats(request: Request):
    from .benchmark import latency_summary
    with get_engine(request).connect() as connection:
        rows = connection.execute(text('SELECT status, duration_ms, llm_generated, question FROM qa_records ORDER BY created_at DESC LIMIT 1000')).mappings().all()
    # Synthetic load records are excluded from usage claims, and never expose question text.
    real = [row for row in rows if not row['question'].startswith('[SYNTHETIC LOAD')]
    return {'data': {'sample_size': len(real), 'sample_limit': 1000, 'synthetic_excluded': len(rows)-len(real),
        'completed': sum(row['status'] == 'completed' for row in real),
        'failed': sum(row['status'] == 'failed' for row in real),
        'processing': sum(row['status'] == 'processing' for row in real),
        'model_generated_records': sum(bool(row['llm_generated']) for row in real),
        'recorded_latency_ms': latency_summary([row['duration_ms'] for row in real if row['duration_ms'] is not None]),
        'scope': 'Latest 1000 records; not all-time totals or model correctness. Synthetic load rows excluded.'}}


def load_report(report_id):
    if report_id not in REGISTRY:
        raise HTTPException(404, '报告不存在。')
    filename, title = REGISTRY[report_id]
    path = (REPORT_DIR/filename).resolve()
    if not path.is_relative_to(REPORT_DIR.resolve()) or not path.is_file():
        raise HTTPException(404, '该报告尚未生成。')
    if path.stat().st_size > 5*1024*1024:
        raise HTTPException(503, '报告超过安全读取限制。')
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(503, '报告数据格式异常。') from None
    return {'id': report_id, 'title': title, 'sha256': hashlib.sha256(raw).hexdigest(), 'report': value}


@router.get('')
def reports():
    items = []
    for report_id in REGISTRY:
        try:
            item = load_report(report_id)
            # List metadata only; detailed report bodies are fetched after explicit selection.
            items.append({key: value for key, value in item.items() if key != 'report'})
        except HTTPException as error:
            if error.status_code != 404:
                raise
    return {'data': {'items': items, 'note': '仅列出已实际生成的白名单报告；不在网页发起模型实验。'}}


@router.get('/{report_id}')
def report(report_id: str):
    return {'data': load_report(report_id)}
