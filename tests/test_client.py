import httpx
import pytest
import respx

from core.config import settings
from services.client import HostClient, UpstreamError
from services.registry import Target


def make_client() -> HostClient:
    return HostClient(Target(key="test", base_url="https://forge.test", concurrency=8))


async def test_paginate_walks_link_headers():
    with respx.mock(base_url="https://forge.test") as mock:
        # More specific route first: respx matches in registration order.
        mock.get("/api/v1/users/taf/repos", params={"page": "2", "limit": "50"}).mock(
            return_value=httpx.Response(200, json=[{"id": 2}, {"id": 3}])
        )
        mock.get("/api/v1/users/taf/repos", params={"limit": 50}).mock(
            return_value=httpx.Response(
                200,
                json=[{"id": 1}],
                headers={
                    "Link": '<https://forge.test/api/v1/users/taf/repos?page=2&limit=50>; rel="next"'
                },
            )
        )
        client = make_client()
        items = await client.paginate("/api/v1/users/taf/repos")
        await client.aclose()
        assert [i["id"] for i in items] == [1, 2, 3]


async def test_404_maps_to_upstream_error():
    with respx.mock(base_url="https://forge.test") as mock:
        mock.get("/api/v1/users/ghost").mock(return_value=httpx.Response(404, json={}))
        client = make_client()
        with pytest.raises(UpstreamError) as exc:
            await client.get_json("/api/v1/users/ghost")
        await client.aclose()
        assert exc.value.status_code == 404


async def test_retry_after_on_429(monkeypatch):
    monkeypatch.setattr(settings, "max_retries", 1)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={}, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    with respx.mock(base_url="https://forge.test") as mock:
        mock.get("/api/v1/version").mock(side_effect=handler)
        client = make_client()
        payload = await client.get_json("/api/v1/version")
        await client.aclose()
        assert payload == {"ok": True}
        assert calls["n"] == 2


async def test_redirect_revalidates_and_blocks_private(monkeypatch):
    from fastapi import HTTPException

    async def fail_validation(origin):
        raise HTTPException(status_code=400, detail="base_url points into a reserved or private range")

    monkeypatch.setattr("services.client.validate_base_url", fail_validation)

    with respx.mock(base_url="https://forge.test") as mock:
        mock.get("/api/v1/sneaky").mock(
            return_value=httpx.Response(
                302,
                headers={"Location": "https://127.0.0.1:8080/api"},
            )
        )
        client = make_client()
        with pytest.raises(HTTPException):
            await client.get_json("/api/v1/sneaky")
        await client.aclose()


async def test_version_probe_detects_forgejo():
    with respx.mock(base_url="https://forge.test") as mock:
        mock.get("/api/v1/version").mock(
            return_value=httpx.Response(200, json={"version": "16.0.3+gitea-1.22.0"})
        )
        mock.get("/api/v1/settings/api").mock(
            return_value=httpx.Response(
                200,
                json={"max_response_items": 50, "default_paging_num": 30},
            )
        )
        client = make_client()
        await client.probe()
        await client.aclose()
        assert client.target.family == "forgejo"
        assert client.max_page_size == 50
