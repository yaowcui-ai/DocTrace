from fastapi import FastAPI, HTTPException, Request, Header, Depends
import httpx2 as httpx
from .answer_config import load_answer_settings
from .config import ConfigurationError, load_settings
from .lightrag_client import LightRAGClient, UpstreamError
from .medium_config import load_medium_settings
from .qa_pipeline import run_medium_qa_pipeline
from .schemas import AskRequest, AskResponse, MediumAskResponse
from contextlib import asynccontextmanager
from .database import create_db_engine
from .database_config import load_database_settings
from .recorded_qa import RecordedQAError, run_recorded_qa
from .logging_config import configure_qa_logging
from .schemas import RecordedAskResponse
import json
from uuid import UUID, uuid4
from time import perf_counter
from .qa_logging import log_qa_event, qa_log_context
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from .qa_records import get_qa_record
from .schemas import QARecordResponse
from fastapi import Query
from .qa_records import list_qa_records
from .schemas import QARecordListResponse
from pathlib import Path
import mimetypes
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .auth_routes import router as auth_router
from .public_example_routes import router as public_example_router
from .auth_routes import read_current_user
from . import auth_http
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from .console_logging import protect_server_console
from .schemas import OptimizedAskRequest
from .qa_pipeline import run_selected_qa_pipeline
from .pipeline_config import load_pipeline_settings
from .rerank_config import load_rerank_settings
# Uvicorn configures logging before importing this module, and emits startup
# messages before FastAPI lifespan. Protect those console writes as well.
protect_server_console()

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_qa_logging()
    try:
        engine = create_db_engine(load_database_settings())
    except ConfigurationError:
        engine = None

    app.state.db_engine = engine

    try:
        yield
    finally:
        app.state.db_engine = None
        if engine is not None:
            engine.dispose()


app = FastAPI(
    title="DocTrace",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(public_example_router)


@app.middleware("http")
async def protect_private_http(request: Request, call_next):
    path = request.url.path.rstrip("/")
    private = path in {"/ask", "/ask/optimized", "/records"} or path.startswith("/records/")
    if private and request.method not in {"GET", "HEAD", "OPTIONS"}:
        try:
            auth_http.require_trusted_json(request)
        except ConfigurationError:
            return JSONResponse(status_code=503, content={"detail": "登录服务配置不完整或无效。"}, headers={"Cache-Control": "no-store"})
        except StarletteHTTPException as error:
            return JSONResponse(status_code=error.status_code, content={"detail": error.detail}, headers={"Cache-Control": "no-store"})
    response = await call_next(request)
    if private or path == '/examples' or path.startswith('/examples/'):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def trace_qa_http(request: Request, call_next):
    path = request.url.path
    if path not in ("/ask", "/ask/optimized", "/records", "/examples") and not path.startswith(("/records/", "/auth/", "/examples/")):
        return await call_next(request)

    started = perf_counter()
    attempt_id = str(uuid4())
    with qa_log_context(attempt_id=attempt_id):
        log_qa_event("http_received", None, stage="HTTP")
        try:
            response = await call_next(request)
        except Exception as error:
            log_qa_event("http_failed", getattr(request.state, "qa_record_id", None),
                stage="HTTP", http_status=500, error_type=type(error).__name__,
                duration_ms=int((perf_counter() - started) * 1000))
            raise
        log_qa_event("http_completed", getattr(request.state, "qa_record_id", None),
            stage="HTTP", http_status=response.status_code,
            duration_ms=int((perf_counter() - started) * 1000))
        response.headers["X-DocTrace-Attempt-ID"] = attempt_id
        return response


WEB_DIR = Path(__file__).resolve().parent / "web"

# Windows may identify .mjs as plain text; browsers require a JavaScript MIME type.
mimetypes.add_type("application/javascript", ".mjs")

app.mount(
    "/static",
    StaticFiles(directory=WEB_DIR),
    name="static",
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "DocTrace"}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, user=Depends(read_current_user)):
    try:
        settings = load_settings()
    except ConfigurationError:
        raise HTTPException(
            status_code=503,
            detail="问答服务配置不完整或无效，请检查后端配置。",
        ) from None
    try:
        return LightRAGClient(settings).ask(request.question)
    except UpstreamError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None


