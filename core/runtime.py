"""Request-scoped HTTP client and a total request budget."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
from starlette.responses import JSONResponse
from starlette.routing import Match

logger = logging.getLogger("stats_api")

REQUEST_BUDGET_SECONDS = 8.0
CLIENT_TIMEOUT = 4.0


@dataclass
class RequestState:
    deadline: float
    client: httpx.AsyncClient


state: ContextVar[RequestState | None] = ContextVar("stats_request", default=None)


def remaining(default=6.0):
    """Seconds left in the request budget, or a default outside a request."""
    current = state.get()
    return max(0.001, current.deadline - time.monotonic()) if current else default


@asynccontextmanager
async def http_client():
    """Reuse the request's connection pool; fall back to a short-lived client."""
    current = state.get()
    if current:
        yield current.client
        return
    async with httpx.AsyncClient(timeout=CLIENT_TIMEOUT, follow_redirects=True) as client:
        yield client


def route_template(scope) -> str:
    """Matched route template, never the concrete handle.

    Starlette fills ``scope["route"]`` only inside the router, after this
    middleware has run, so match against the app's routes directly.
    """
    app = scope.get("app")
    for route in getattr(getattr(app, "router", None), "routes", ()):
        try:
            match, _ = route.matches(scope)
        except Exception:
            continue
        if match == Match.FULL:
            return getattr(route, "path", None) or "unmatched"
    return "unmatched"


class RequestBudgetMiddleware:
    def __init__(self, app, seconds=REQUEST_BUDGET_SECONDS):
        self.app, self.seconds = app, seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started, sent, status = time.monotonic(), False, 500
        async with httpx.AsyncClient(timeout=min(CLIENT_TIMEOUT, self.seconds), follow_redirects=True) as client:
            token = state.set(RequestState(started + self.seconds, client))

            async def tracked(message):
                nonlocal sent, status
                if message["type"] == "http.response.start":
                    sent, status = True, message["status"]
                await send(message)

            try:
                await asyncio.wait_for(self.app(scope, receive, tracked), self.seconds)
            except asyncio.TimeoutError:
                if sent:
                    # Headers are already on the wire; ASGI cannot replace them.
                    raise
                response = JSONResponse(
                    {"status": "error", "message": "Upstream request deadline exceeded"},
                    status_code=504, headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, tracked)
            finally:
                state.reset(token)
                logger.log(
                    logging.WARNING if status >= 500 else logging.INFO,
                    "request route=%s status=%s elapsed_ms=%s",
                    route_template(scope), status, int((time.monotonic() - started) * 1000),
                )
