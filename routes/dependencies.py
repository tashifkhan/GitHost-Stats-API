"""Per-request context: one resolved target plus its client and service."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi import Query

from services.analytics import AnalyticsService
from services.client import HostClient
from services.registry import Target, resolve_target


@dataclass
class Context:
    target: Target
    client: HostClient
    analytics: AnalyticsService
    emails: list[str] = field(default_factory=list)


async def build_context(
    host: str | None = None,
    base_url: str | None = None,
    emails_csv: str | None = None,
) -> Context:
    """Resolve ?host= / ?base_url= into an open context; bare requests are rejected."""
    target = await resolve_target(host=host, base_url=base_url)
    client = HostClient(target)
    try:
        # Family/software must be known before the envelope is built. Probe
        # failures degrade gracefully to gitea defaults inside the client.
        await asyncio.wait_for(client.probe(), timeout=8.0)
    except Exception:
        pass
    return Context(
        target=target,
        client=client,
        analytics=AnalyticsService(client, target),
        emails=[e.strip().lower() for e in (emails_csv or "").split(",") if e.strip()],
    )


async def request_context(
    host: str | None = Query(None, description="Registered instance key, e.g. taf | codeberg | gitea"),
    base_url: str | None = Query(None, description="Any Gitea-family instance URL (SSRF-guarded)"),
    emails: str | None = Query(None, description="Comma-separated extra commit emails"),
) -> AsyncIterator[Context]:
    ctx = await build_context(host=host, base_url=base_url, emails_csv=emails)
    try:
        yield ctx
    finally:
        await ctx.client.aclose()


async def prefixed_context(
    host: str,
    emails: str | None = None,
) -> AsyncIterator[Context]:
    ctx = await build_context(host=host, emails_csv=emails)
    try:
        yield ctx
    finally:
        await ctx.client.aclose()
