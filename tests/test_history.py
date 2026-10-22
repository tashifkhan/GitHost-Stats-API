import asyncio
import httpx
import pytest
import respx

from core.config import settings
from services.client import HostClient
from services.history import HistoryService, _matches_identity
from services.registry import Target


def commit(sha: str, login=None, name="Dev", email="dev@x.y", day="2026-01-15") -> dict:
    from datetime import datetime, timezone

    iso = datetime.fromisoformat(f"{day}T10:00+00:00").astimezone(timezone.utc).isoformat()
    return {
        "sha": sha,
        "commit": {"author": {"name": name, "email": email, "date": iso}},
        "author": {"login": login} if login else None,
        "parents": [{"sha": "p"}],
    }


def make_service() -> HistoryService:
    target = Target(key="test", base_url="https://forge.test", concurrency=8)
    client = HostClient(target)
    return HistoryService(client, target, "test")


REPO = {"id": 7, "name": "dotfiles", "owner": {"login": "taf"}}


async def test_append_when_prev_head_seen():
    """Pages newer than the stored head SHA merge; older pages never re-count."""
    shas = [commit("c3", login="taf"), commit("c2", login="taf"), commit("c1", login="taf")]
    with respx.mock(base_url="https://forge.test") as forge:
        forge.get("/api/v1/repos/taf/dotfiles/commits").mock(return_value=httpx.Response(200, json=shas))
        service = make_service()
        outcome = await service._walk_repo(
            repo=REPO,
            username="taf",
            emails=set(),
            entry={"pushed_at": "old", "head_sha": "c2", "oldest_sha": "c1", "complete": True},
            pushed_at="new",
            deadline=float("inf"),
        )
        await service.client.aclose()

    assert outcome["status"] == "append"
    assert outcome["days"] == {"2026-01-15": 1}


async def test_replace_on_full_exhaustion(monkeypatch):
    """Force-push rewrite: head SHA never seen, repo exhausted, wholesale replace."""
    monkeypatch.setattr(settings, "history_max_pages", 10)
    shas = [commit("z9", login="taf"), commit("z8", login="someone")]
    with respx.mock(base_url="https://forge.test") as forge:
        forge.get("/api/v1/repos/taf/dotfiles/commits").mock(return_value=httpx.Response(200, json=shas))
        service = make_service()
        outcome = await service._walk_repo(
            repo=REPO,
            username="taf",
            emails={"taf@codeberg.org"},
            entry={"pushed_at": "old", "head_sha": "dead", "oldest_sha": "old1", "complete": True},
            pushed_at="newer",
            deadline=float("inf"),
        )
        await service.client.aclose()

    assert outcome["status"] == "replace"
    assert outcome["days"] == {"2026-01-15": 1}
    assert outcome["head_sha"] == "z9"


async def test_incomplete_on_page_cap(monkeypatch):
    """Cap reached without finishing: partial progress is kept as a seed."""
    monkeypatch.setattr(settings, "history_max_pages", 2)

    def handler(request):
        page = int(request.url.params.get("page") or 1)
        # Full pages so the walk hits the cap rather than exhausting early.
        return httpx.Response(200, json=[commit(f"s{page}-{i}", login="taf") for i in range(50)])

    with respx.mock(base_url="https://forge.test") as forge:
        forge.get("/api/v1/repos/taf/dotfiles/commits").mock(side_effect=handler)
        service = make_service()
        outcome = await service._walk_repo(
            repo=REPO,
            username="taf",
            emails=set(),
            entry=None,
            pushed_at="p",
            deadline=float("inf"),
        )
        await service.client.aclose()

    assert outcome["status"] == "incomplete"
    assert outcome["days"] == {"2026-01-15": 100}
    assert outcome["head_sha"] == "s1-0"
    assert outcome["oldest_sha"] == "s2-49"


