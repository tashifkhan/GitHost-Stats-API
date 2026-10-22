"""Repository contributors, including Co-authored-by trailers.

Keep commit membership by email so an email linked to an account on a later
page can merge earlier credits without counting the same commit twice.
"""

import asyncio
import re
from urllib.parse import parse_qs, quote, urlsplit

from core.cache import delete_key, get_json, set_json
from core.config import settings
from models.canonical.summary import RepoContributor
from services.client import UpstreamError, _parse_next_link


_COAUTHOR_RE = re.compile(
    r"^Co-authored-by:[ \t]*([^\r\n<>]+?)[ \t]*<([^<>\s]+@[^<>\s]+)>[ \t]*\r?$",
    re.IGNORECASE | re.MULTILINE,
)


def _new_state(page_size: int) -> dict:
    return {
        "head": None, "page": 1, "page_size": page_size, "complete": False,
        "credits": {}, "aliases": {}, "users": {},
    }


def _remember_user(state: dict, user: dict, email: str = "") -> str | None:
    login = str(user.get("login") or user.get("username") or "").strip()
    if not login:
        return None
    key = login.lower()
    existing = state["users"].get(key, {})
    state["users"][key] = {
        "login": login,
        "name": user.get("full_name") or existing.get("name") or login,
        "avatar_url": user.get("avatar_url") or existing.get("avatar_url"),
        "html_url": user.get("html_url") or existing.get("html_url"),
    }
    for address in (email, user.get("email")):
        if address:
            state["aliases"][str(address).strip().lower()] = key
    return key


def _add_commit(state: dict, payload: dict) -> None:
    sha = payload["sha"]
    commit = payload["commit"]
    author = commit.get("author") or {}
    email = str(author.get("email") or "").strip().lower()
    linked = _remember_user(state, payload.get("author") or {}, email)
    identities = [(str(author.get("name") or ""), email, linked)]
    identities.extend(
        (name.strip(), address.lower(), None)
        for name, address in _COAUTHOR_RE.findall(str(commit.get("message") or ""))
    )
    for name, address, login in identities:
        identity = f"email:{address}" if address else f"user:{login}" if login else f"name:{name}"
        if not address and not login and not name:
            continue
        credit = state["credits"].setdefault(identity, {
            "name": name or None, "email": address, "login": login, "commits": {},
        })
        credit["commits"][sha] = True


def _contributors(state: dict, base_url: str, user: dict, extra_emails: set[str]) -> list[RepoContributor]:
    # Request-provided aliases must not change the shared repo checkpoint.
    aliases = dict(state["aliases"])
    users = dict(state["users"])
    login = str(user.get("login") or user.get("username") or "").strip()
    if login:
        key = login.lower()
        users.setdefault(key, {
            "login": login, "name": user.get("full_name") or login,
            "avatar_url": user.get("avatar_url"), "html_url": user.get("html_url"),
        })
        for address in [user.get("email"), *extra_emails]:
            if address:
                aliases[str(address).strip().lower()] = key
    merged: dict[str, tuple[dict, set[str]]] = {}
    for identity, credit in state["credits"].items():
        account = aliases.get(credit["email"]) or credit["login"]
        key = f"user:{account}" if account else identity
        metadata = dict(users[account]) if account else {"name": credit["name"]}
        if account and not metadata.get("html_url"):
            metadata["html_url"] = f"{base_url}/{quote(metadata['login'], safe='')}"
        _, commits = merged.setdefault(key, (metadata, set()))
        commits.update(credit["commits"])
    ranked = sorted(merged.items(), key=lambda item: (
        -len(item[1][1]),
        (item[1][0].get("login") or item[1][0].get("name") or "").lower(),
        item[0],
    ))[:10]
    return [RepoContributor(**metadata, contributions=len(commits)) for _, (metadata, commits) in ranked]


async def repository_contributors(
    client, target, repo: dict, deadline: float, *, user: dict, extra_emails: set[str],
) -> tuple[list[RepoContributor], bool]:
    owner = (repo.get("owner") or {}).get("login")
    name = repo.get("name")
    if not owner or not name:
        return [], False
    version = repo.get("pushed_at") or repo.get("updated_at") or "head"
    key = f"githost:{target.key}:contributors:v1:{owner}/{name}:{version}"
    state = await get_json(key) or _new_state(client.max_page_size)
    if state["complete"]:
        return _contributors(state, target.base_url, user, extra_emails), True
    path = f"/api/v1/repos/{quote(owner, safe='')}/{quote(name, safe='')}/commits"
    for _ in range(settings.history_max_pages):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        params = {
            "page": state["page"], "limit": state["page_size"],
            "stat": "false", "verification": "false", "files": "false",
        }
        if state["head"]:
            params["sha"] = state["head"]
        try:
            payload, headers = await asyncio.wait_for(client.get_with_meta(path, params), remaining)
        except UpstreamError as exc:
            if exc.status_code == 409:
                state = _new_state(client.max_page_size)
                state["complete"] = True
                await set_json(key, state, settings.hist_ttl)
            elif state["head"] and exc.status_code in (404, 422):
                # The pinned history disappeared. Start from the new head on
                # the next request instead of mixing two histories together.
                await delete_key(key)
                state = _new_state(client.max_page_size)
            break
        except (TimeoutError, asyncio.TimeoutError):
            break
        if not isinstance(payload, list):
            break
        if payload and not all(
            isinstance(item, dict) and item.get("sha") and isinstance(item.get("commit"), dict)
            for item in payload
        ):
            break
        if payload and not state["head"]:
            state["head"] = payload[0]["sha"]
        for commit in payload:
            _add_commit(state, commit)
        headers = {key.lower(): str(value) for key, value in headers.items()}
        next_link = _parse_next_link(headers.get("link"))
        has_more = headers.get("x-hasmore", "").lower()
        # Gitea also reports pagination through X-HasMore/X-PerPage. A forge
        # may cap pages below the requested limit without sending a Link.
        try:
            actual_size = int(headers.get("x-perpage", state["page_size"]))
            if 0 < actual_size <= state["page_size"]:
                state["page_size"] = actual_size
        except ValueError:
            pass
        if not payload or (not next_link and has_more != "true" and (
            has_more == "false" or len(payload) < state["page_size"]
        )):
            state["complete"] = True
        next_page = state["page"] + 1
        if next_link:
            try:
                next_page = int(parse_qs(urlsplit(next_link).query)["page"][0])
            except (KeyError, ValueError, IndexError):
                break
            if next_page <= state["page"]:
                break
        state["page"] = next_page
        await set_json(key, state, settings.hist_ttl)
        if state["complete"]:
            break
    return _contributors(state, target.base_url, user, extra_emails), state["complete"]
