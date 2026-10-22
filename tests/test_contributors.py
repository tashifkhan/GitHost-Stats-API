import asyncio
import copy
import json

import pytest

from core.config import settings
from services import contributors
from services.analytics import AnalyticsService
from services.client import UpstreamError
from services.registry import Target


REPO = {"id": 1, "name": "repo", "owner": {"login": "alice"}, "pushed_at": "v1"}
USER = {"login": "alice", "email": "alice@personal.test", "avatar_url": "alice.png"}
TARGET = Target(key="test", base_url="https://forge.test")


def commit(sha, login=None, email="dev@example.test", name="Developer", message=""):
    return {
        "sha": sha,
        "author": {"login": login, "avatar_url": f"{login}.png"} if login else None,
        "commit": {"author": {"name": name, "email": email}, "message": message},
    }


class Client:
    max_page_size = 2

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get_with_meta(self, path, params):
        self.calls.append((path, dict(params)))
        reply = self.pages.get(params["page"], ([], {}))
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def stored(monkeypatch):
    values = {}

    async def get(key):
        return copy.deepcopy(values.get(key))

    async def set_value(key, value, ttl):
        values[key] = json.loads(json.dumps(value))

    async def delete(key):
        values.pop(key, None)

    monkeypatch.setattr(contributors, "get_json", get)
    monkeypatch.setattr(contributors, "set_json", set_value)
    monkeypatch.setattr(contributors, "delete_key", delete)
    return values


async def scan(client, repo=None, target=None, user=None, emails=None, deadline=None):
    return await contributors.repository_contributors(
        client, target or TARGET, repo or REPO,
        deadline if deadline is not None else asyncio.get_running_loop().time() + 30,
        user=user or USER, extra_emails=emails or set(),
    )


async def test_authors_coauthors_and_late_aliases_count_each_sha_once(stored):
    shared = commit("new", "alice", "alice@work.test", message=(
        "Shared work\r\n\r\nco-AUTHORED-by: Alice <Alice@Personal.Test>\r\n"
        "Co-authored-by: Bob <private@bob.test>\r\n"
        "Co-authored-by: Guest <guest@example.test>\r\n"
        "Co-authored-by: Guest Again <GUEST@example.test>\r\n"
        "Co-authored-by: Alice <alice@work.test>"
    ))
    client = Client({
        1: ([shared], {"link": '<https://forge.test/api/v1/repos/alice/repo/commits?page=2>; rel="next"'}),
        2: ([commit("old", "Bob", "private@bob.test", message=(
            "Co-authored-by: Alice <alice@personal.test>"
        )), shared], {}),
    })
    result, complete = await scan(client)
    assert complete is True
    assert [(item.login, item.name, item.contributions) for item in result] == [
        ("alice", "alice", 2), ("Bob", "Bob", 2), (None, "Guest", 1),
    ]
    assert result[1].avatar_url == "Bob.png"
    assert result[1].html_url == "https://forge.test/Bob"
    assert result[2].html_url is None
    assert client.calls[1][1]["sha"] == "new"
    assert client.calls[2][1]["sha"] == "new"
    assert all("email" not in item.model_dump() for item in result)
    calls = len(client.calls)
    cached, cached_complete = await scan(client)
    assert len(client.calls) == calls
    assert cached == result and cached_complete is True


async def test_capped_scan_resumes_at_next_page(stored, monkeypatch):
    monkeypatch.setattr(settings, "history_max_pages", 1)
    client = Client({1: ([commit("a", "alice"), commit("b", "alice")], {})})
    first, complete = await scan(client)
    assert complete is False
    assert first[0].contributions == 2
    # An overlapping SHA on a later page must not duplicate any credit.
    client.pages[2] = ([commit("b", "alice"), commit("c", "alice")], {})
    second, complete = await scan(client)
    assert complete is False
    assert second[0].contributions == 3
    _, complete = await scan(client)
    assert complete is True
    assert [params["page"] for _, params in client.calls] == [1, 2, 3]


