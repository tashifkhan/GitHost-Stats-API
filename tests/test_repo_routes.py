import httpx
import pytest
from fastapi import FastAPI

from core import middleware
from core.rate_limit import RateLimitResult
from models.canonical.summary import RepoContributor, Repos, RepoSummary
from routes import canonical
from routes.dependencies import Context
from services.registry import Target


@pytest.mark.parametrize("url", [
    "/alice/repos?host=test&emails=alias@example.test",
    "/f/test/alice/repos?emails=alias@example.test",
])
async def test_repo_routes_resume_partial_results_before_caching(monkeypatch, url):
    cached = {}
    calls = []

    async def get_cache(key):
        return cached.get(key)

    async def set_cache(key, value, ttl):
        cached[key] = value

    async def allowed(*args):
        return RateLimitResult(allowed=True)

    class Service:
        async def get_repos_section(self, username, *, extra_emails):
            calls.append((username, extra_emails))
            return Repos(count=1, repos=[RepoSummary(
                id=1, name="repo", contributors=[RepoContributor(
                    login="bob", name="Bob", avatar_url="bob.png",
                    html_url="https://forge.test/bob", contributions=3,
                )], contributors_complete=len(calls) > 1,
            )])

    ctx = Context(
        target=Target(key="test", base_url="https://forge.test"), client=None,
        analytics=Service(), emails=["alias@example.test"],
    )
    app = FastAPI()
    app.include_router(canonical.router)
    app.dependency_overrides[canonical._ctx] = lambda: ctx
    app.dependency_overrides[canonical._ctx_prefixed] = lambda: ctx
    app.add_middleware(middleware.CacheRateLimitMiddleware)
    monkeypatch.setattr(middleware, "redis_enabled", lambda: True)
    monkeypatch.setattr(middleware, "get_json", get_cache)
    monkeypatch.setattr(middleware, "set_json", set_cache)
    monkeypatch.setattr(middleware, "check_rate_limit", allowed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://api.test") as client:
        partial = await client.get(url)
        assert partial.status_code == 200
        assert partial.json()["data"]["repos"][0]["contributors_complete"] is False
        assert partial.headers["cache-control"] == "no-store"
        assert not cached
        complete = await client.get(url)
        hit = await client.get(url)
    assert complete.status_code == hit.status_code == 200
    assert hit.headers["x-cache"] == "HIT"
    repo = hit.json()["data"]["repos"][0]
    assert repo["contributors_complete"] is True
    assert repo["contributors"][0]["contributions"] == 3
    assert repo["contributors"][0]["avatar_url"] == "bob.png"
    assert hit.json()["instance"] == "test"
    assert calls == [("alice", {"alias@example.test"})] * 2
