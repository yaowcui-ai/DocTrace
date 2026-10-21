"""Orchestrate retrieval, reranking, evidence selection and answer generation."""

import time
from .pipeline_config import load_pipeline_settings
from .rerank_config import load_rerank_settings
from .answer_client import collect_answer
from .context_builder import build_evidence_context
from .context_selection import select_context
from .lightrag_client import UpstreamError
from .rerank_client import collect_rerank
from .retrieval_client import collect_retrieval
from .schemas import AskResponse, MediumAskResponse, RetrievalInfo
from .facet_policy import POLICY_VERSION
from .qa_logging import log_qa_event, qa_stage

def require_stage_success(record: dict, stage: str) -> None:
    kind = record["error_kind"]
    if kind is None:
        return
    status = 504 if kind == "timeout" else 503 if kind == "transport_error" else 502
    raise UpstreamError(status, f"{stage}服务未成功完成，请检查后端记录后再试。", stage=stage)

def require_medium_policy(metadata: dict | None) -> bool:
    if (
        not isinstance(metadata, dict)
        or metadata.get("version") != POLICY_VERSION
    ):
        raise UpstreamError(
            502,
            "上游未返回受支持的检索策略版本。",
            stage="检索策略",
        )

    strategy = metadata.get("strategy")

    if strategy not in (
        "whole_query_rerank",
        "facet_interleave_v1",
        "fallback_whole_query",
        "fallback_original",
    ):
        raise UpstreamError(
            502,
            "上游检索策略未启用或执行状态无法识别。",
            stage="检索策略",
        )

    return strategy in (
        "fallback_whole_query",
        "fallback_original",
    )

def insufficient_evidence_response(started: float) -> AskResponse:
    log_qa_event("evidence_insufficient", None, outcome="non_generated", chunk_count=0)
    return AskResponse(
        response=(
            "本次检索与筛选未获得足够支持回答的证据，无法确认答案。"
            "当前系统基于公开 HR 政策，不能仅凭这些政策确定个人实际工资、到账金额或审批结果；"
            "这些情况需要通过授权的业务记录核实。"
            "如果你想了解政策规则，可以补充政策名称、适用地区等信息。"
        ),
        references=[],
        response_time=round(time.perf_counter() - started, 3),
        llm_generated=False,
    )

def run_qa_pipeline(
    question,
    client,
    rag_settings,
    rerank_settings,
    answer_settings,
    *,
    max_chars,
    min_score,
) -> AskResponse:
    started = time.perf_counter()

    with qa_stage("检索"):
        retrieval = collect_retrieval(client, rag_settings, question)
        require_stage_success(retrieval, "检索")

    chunks = retrieval["chunks"]
    if not chunks:
        return insufficient_evidence_response(started)

    with qa_stage("重排"):
        reranking = collect_rerank(
            client, rerank_settings, question, chunks
        )
        require_stage_success(reranking, "重排")

    with qa_stage("上下文筛选"):
        selection = select_context(
            reranking["ranked_chunks"],
            max_chars=max_chars,
            min_score=min_score,
        )
    selected = selection["selected_chunks"]

    if not selected:
        return insufficient_evidence_response(started)

    with qa_stage("上下文组装"):
        evidence_bundle = build_evidence_context(selected)
    with qa_stage("回答模型"):
        generation = collect_answer(
            client, answer_settings, question, evidence_bundle
        )
        require_stage_success(generation, "回答模型")
        answer = AskResponse.model_validate(
            generation["result"], strict=True
        )
    answer.response_time = round(time.perf_counter() - started, 3)
    return answer
def run_medium_qa_pipeline(
    question,
    client,
    rag_settings,
    answer_settings,
    *,
    max_total_tokens=40000,
) -> AskResponse:
    started = time.perf_counter()

    with qa_stage("检索"):
        retrieval = collect_retrieval(
            client,
            rag_settings,
            question,
            mode="mix",
            max_total_tokens=max_total_tokens,
        )
        require_stage_success(retrieval, "检索")

    chunks = retrieval["chunks"]
    if not chunks:
        return insufficient_evidence_response(started)

    with qa_stage("检索策略"):
        metadata = retrieval["policy_metadata"]
        degraded = require_medium_policy(metadata)
    log_qa_event("retrieval_ready", None, chunk_count=len(chunks),
        strategy=metadata["strategy"], degraded=degraded)

    retrieval_info = RetrievalInfo(
        mode="mix",
        policy_version=metadata["version"],
        strategy=metadata["strategy"],
        degraded=degraded,
    )

    with qa_stage("上下文组装"):
        evidence_bundle = build_evidence_context(chunks)
    with qa_stage("回答模型"):
        generation = collect_answer(
            client, answer_settings, question, evidence_bundle
        )
        require_stage_success(generation, "回答模型")
        answer = MediumAskResponse.model_validate(
            generation["result"], strict=True
        )
    answer.retrieval = retrieval_info
    answer.response_time = round(time.perf_counter() - started, 3)
    return answer
def run_selected_qa_pipeline(
    question,
    client,
    rag_settings,
    answer_settings,
    *,
    mode="naive",
    max_total_tokens=40000,
) -> MediumAskResponse:
    if mode == "mix":
        return run_medium_qa_pipeline(
            question,
            client,
            rag_settings,
            answer_settings,
            max_total_tokens=max_total_tokens,
        )

    if mode != "naive":
        raise ValueError("mode must be naive or mix")

    pipeline = load_pipeline_settings()
    rerank = load_rerank_settings()

    result = run_qa_pipeline(
        question,
        client,
        rag_settings,
        rerank,
        answer_settings,
        max_chars=pipeline.max_chars,
        min_score=pipeline.min_score,
    )

    return MediumAskResponse(
        **result.model_dump(),
        retrieval=RetrievalInfo(
            mode="naive",
            policy_version="naive-rerank-v1",
            strategy="vector_rerank_context",
            degraded=False,
        ),
    )