"""Enforce bytes while ASGI receives request data, including chunked bodies."""
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or scope.get('method') in {'GET', 'HEAD', 'OPTIONS'}:
            return await self.app(scope, receive, send)
        limit = 1_200_000 if path.startswith('/api/v1/admin/documents') else 32_000
        headers = dict(scope.get('headers', []))
        length = headers.get(b'content-length')
        if length is not None:
            try:
                size = int(length)
                assert size >= 0
            except (ValueError, AssertionError):
                response = JSONResponse({'detail': '请求长度格式无效。'}, status_code=400, headers={'Cache-Control': 'no-store'})
                return await response(scope, receive, send)
            if size > limit:
                response = JSONResponse({'detail': '请求内容超过大小限制。'}, status_code=413, headers={'Cache-Control': 'no-store'})
                return await response(scope, receive, send)
        received = 0
        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > limit:
                    raise HTTPException(413, '请求内容超过大小限制。', headers={'Cache-Control': 'no-store'})
            return message
        return await self.app(scope, bounded_receive, send)
