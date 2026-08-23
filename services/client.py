"""HTTP layer for one resolved git host.

One ``HostClient`` per request target: auth header when a token is registered,
a politeness semaphore per host, ``Link``-header pagination walking with page
caps, version/settings probes cached in-process plus Redis when available,
and 429/Retry-After handling that treats throttling as weather.
"""

import asyncio
import random
from urllib.parse import parse_qs, urlsplit

import httpx

from core.cache import get_json, redis_enabled, set_json
from core.config import settings
from services.registry import Target, validate_base_url


class UpstreamError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        segment = part.strip()
        if not segment.lower().endswith('rel="next"'):
            continue
        url_part = segment.split(";", 1)[0].strip()
        if url_part.startswith("<") and url_part.endswith(">"):
            return url_part[1:-1]
    return None


class HostClient:
    def __init__(self, target: Target):
        self.target = target
        self._semaphore = asyncio.Semaphore(max(target.concurrency, 1))
        self._client = httpx.AsyncClient(
            base_url=target.base_url,
            timeout=settings.upstream_timeout_seconds,
            follow_redirects=False,
            headers={
                "Accept": "application/json",
                **({"Authorization": f"token {target.token}"} if target.token else {}),
            },
        )
        self.max_page_size = 50
        self._probe_task: asyncio.Task | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- core request -----------------------------------------------------

    async def _request(self, path: str, params: dict | None) -> httpx.Response:
        hops = 0
        url: str | None = path
        request_params = params
        while True:
            async with self._semaphore:
                response = await self._client.get(url or "/", params=request_params)
            if not response.is_redirect:
                return response
            location = response.headers.get("location")
            if not location or hops >= 3:
                raise UpstreamError(response.status_code or 502, "Upstream redirect loop")
            # Re-run the SSRF chain on every hop; a friendly public URL can
            # 302 into a private address.
            split = urlsplit(location)
            await validate_base_url(f"{split.scheme}://{split.netloc}")
            url = location
            request_params = None
            hops += 1

    async def get_with_meta(self, path: str, params: dict | None = None):
        """GET one JSON document; returns ``(payload, headers)``."""
        delay = 0.5
        last_error: Exception | None = None
        for attempt in range(settings.max_retries + 1):
            try:
                response = await self._request(path, params)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.status_code == 200:
                    try:
                        return response.json(), response.headers
                    except ValueError as exc:
                        raise UpstreamError(502, "Upstream returned invalid JSON") from exc
                if response.status_code == 404:
                    raise UpstreamError(404, "Not found on this host")
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    retry_after = response.headers.get("retry-after")
                    if retry_after:
                        try:
                            delay = min(float(retry_after), 30.0)
                        except ValueError:
                            pass
                    last_error = UpstreamError(
                        response.status_code, f"Upstream returned {response.status_code}"
                    )
                else:
                    raise UpstreamError(
                        response.status_code, f"Upstream returned {response.status_code}"
                    )
            jittered = min(delay * (1 + random.random() * 0.25), 30.0)
            await asyncio.sleep(jittered)
            delay *= 2
        raise UpstreamError(502, f"Upstream unreachable: {last_error}")

    async def get_json(self, path: str, params: dict | None = None):
        payload, _headers = await self.get_with_meta(path, params)
        return payload

    async def paginate(self, path: str, params: dict | None = None, max_pages: int = 100) -> list:
        """Walk every page of a list endpoint via ``Link rel="next"``."""
        items: list = []
        base = dict(params or {})
        base.setdefault("limit", self.max_page_size)

        url_path: str | None = path
        request_params: dict | None = base
        pages = 0
        seen_pages: set[int] = set()
        while url_path and pages < max_pages:
            data, headers = await self.get_with_meta(url_path, request_params)
            if not isinstance(data, list):
                break
            items.extend(data)
            pages += 1

            next_url = _parse_next_link(headers.get("link"))
            if not next_url:
                break
            split = urlsplit(next_url)
            query = parse_qs(split.query)
            try:
                page_no = int((query.get("page") or ["1"])[0])
            except ValueError:
                page_no = pages + 1
            if page_no in seen_pages:
                break
            seen_pages.add(page_no)
            url_path = split.path
            request_params = {k: v[0] for k, v in query.items()}
        return items

    # ---- probes -----------------------------------------------------------

    def probe(self) -> asyncio.Task:
        """Kick off (once) the version + settings probes for this target."""
        if self._probe_task is None:
            self._probe_task = asyncio.create_task(self._run_probes())
        return self._probe_task

    async def _run_probes(self) -> None:
        target = self.target
        cache_key = f"githost:probe:{target.base_url}"
        cached = await get_json(cache_key) if redis_enabled() else None
        if cached and cached.get("family"):
            target.family = cached["family"]
            target.software = cached.get("software") or {}
            if cached.get("max_response_items"):
                self.max_page_size = max(1, min(int(cached["max_response_items"]), 100))
            return

        family = target.family
        software: dict = {}
        version = ""
        try:
            version_payload = await self.get_json("/api/v1/version")
            version = str((version_payload or {}).get("version") or "")
            try:
                major = int(version.split(".", 1)[0])
            except ValueError:
                major = 0
            if "+gitea" in version or major >= 2:
                family = "forgejo"
                software["name"] = "Forgejo"
            else:
                family = "gitea"
                software["name"] = "Gitea"
            if version:
                software["version"] = version
        except Exception:
            pass

        try:
            api_settings = await self.get_json("/api/v1/settings/api")
            cap = int((api_settings or {}).get("max_response_items") or 50)
            self.max_page_size = max(1, min(cap, 100))
        except Exception:
            pass

        target.family = family
        target.software = software
        if redis_enabled():
            await set_json(
                cache_key,
                {"family": family, "software": software, "max_response_items": self.max_page_size},
                settings.version_ttl,
            )
