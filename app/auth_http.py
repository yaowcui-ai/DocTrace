"""Shared HTTP safeguards for the authentication router."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from .auth_config import load_auth_settings
from .config import ConfigurationError


def require_trusted_json(request: Request):
    settings = load_auth_settings()
    request.state.auth_settings = settings
    if request.headers.getlist("origin") != [settings.allowed_origin]:
        raise HTTPException(403, "请求来源不受信任。")
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(415, "请使用 JSON 请求。")
    return settings


class AuthRoute(APIRoute):
    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def guarded(request: Request):
            try:
                settings = load_auth_settings()
                request.state.auth_settings = settings
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    require_trusted_json(request)
                response = await original_handler(request)
            except ConfigurationError:
                response = JSONResponse(status_code=503, content={"detail": "登录服务配置不完整或无效。"})
            except RequestValidationError:
                # Pydantic errors may contain raw passwords in input/context.
                response = JSONResponse(status_code=422, content={"detail": "登录请求格式不正确，请检查用户名和密码格式。"})
            except HTTPException as error:
                response = JSONResponse(status_code=error.status_code, content={"detail": error.detail}, headers=error.headers)
            response.headers["Cache-Control"] = "no-store"
            return response

        return guarded