async def test_resume_counts_tail_beyond_boundary(monkeypatch):
    """During a resume, commits older than the stored oldest still count."""
    monkeypatch.setattr(settings, "history_max_pages", 5)

    def handler(request):
        page = int(request.url.params.get("page") or 1)
        if page == 1:
            # Full stored-interior page: head + mids.
            body = [commit("h1", login="taf")] + [
                commit(f"m{i}", login="taf", day="2026-01-05") for i in range(49)
            ]
        elif page == 2:
            # Boundary mid-page: oldest marker then NEW older work continues.
            body = [commit("o1", login="taf")] + [
                commit(f"t{i}", login="taf", day="2026-01-01") for i in range(49)
            ]
        else:
            body = []
        return httpx.Response(200, json=body)

    with respx.mock(base_url="https://forge.test") as forge:
        forge.get("/api/v1/repos/taf/dotfiles/commits").mock(side_effect=handler)
        service = make_service()
        outcome = await service._walk_repo(
            repo=REPO,
            username="taf",
            emails=set(),
            entry={"pushed_at": "p", "head_sha": "h1", "oldest_sha": "o1", "complete": False, "page": None},
            pushed_at="p",
            deadline=float("inf"),
        )
        await service.client.aclose()

    assert outcome["status"] == "append"
    # 49 tail commits beyond the boundary, all on 2026-01-01.
    assert outcome["days"] == {"2026-01-01": 49}


async def test_timeout_after_boundary_stays_incomplete(monkeypatch):
    """Crossing the bookmark under a deadline is not completion."""
    monkeypatch.setattr(settings, "history_max_pages", 40)

    def handler(request):
        page = int(request.url.params.get("page") or 1)
        if page == 1:
            body = [commit("h1", login="taf")] + [
                commit(f"m{i}", login="taf", day="2026-01-05") for i in range(49)
            ]
        elif page == 2:
            # Boundary mid-page, then more tail pages follow (pages 3+).
            body = [commit("o1", login="taf")] + [
                commit(f"t{i}", login="taf", day="2026-01-01") for i in range(49)
            ]
        else:
            body = [commit(f"deep-{page}-{i}", login="taf", day="2026-01-01") for i in range(50)]
        return httpx.Response(200, json=body)

    async def slow_send(request):
        await asyncio.sleep(1.2)
        return handler(request)

    with respx.mock(base_url="https://forge.test") as forge:
        forge.get("/api/v1/repos/taf/dotfiles/commits").mock(side_effect=slow_send)
        service = make_service()
        loop = asyncio.get_running_loop()
        outcome = await service._walk_repo(
            repo=REPO,
            username="taf",
            emails=set(),
            entry={"pushed_at": "p", "head_sha": "h1", "oldest_sha": "o1", "complete": False, "page": None},
            pushed_at="p",
            deadline=loop.time() + 3.0,
        )
        await service.client.aclose()

    assert outcome["status"] == "incomplete"
    # Page 2 boundary + tails (49) and one deep page (50) fit in the budget.
    assert outcome["days"]["2026-01-01"] == 99
    assert outcome["oldest_sha"].startswith("deep-")


async def test_resume_boundary_at_repo_end():
    """When the stored oldest is also the repo's last commit, append is clean."""
    monkeypatch_cap = None

    def handler(request):
        page = int(request.url.params.get("page") or 1)
        if page == 1:
            body = [commit("h1", login="taf")] + [
                commit(f"m{i}", login="taf", day="2026-01-05") for i in range(49)
            ]
        else:
            body = [commit("o1", login="taf")]
        return httpx.Response(200, json=body)

    with respx.mock(base_url="https://forge.test") as forge:
        forge.get("/api/v1/repos/taf/dotfiles/commits").mock(side_effect=handler)
        service = make_service()
        outcome = await service._walk_repo(
            repo=REPO,
            username="taf",
            emails=set(),
            entry={"pushed_at": "p", "head_sha": "h1", "oldest_sha": "o1", "complete": False, "page": None},
            pushed_at="p",
            deadline=float("inf"),
        )
        await service.client.aclose()

    assert outcome["status"] == "append"
    assert outcome["days"] == {}


async def test_identity_email_local_part(monkeypatch):
    shas = [commit("e1", name="Anyone", email="taf@noreply.example")]
    with respx.mock(base_url="https://forge.test") as forge:
        forge.get("/api/v1/repos/taf/dotfiles/commits").mock(return_value=httpx.Response(200, json=shas))
        service = make_service()
        outcome = await service._walk_repo(
            repo=REPO,
            username="taf",
            emails=set(),
            entry=None,
            pushed_at="p",
            deadline=float("inf"),
        )
        await service.client.aclose()

    assert outcome["status"] == "replace"
    assert outcome["days"] == {"2026-01-15": 1}


