"""Local MySQL/API smoke check using an explicitly synthetic saved answer.

Only pre-existing-key POSTs and an invalid-key POST are sent. No fresh-key
question is sent to the answer pipeline. The fixture and report are retained.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import text

from .database import create_db_engine
from .database_config import load_database_settings
from .medium_config import load_medium_settings
from .qa_records import create_processing_record, get_qa_record, save_completed_record
from .schemas import MediumAskResponse

BASE_URL = "http://127.0.0.1:8001"
QUESTION = "【幂等集成测试，非政策提问】读取预先保存的测试答案。"
ANSWER = "【测试脚本预先写入，非模型生成】此内容仅用于验证幂等结果复用，不是 HR 政策答案。"


def main() -> int:
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    path = Path(__file__).resolve().parents[1] / "evaluation" / "runs" / (run_id + "_mysql_idempotency.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"run_id": run_id, "kind": "integration_smoke_not_model_evaluation",
              "created_at": now.isoformat(), "target": BASE_URL, "status": "started",
              "fixture_is_synthetic": True, "probes": []}
    engine = None

    def persist():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def require(condition, code):
        if not condition:
            report["failed_check"] = code
            raise AssertionError(code)

    persist()
    try:
        with httpx.Client(trust_env=False, timeout=15, follow_redirects=False) as client:
            report["step"] = "check_live_api"
            schema = client.get(BASE_URL + "/openapi.json")
            schema.raise_for_status()
            parameters = schema.json()["paths"]["/ask/optimized"]["post"].get("parameters", [])
            require(any(p.get("name") == "Idempotency-Key" and p.get("in") == "header" for p in parameters), "live_api_missing_key_header")

            report["step"] = "prepare_explicit_test_record"
            engine = create_db_engine(load_database_settings())
            corpus_id = load_medium_settings().corpus_id
            key = str(uuid4())
            report.update(corpus_id=corpus_id, idempotency_key=key)
            record_id = create_processing_record(engine, question=QUESTION, corpus_id=corpus_id, idempotency_key=key)
            report["request_id"] = record_id
            persist()
            save_completed_record(engine, record_id, result=MediumAskResponse(response=ANSWER, references=[], llm_generated=False), duration_ms=0)
            before = get_qa_record(engine, record_id)
            with engine.connect() as conn:
                count_before = conn.execute(text("SELECT COUNT(*) FROM qa_records")).scalar_one()

            report["step"] = "confirm_api_reads_same_fixture"
            saved = client.get(BASE_URL + "/records/" + record_id)
            saved.raise_for_status()
            require(saved.json().get("answer") == ANSWER and saved.json().get("status") == "completed", "api_fixture_mismatch")
            require(saved.json().get("corpus_id") == corpus_id, "api_corpus_mismatch")

            report["step"] = "replay_and_reject_probes"
            for name, sent_key, question, expected in [
                ("completed_first", key, QUESTION, 200),
                ("completed_second", key, QUESTION, 200),
                ("different_question_same_key", key, QUESTION + "不同问题", 409),
                ("invalid_key", "not-a-uuid", QUESTION, 422),
            ]:
                response = client.post(BASE_URL + "/ask/optimized", headers={"Idempotency-Key": sent_key}, json={"question": question})
                body = response.json()
                report["probes"].append({"name": name, "http_status": response.status_code, "body": body})
                persist()
                require(response.status_code == expected, name + "_status")
                if expected == 200:
                    require(body.get("request_id") == record_id and body.get("response") == ANSWER, name + "_result")
                    require(body.get("llm_generated") is False, name + "_generation_flag")
                elif expected == 409:
                    require(body.get("detail", {}).get("stage") == "请求校验", "conflict_stage")

            report["step"] = "verify_database_unchanged"
            require(get_qa_record(engine, record_id) == before, "original_record_changed")
            with engine.connect() as conn:
                count_after = conn.execute(text("SELECT COUNT(*) FROM qa_records")).scalar_one()
                key_count = conn.execute(text("SELECT COUNT(*) FROM qa_records WHERE idempotency_key=:key"), {"key": key}).scalar_one()
            report.update(total_before_requests=count_before, total_after_requests=count_after, rows_for_key=key_count, record_unchanged=True)
            require(count_after == count_before and key_count == 1, "unexpected_new_records")
            report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__)
    finally:
        if engine is not None:
            engine.dispose()
        persist()

    print("Status:", report["status"])
    print("Request ID:", report.get("request_id"))
    for probe in report["probes"]:
        print(probe["name"], "HTTP:", probe["http_status"])
    print("Report:", path)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
