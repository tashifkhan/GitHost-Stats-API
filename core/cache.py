import json
from base64 import b64decode, b64encode
from typing import Any

import httpx
from redis import asyncio as redis

from core.config import settings


class UpstashRestRedis:
    """The slice of the Redis API this app uses, spoken over Upstash's REST API.

    Vercel's integration provisions only a REST pair, so a deployment that
    looks fully configured would otherwise find ``REDIS_URL`` empty and
    silently run with no cache at all.
    """

    def __init__(self, url: str, token: str):
        url = url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        self._url = url
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5.0, headers=self._headers)
        return self._client

    async def _command(self, *parts: Any) -> Any:
        response = await self._http().post(self._url, json=[str(part) for part in parts])
        if response.status_code != 200:
            return None
        return response.json().get("result")

    async def get(self, key: str) -> Any:
        return await self._command("GET", key)

    async def setex(self, key: str, ttl_seconds: int, value: str) -> Any:
        return await self._command("SET", key, value, "EX", ttl_seconds)

    async def ttl(self, key: str) -> int:
        result = await self._command("TTL", key)
        return int(result) if result is not None else -2

    async def incr(self, key: str) -> int:
        result = await self._command("INCR", key)
        return int(result) if result is not None else 0

    async def expire(self, key: str, ttl_seconds: int) -> Any:
        return await self._command("EXPIRE", key, ttl_seconds)

    async def delete(self, key: str) -> Any:
        return await self._command("DEL", key)

    # Hash commands used by the deep history manifest.
    async def hset(self, key: str, field: str, value: str) -> Any:
        return await self._command("HSET", key, field, value)

    async def hgetall(self, key: str) -> dict[str, str] | None:
        result = await self._command("HGETALL", key)
        if not isinstance(result, list) or not result:
            return None if result is None else {}
        pairs = {}
        it = iter(result)
        for field, value in zip(it, it):
            pairs[field] = value
        return pairs or None

    async def hdel(self, key: str, *fields: str) -> Any:
        if not fields:
            return None
        return await self._command("HDEL", key, *fields)


_client: redis.Redis | UpstashRestRedis | None = None


def redis_enabled() -> bool:
    return bool(settings.redis_url) or bool(
        settings.upstash_rest_url and settings.upstash_rest_token
    )


def get_redis() -> redis.Redis | UpstashRestRedis | None:
    global _client
    if _client is not None:
        return _client

    if settings.redis_url:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    elif settings.upstash_rest_url and settings.upstash_rest_token:
        _client = UpstashRestRedis(settings.upstash_rest_url, settings.upstash_rest_token)

    return _client


async def get_json(key: str) -> dict[str, Any] | None:
    client = get_redis()
    if client is None:
        return None
    try:
        value = await client.get(key)
    except Exception:
        return None
    if not value:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return None


async def set_json(key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        await client.setex(key, ttl_seconds, json.dumps(value, separators=(",", ":")))
    except Exception:
        return


async def delete_key(key: str) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        await client.delete(key)
    except Exception:
        return


def encode_body(body: bytes) -> str:
    return b64encode(body).decode("ascii")


def decode_body(body: str) -> bytes:
    return b64decode(body.encode("ascii"))
