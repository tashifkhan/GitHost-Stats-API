import pytest
from fastapi import HTTPException

from core.config import settings
from services import registry


@pytest.fixture(autouse=True)
def _allow_custom(monkeypatch):
    monkeypatch.setattr(settings, "allow_custom_base", True)
    monkeypatch.setattr(settings, "block_private_ips", True)


def public_host(monkeypatch, ip="1.2.3.4"):
    async def fake_resolve(host):
        import ipaddress

        return [ipaddress.ip_address(ip)]

    monkeypatch.setattr(registry, "_resolve_hostname", fake_resolve)


def private_host(monkeypatch, ip):
    async def fake_resolve(host):
        import ipaddress

        return [ipaddress.ip_address(ip)]

    monkeypatch.setattr(registry, "_resolve_hostname", fake_resolve)


async def test_rejects_plain_http(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        await registry.validate_base_url("http://git.example.com")
    assert exc.value.status_code == 400


async def test_rejects_userinfo(monkeypatch):
    public_host(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await registry.validate_base_url("https://user:pass@git.example.com")
    assert exc.value.status_code == 400


async def test_rejects_nonstandard_port(monkeypatch):
    public_host(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await registry.validate_base_url("https://git.example.com:8443")
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        "172.16.0.9",
        "169.254.1.1",
        "100.64.126.69",  # Tailscale/CGNAT
    ],
)
async def test_rejects_reserved_ranges(monkeypatch, ip):
    private_host(monkeypatch, ip)
    with pytest.raises(HTTPException) as exc:
        await registry.validate_base_url(f"https://{ip}")
    assert exc.value.status_code == 400
    assert "reserved" in exc.value.detail


@pytest.mark.parametrize(
    "url",
    [
        "https://[::1]",
        "https://[fd00::5]",
        "https://[fe80::1]",
    ],
)
async def test_rejects_reserved_ipv6(monkeypatch, url):
    host = url.split("//", 1)[1].strip("[]")
    private_host(monkeypatch, host.strip("[]"))
    with pytest.raises(HTTPException) as exc:
        await registry.validate_base_url(url)
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "url",
    ["https://::1", "https://fe80::1"],
)
async def test_rejects_bare_ipv6_literals_as_invalid(monkeypatch, url):
    public_host(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await registry.validate_base_url(url)
    assert exc.value.status_code == 400
    assert "valid URL" in exc.value.detail


async def test_accepts_public_host_and_normalizes(monkeypatch):
    public_host(monkeypatch)
    origin = await registry.validate_base_url("https://git.example.com/")
    assert origin == "https://git.example.com"


async def test_disabled_private_block_allows_tailnet(monkeypatch):
    monkeypatch.setattr(settings, "block_private_ips", False)
    private_host(monkeypatch, "100.64.126.69")
    origin = await registry.validate_base_url("https://git.tailnet.example")
    assert origin.startswith("https://")


async def test_unknown_registered_host_lists_options():
    targets = registry.parse_instances()
    if not targets:
        return
    with pytest.raises(HTTPException) as exc:
        await registry.resolve_target(host="does-not-exist")
    assert exc.value.status_code == 404
    for key in targets:
        assert key in exc.value.detail


async def test_bare_request_is_rejected():
    targets = registry.parse_instances()
    if not targets:
        return
    with pytest.raises(HTTPException) as exc:
        await registry.resolve_target()
    assert exc.value.status_code == 400
    assert "No host selected" in exc.value.detail
    for key in targets:
        assert key in exc.value.detail


async def test_precedence_base_url_wins(monkeypatch):
    public_host(monkeypatch)
    targets = registry.parse_instances()
    target = await registry.resolve_target(
        host=next(iter(targets), None),
        base_url="https://git.other.example",
    )
    assert target.base_url == "https://git.other.example"
    assert target.custom is True
    assert target.token is None
