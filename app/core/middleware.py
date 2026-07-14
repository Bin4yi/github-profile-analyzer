"""
HTTP access logging — one line per request, written to logs/http_access.log via the
dedicated logger set up in logging_config.py (kept separate from app.log on purpose).
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging_config import get_access_logger

_access_logger = get_access_logger()


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()

        forwarded_for = request.headers.get("x-forwarded-for", "")
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else None
        if not client_ip:
            client_ip = request.client.host if request.client else "-"

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            user_agent = request.headers.get("user-agent", "-")
            query = f"?{request.url.query}" if request.url.query else ""
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime())

            _access_logger.info(
                '%s - [%s] "%s %s%s HTTP/1.1" %d %.1fms "%s"',
                client_ip,
                timestamp,
                request.method,
                request.url.path,
                query,
                status_code,
                duration_ms,
                user_agent,
            )