async def test_gitea_pagination_headers_keep_short_pages_from_ending_scan(stored):
    client = Client({
        1: ([commit("a", "alice")], {"X-HasMore": "true", "X-PerPage": "1"}),
        2: ([commit("b", "alice")], {"X-HasMore": "false", "X-PerPage": "1"}),
    })
    result, complete = await scan(client)
    assert complete is True
    assert result[0].contributions == 2
    assert [params["page"] for _, params in client.calls] == [1, 2]
    assert client.calls[1][1]["limit"] == 1


async def test_shared_cache_isolates_hosts_repo_versions_and_request_aliases(stored):
    client = Client({1: ([commit("a", None, "alias@private.test", name="Alias")], {})})
    attributed, _ = await scan(client, emails={"alias@private.test"})
    assert attributed[0].login == "alice"
    plain, _ = await scan(client)
    assert plain[0].login is None
    assert len(client.calls) == 1
    await scan(client, repo={**REPO, "pushed_at": "v2"})
    await scan(client, target=Target(key="other", base_url="https://other.test"))
    assert len(client.calls) == 3
    assert len(stored) == 3


@pytest.mark.parametrize("status,complete", [(403, False), (404, False), (409, True)])
async def test_upstream_errors_and_empty_repos(stored, status, complete):
    result, finished = await scan(Client({1: UpstreamError(status, "unavailable")}))
    assert result == []
    assert finished is complete


async def test_unreachable_pinned_head_discards_old_history(stored, monkeypatch):
    monkeypatch.setattr(settings, "history_max_pages", 1)
    client = Client({1: ([commit("a", "alice"), commit("b", "alice")], {})})
    await scan(client)
    client.pages[2] = UpstreamError(404, "old head disappeared")
    result, complete = await scan(client)
    assert result == [] and complete is False
    assert stored == {}
    client.pages[1] = ([commit("replacement", "bob")], {})
    result, complete = await scan(client)
    assert complete is True
    assert result[0].login == "bob" and result[0].contributions == 1
    assert "sha" not in client.calls[-1][1]


async def test_deadline_cancels_inflight_request(stored):
    class SlowClient(Client):
        cancelled = False

        async def get_with_meta(self, path, params):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    client = SlowClient({})
    result, complete = await scan(client, deadline=asyncio.get_running_loop().time() + 0.01)
    assert result == [] and complete is False
    assert client.cancelled is True


@pytest.mark.parametrize("payload", [{"message": "bad shape"}, [{"sha": "missing-author"}]])
async def test_malformed_pages_are_not_complete(stored, payload):
    result, complete = await scan(Client({1: (payload, {})}))
    assert result == [] and complete is False
    assert not stored


async def test_top_ten_contributors_keep_coauthors_without_accounts(stored):
    client = Client({1: ([commit("shared", "alice", message="\n".join(
        f"Co-authored-by: Guest {i:02d} <guest{i}@example.test>" for i in range(12)
    ))], {})})
    result, complete = await scan(client)
    assert complete is True
    assert len(result) == 10
    assert result[0].login == "alice"
    assert result[-1].name == "Guest 08"


async def test_repo_section_enriches_forks_and_mirrors_too(stored, monkeypatch):
    raw = [REPO, {**REPO, "id": 2, "name": "fork", "fork": True},
           {**REPO, "id": 3, "name": "mirror", "mirror": True}]
    client = Client({1: ([commit("shared", "alice", message=(
        "Co-authored-by: Alias <alias@example.test>"
    ))], {})})
    service = AnalyticsService(client, TARGET)

    async def repos(username):
        return raw

    async def user(username):
        return USER

    monkeypatch.setattr(service, "get_repos", repos)
    monkeypatch.setattr(service, "get_user", user)
    result = await service.get_repos_section("alice", extra_emails={"alias@example.test"})
    assert result.count == 3
    assert all(repo.contributors_complete for repo in result.repos)
    assert all(len(repo.contributors) == 1 for repo in result.repos)
    assert all(repo.contributors[0].contributions == 1 for repo in result.repos)