def make_qa_client():
    # Per-operation inactivity limits, not a total pipeline deadline.
    timeout = httpx.Timeout(120.0, connect=5.0, write=30.0, pool=5.0)
    return httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False)

@app.post("/ask/optimized", response_model=RecordedAskResponse)
def ask_optimized(
    request: OptimizedAskRequest,
    http_request: Request,
    user=Depends(read_current_user),
    idempotency_key: UUID | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
):
    try:
        medium = load_medium_settings()
        answer_settings = load_answer_settings()
        if request.mode == "naive":
            load_pipeline_settings()
            load_rerank_settings()
    except ConfigurationError:
        log_qa_event("configuration_failed", None, stage="问答配置", http_status=503)
        raise HTTPException(
            status_code=503,
            detail="问答服务配置不完整或无效，请检查后端配置。",
        ) from None

    engine = http_request.app.state.db_engine

    if engine is None:
        log_qa_event("configuration_failed", None, stage="记录保存", http_status=503)
        raise HTTPException(
            status_code=503,
            detail={
                "stage": "记录保存",
                "message": "数据库配置不完整或无效，请检查后端配置。",
                "request_id": None,
            },
        )

    def answer_fn():
        with make_qa_client() as client:
            return run_selected_qa_pipeline(
                request.question,
                client,
                medium.rag_settings,
                answer_settings,
                mode=request.mode,
                max_total_tokens=medium.max_total_tokens,
            )

    try:
        request_id, answer = run_recorded_qa(
            engine,
            question=request.question,
            corpus_id=medium.corpus_id,
            answer_fn=answer_fn,
            owner_user_id=str(user.user_id),
            idempotency_key=(
                str(idempotency_key)
                if idempotency_key is not None
                else None
            ),
            request_mode=request.mode,
        )
    except RecordedQAError as error:
        http_request.state.qa_record_id = error.request_id
        raise HTTPException(
            status_code=error.status_code,
            detail={
                "stage": error.stage,
                "message": error.detail,
                "request_id": error.request_id,
            },
        ) from None

    http_request.state.qa_record_id = request_id
    return RecordedAskResponse(
        request_id=request_id,
        **answer.model_dump(),
    )

@app.get("/records/{request_id}", response_model=QARecordResponse)
def read_record(request_id: UUID, http_request: Request, user=Depends(read_current_user)):
    http_request.state.qa_record_id = str(request_id)
    engine = http_request.app.state.db_engine

    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="记录查询服务配置不完整或无效。",
        )

    try:
        row = get_qa_record(engine, str(request_id), owner_user_id=str(user.user_id))
    except SQLAlchemyError:
        log_qa_event("record_read_failed", str(request_id), stage="记录读取", http_status=503)
        raise HTTPException(
            status_code=503,
            detail="暂时无法读取问答记录，请稍后再试。",
        ) from None

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="问答记录不存在。",
        )

    try:
        for database_field, response_field in (
            ("references_json", "references"),
            ("retrieval_json", "retrieval"),
        ):
            value = row.pop(database_field)
            row[response_field] = (
                json.loads(value) if value is not None else None
            )

        return QARecordResponse.model_validate(row)
    except (json.JSONDecodeError, ValidationError, TypeError):
        log_qa_event("record_read_failed", str(request_id), stage="记录读取", http_status=500)
        raise HTTPException(
            status_code=500,
            detail="已保存的问答记录格式异常。",
        ) from None

@app.get("/records", response_model=QARecordListResponse)
def read_records(
    http_request: Request,
    user=Depends(read_current_user),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    engine = http_request.app.state.db_engine

    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="记录查询服务配置不完整或无效。",
        )

    try:
        page = list_qa_records(
            engine,
            limit=limit,
            offset=offset,
            owner_user_id=str(user.user_id),
        )
    except SQLAlchemyError:
        log_qa_event("record_read_failed", None, stage="记录列表", http_status=503)
        raise HTTPException(
            status_code=503,
            detail="暂时无法读取问答记录，请稍后再试。",
        ) from None

    try:
        return QARecordListResponse.model_validate(page)
    except ValidationError:
        raise HTTPException(
            status_code=500,
            detail="已保存的问答记录格式异常。",
        ) from None
@app.get("/", response_class=FileResponse, include_in_schema=False)
def homepage():
    return FileResponse(WEB_DIR / "index.html")
