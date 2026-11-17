"""Offline regressions for the Vercel 10s timeout work."""

import asyncio
import logging
import time

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core import cache, rate_limit, runtime
from core.runtime import RequestBudgetMiddleware


def _budget_app(seconds):
    app = FastAPI()
    cancelled = asyncio.Event()

    @app.get("/{username}/profile")
    async def stalled(username: str):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    app.add_middleware(RequestBudgetMiddleware, seconds=seconds)
    app.add_middleware(CORSMiddleware, allow_origins=["*"])
    return app, cancelled


async def _get(app, path, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, **kwargs)


class _Stalled:
    """A store client whose every call hangs."""

    def __getattr__(self, name):
        async def hang(*args, **kwargs):
            await asyncio.sleep(60)
        return hang


async def test_budget_returns_504_with_cors_and_cancels_handler(caplog):
    app, cancelled = _budget_app(0.05)
    started = time.monotonic()
    with caplog.at_level(logging.INFO, logger="stats_api"):
        response = await _get(app, "/private-handle/profile", headers={"Origin": "https://example.test"})
    assert time.monotonic() - started < 1
    assert response.status_code == 504
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == "*"
    assert cancelled.is_set()
    logged = caplog.text
    assert "route=/{username}/profile" in logged
    assert "private-handle" not in logged


def test_main_puts_cors_outside_budget_and_cache():
    import main

    order = [m.cls.__name__ for m in main.app.user_middleware]
    assert order == ["CORSMiddleware", "RequestBudgetMiddleware", "CacheRateLimitMiddleware"]


async def test_store_calls_are_bounded_by_request_budget(monkeypatch):
    monkeypatch.setattr(cache, "get_redis", lambda: _Stalled())
    async with httpx.AsyncClient() as client:
        token = runtime.state.set(runtime.RequestState(time.monotonic() + 0.02, client))
        try:
            started = time.monotonic()
            assert await cache.get_json("k") is None
            assert time.monotonic() - started < cache.OPERATION_TIMEOUT
        finally:
            runtime.state.reset(token)


async def test_store_calls_are_bounded_without_request(monkeypatch):
    monkeypatch.setattr(cache, "OPERATION_TIMEOUT", 0.02)
    monkeypatch.setattr(cache, "get_redis", lambda: _Stalled())
    started = time.monotonic()
    assert await cache.get_json("k") is None
    assert await cache.set_json("k", {"a": 1}, 10) is None
    assert time.monotonic() - started < 0.5


async def test_get_json_treats_non_dict_entries_as_miss(monkeypatch):
    class Store:
        async def get(self, key):
            return {"list": "[1,2]", "bad": "{", "ok": '{"a":1}'}[key]

    monkeypatch.setattr(cache, "get_redis", lambda: Store())
    assert await cache.get_json("list") is None
    assert await cache.get_json("bad") is None
    assert await cache.get_json("ok") == {"a": 1}


async def test_upstash_rest_stall_and_error_are_misses(monkeypatch):
    monkeypatch.setattr(cache, "OPERATION_TIMEOUT", 0.02)

    async def stalled(request):
        await asyncio.sleep(60)

    store = cache.UpstashRestRedis("example.test", "token")
    store._client = httpx.AsyncClient(transport=httpx.MockTransport(stalled))
    started = time.monotonic()
    assert await store.get("k") is None
    assert time.monotonic() - started < 0.5

    store._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"error": "ERR"}))
    )
    assert await store.get("k") is None
    assert await store.ttl("k") == -2


async def test_rate_limit_fails_open_when_store_stalls(monkeypatch):
    monkeypatch.setattr(cache, "OPERATION_TIMEOUT", 0.02)
    monkeypatch.setattr(cache, "get_redis", lambda: _Stalled())
    started = time.monotonic()
    result = await rate_limit.check_rate_limit("ip:x", 1, 60, "ip")
    assert result.allowed
    assert time.monotonic() - started < 0.5


async def test_rate_limit_fails_open_on_error_and_without_store(monkeypatch):
    class Broken:
        async def eval(self, *args):
            raise ConnectionError("down")

    monkeypatch.setattr(cache, "get_redis", lambda: Broken())
    assert (await rate_limit.check_rate_limit("ip:x", 1, 60, "ip")).allowed
    monkeypatch.setattr(cache, "get_redis", lambda: None)
    assert (await rate_limit.check_rate_limit("ip:x", 1, 60, "ip")).allowed


async def test_rate_limit_uses_one_eval_and_maps_reply(monkeypatch):
    calls = []

    class Store:
        def __init__(self, reply):
            self.reply = reply

        async def eval(self, script, numkeys, *args):
            calls.append((numkeys, args[:3]))
            return self.reply

    monkeypatch.setattr(cache, "get_redis", lambda: Store([0, 7, 0]))
    denied = await rate_limit.check_rate_limit("ip:x", 1, 60, "ip")
    assert (denied.allowed, denied.retry_after, denied.limited_by) == (False, 7, "ip")

    monkeypatch.setattr(cache, "get_redis", lambda: Store(["1", "42", "3"]))
    allowed = await rate_limit.check_rate_limit("ip:x", 5, 60, "ip")
    assert (allowed.allowed, allowed.remaining) == (True, 3)
    assert calls == [(3, ("backoff:ip:x", "rl:ip:x", "violations:ip:x"))] * 2
