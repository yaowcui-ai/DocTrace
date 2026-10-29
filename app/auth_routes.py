"""Session login and current-user HTTP endpoints."""

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from .authentication import authenticate_user
from .auth_config import SESSION_COOKIE_NAME
from .auth_http import AuthRoute
from .auth_schemas import CurrentUserResponse, LoginRequest
from .sessions import SessionUserUnavailable, create_session, get_session_user, revoke_session

router = APIRouter(prefix="/auth", tags=["authentication"], route_class=AuthRoute)


@router.post("/login", response_model=CurrentUserResponse)
def login(payload: LoginRequest, request: Request, response: Response):
    limiter = getattr(request.app.state, 'login_limiter', None)
    if limiter is not None:
        import hashlib
        host = request.client.host if request.client else 'unknown'
        # Both account and client limits apply; raw credentials are never retained.
        for key in ('host:' + host, 'user:' + hashlib.sha256(payload.username.encode()).hexdigest()):
            retry = limiter.check(key)
            if retry is not None:
                raise HTTPException(429, '登录尝试过于频繁，请稍后再试。', headers={'Retry-After': str(retry)})
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="登录服务暂时不可用。",
        )

    settings = request.state.auth_settings

    try:
        user = authenticate_user(
            engine,
            payload.username,
            payload.password.get_secret_value(),
        )

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="用户名或密码不正确，或账户不可用。",
            )

        token, expires_at = create_session(
            engine,
            user_id=user["user_id"],
            ttl_seconds=settings.session_ttl_seconds,
        )
    except SessionUserUnavailable:
        raise HTTPException(
            status_code=401,
            detail="用户名或密码不正确，或账户不可用。",
        ) from None
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="登录服务暂时不可用。",
        ) from None

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        expires=expires_at,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )

    return CurrentUserResponse(**user)


@router.post("/logout", status_code=204, response_class=Response)
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        engine = getattr(request.app.state, "db_engine", None)
        if engine is None:
            raise HTTPException(503, "暂时无法退出登录，请稍后重试。")
        try:
            revoke_session(engine, token)
        except SQLAlchemyError:
            raise HTTPException(503, "暂时无法退出登录，请稍后重试。") from None
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=request.state.auth_settings.cookie_secure,
        httponly=True, samesite="strict",
    )
    return response

@router.get("/me", response_model=CurrentUserResponse)
def read_current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="请先登录，或重新登录。",
        )

    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="身份验证服务暂时不可用。",
        )

    try:
        user = get_session_user(engine, token)
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="身份验证服务暂时不可用。",
        ) from None

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="请先登录，或重新登录。",
        )

    expected = request.headers.get("X-DocTrace-User-ID")
    if expected is not None and expected != user["user_id"]:
        raise HTTPException(409, "登录身份已改变，请刷新页面后重试。", headers={"X-DocTrace-Identity-Changed": "1"})
    return CurrentUserResponse(**user)
