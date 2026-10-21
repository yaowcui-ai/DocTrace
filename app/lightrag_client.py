"""HTTP boundary between DocTrace and LightRAG."""

import httpx2 as httpx
from pydantic import ValidationError

from .config import Settings
from .schemas import AskResponse


class UpstreamError(Exception):
    def __init__(self, status_code: int, detail: str, *, stage: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.stage = stage
        super().__init__(detail)


class LightRAGClient:
    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    def ask(self, question: str) -> AskResponse:
        payload = {
            "query": question,
            "mode": "naive",
            "only_need_context": False,
            "enable_rerank": False,
            "include_references": True,
            "include_chunk_content": True,
        }
        # Separate inactivity limits, not a total wall-clock deadline.
        timeout = httpx.Timeout(120.0, connect=5.0, write=10.0, pool=5.0)
        try:
            with httpx.Client(
                timeout=timeout,
                trust_env=False,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self.settings.lightrag_url + "/query",
                    headers={"X-API-Key": self.settings.lightrag_api_key},
                    json=payload,
                )
        except httpx.TimeoutException:
            raise UpstreamError(504, "等待知识库服务超时，上游可能仍在处理请求。") from None
        except httpx.RequestError:
            raise UpstreamError(503, "无法连接知识库服务，请检查服务状态。") from None

        if response.status_code in (401, 403):
            raise UpstreamError(502, "知识库服务鉴权失败，请检查后端使用的 LightRAG 密钥。")
        if not 200 <= response.status_code < 300:
            raise UpstreamError(502, "知识库服务返回异常状态，请检查上游服务。")

        try:
            # Validate instead of passing arbitrary upstream JSON to users.
            return AskResponse.model_validate(response.json(), strict=True)
        except (ValueError, ValidationError):
            raise UpstreamError(502, "知识库服务响应格式无效。") from None
