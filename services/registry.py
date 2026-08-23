"""Instance registry and the caller-supplied base_url guard chain.

Registered hosts come from ``GITHOST_INSTANCES``. Callers may also pass any
Gitea-family base URL; those requests go through ``validate_base_url`` before
anything is fetched: https only, no userinfo, every resolved address checked
against reserved ranges, redirects re-validated per hop by the client layer.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from core.config import settings

# Shared address space (Tailscale, CGNAT). Not always flagged private by
# older ipaddress versions, so it gets its own check.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


@dataclass
class Target:
    """One resolved upstream the client layer can talk to."""

    key: str                 # registry key, or hostname for custom URLs
    base_url: str            # normalized origin, no trailing slash
    token: str | None = None
    custom: bool = False     # caller-supplied, never carries a token
    family: str = "gitea"    # refined by the version probe ("forgejo"|"gitea")
    software: dict = field(default_factory=dict)  # {"name","version"} once probed
    concurrency: int = 4


def parse_instances() -> dict[str, Target]:
    targets: dict[str, Target] = {}
    for chunk in settings.instances_raw.split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, raw_url = chunk.partition("=")
        key = key.strip().lower()
        base = _normalize_origin(raw_url.strip())
        if not key or not base:
            continue
        env_token_key = "GITHOST_TOKEN_" + "".join(c if c.isalnum() else "_" for c in key).upper()
        import os

        token = os.getenv(env_token_key) or None
        concurrency = int(os.getenv(f"GITHOST_CONCURRENCY_{key.upper()}", str(settings.default_registered_concurrency)))
        targets[key] = Target(
            key=key,
            base_url=base,
            token=token,
            concurrency=concurrency,
        )
    return targets


def _normalize_origin(raw: str) -> str | None:
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if parts.scheme != "https":
        return None
    if not parts.hostname:
        return None
    host = parts.hostname.lower()
    origin = f"https://{host}"
    if parts.port and parts.port != 443:
        return None
    return origin


def _is_forbidden_ip(ip: ipaddress._BaseAddress) -> bool:
    if not settings.block_private_ips:
        return False
    try:
        if ip in _CGNAT:
            return True
        return not ip.is_global or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    except ValueError:
        return True


async def _resolve_hostname(host: str) -> list:
    loop = asyncio.get_running_loop()

    def lookup():
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        addresses = []
        for info in infos:
            addresses.append(ipaddress.ip_address(info[4][0]))
        return addresses

    return await loop.run_in_executor(None, lookup)


async def validate_base_url(raw_base_url: str) -> str:
    """Run the SSRF guard chain over a caller-supplied base URL.

    Returns the normalized origin on success; raises HTTPException(400) with a
    reason otherwise. No request has been made when this returns.
    """
    raw = (raw_base_url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="base_url is empty")
    if "://" not in raw:
        raw = f"https://{raw}"

    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise HTTPException(status_code=400, detail="base_url is not a valid URL")
    if parts.scheme != "https":
        raise HTTPException(status_code=400, detail="base_url must use https")
    if parts.username or parts.password or "@" in parts.netloc:
        raise HTTPException(status_code=400, detail="base_url must not contain credentials")
    if port not in (None, 443):
        raise HTTPException(status_code=400, detail="base_url must use port 443")
    host = (parts.hostname or "").lower()
    if not host or len(host) > 253:
        raise HTTPException(status_code=400, detail="base_url hostname missing")

    try:
        addresses = await _resolve_hostname(host)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail=f"base_url host does not resolve: {host}")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"base_url could not be resolved: {exc}")

    if not addresses:
        raise HTTPException(status_code=400, detail="base_url resolved to no addresses")
    for ip in addresses:
        if _is_forbidden_ip(ip):
            raise HTTPException(
                status_code=400,
                detail="base_url points into a reserved or private range",
            )
    return f"https://{host}"


async def resolve_target(
    host: str | None = None,
    base_url: str | None = None,
) -> Target:
    """Resolve ?host= / ?base_url= into one Target; bare requests are rejected."""
    targets = parse_instances()

    if base_url:
        if not settings.allow_custom_base:
            raise HTTPException(status_code=403, detail="Custom base_url support is disabled here")
        origin = await validate_base_url(base_url)
        hostname = urlsplit(origin).hostname or origin
        # A registered key wins when the caller spelled out a known instance.
        for target in targets.values():
            if urlsplit(target.base_url).hostname == hostname:
                return target
        return Target(
            key=hostname,
            base_url=origin,
            token=None,
            custom=True,
            concurrency=settings.custom_concurrency,
        )

    if host:
        key = host.strip().lower()
        if key in targets:
            return targets[key]
        # Tolerate bare hostnames that match a registered instance's domain.
        for target in targets.values():
            if urlsplit(target.base_url).hostname == key:
                return target
        raise HTTPException(
            status_code=404,
            detail=f"Unknown host '{key}'. Registered: {', '.join(sorted(targets))}. Or pass base_url.",
        )

    registered = ", ".join(sorted(targets))
    raise HTTPException(
        status_code=400,
        detail=(
            "No host selected. Pass ?host=<key> or ?base_url=https://... "
            f"(registered: {registered})"
        ),
    )


async def probe_family(base_url: str) -> tuple[str, dict]:
    """Ask /api/v1/version and map the string to (family, software block).

    Forgejo reports versions like ``16.0.3+gitea-1.22.0``; Gitea reports plain
    ``1.x.y``. Anything unparseable degrades to gitea rather than failing.
    """
    try:
        async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
            response = await client.get(f"{base_url}/api/v1/version")
            version = str((response.json() or {}).get("version") or "")
    except Exception:
        version = ""

    major_text = version.split(".", 1)[0]
    try:
        major = int(major_text)
    except ValueError:
        major = 0

    if "+gitea" in version or major >= 2:
        family = "forgejo"
        name = "Forgejo"
    else:
        family = "gitea"
        name = "Gitea"
    software = {"name": name}
    if version:
        software["version"] = version
    return family, software