async def test_deadline_stops_walk(monkeypatch):
    monkeypatch.setattr(settings, "history_max_pages", 100)
    with respx.mock(base_url="https://forge.test") as forge:

        def endless(request):
            page = int(request.url.params.get("page") or 1)
            return httpx.Response(200, json=[commit(f"p{page}", login="taf")] * 50)

        forge.get("/api/v1/repos/taf/dotfiles/commits").mock(side_effect=endless)
        service = make_service()
        import asyncio

        loop = asyncio.get_running_loop()
        outcome = await service._walk_repo(
            repo=REPO,
            username="taf",
            emails=set(),
            entry=None,
            pushed_at="p",
            deadline=loop.time() + 0.05,
        )
        await service.client.aclose()

    assert outcome["status"] == "incomplete"


@pytest.mark.parametrize("message,emails,expected", [
    ("Shared work\n\nCo-authored-by: Someone <taf@noreply.example>", set(), True),
    ("Shared work\r\n\r\nco-AUTHORED-by: Someone <Alias@Example.com>\r\n", {"alias@example.com"}, True),
    ("Shared work\n\nCo-authored-by: Someone <alias@example.com>", {"ALIAS@EXAMPLE.COM"}, True),
    ("Shared work\n\nCo-authored-by: Someone <other@example.com>", set(), False),
    ("Mention Co-authored-by: Someone <taf@example.com>", set(), False),
    ("Co-authored-by: taf", set(), False),
    ("Co-authored-by: taf <other@example.com>", set(), False),
])
def test_coauthor_identity(message, emails, expected):
    payload = commit("shared", login="someone")
    payload["commit"]["message"] = message
    assert _matches_identity(payload, "taf", emails) is expected


@pytest.mark.parametrize("incremental", [False, True])
async def test_walk_includes_coauthors_once(incremental):
    coauthored = commit("new", login="someone")
    coauthored["commit"]["message"] = (
        "Shared work\n\nCo-authored-by: Developer <taf@noreply.example>\n"
        "Co-authored-by: Developer <alias@example.com>"
    )
    primary = commit("old", login="taf")
    primary["commit"]["message"] = "Own work\n\nCo-authored-by: Developer <alias@example.com>"
    unrelated = commit("unrelated", login="someone")
    entry = {"pushed_at": "old", "head_sha": "old", "oldest_sha": "unrelated", "complete": True}
    with respx.mock(base_url="https://forge.test") as forge:
        forge.get("/api/v1/repos/taf/dotfiles/commits").mock(
            return_value=httpx.Response(200, json=[coauthored, primary, unrelated])
        )
        service = make_service()
        outcome = await service._walk_repo(
            repo=REPO, username="taf", emails={"alias@example.com"},
            entry=entry if incremental else None, pushed_at="new", deadline=float("inf"),
        )
        await service.client.aclose()
    assert outcome["status"] == ("append" if incremental else "replace")
    assert outcome["days"] == {"2026-01-15": 1 if incremental else 2}


async def test_deep_calendar_supplies_public_email_to_history(monkeypatch):
    from services import analytics

    service = analytics.AnalyticsService(None, Target(key="test", base_url="https://forge.test"))
    captured = []

    async def user(username):
        return {"email": "public@example.com"}

    async def repos(username):
        return [REPO]

    async def native(username):
        return []

    async def refresh(username, *, repos, extra_emails):
        captured.append(extra_emails)
        return {"days": {"2026-01-15": 1}, "complete": True, "repos": 1, "total_commits": 1}

    monkeypatch.setattr(analytics, "redis_enabled", lambda: True)
    monkeypatch.setattr(service, "get_user", user)
    monkeypatch.setattr(service, "get_repos", repos)
    monkeypatch.setattr(service, "get_native_heatmap", native)
    monkeypatch.setattr(service.history, "refresh", refresh)

    _, facts = await service._full_calendar("taf", deep=True, extra_emails={"alias@example.com"})
    assert captured == [{"public@example.com", "alias@example.com"}]
    assert facts["total_commits"] == 1
