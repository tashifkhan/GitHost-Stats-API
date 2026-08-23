"""Deep history backfill: rebuild the contribution calendar from git itself.

The native heatmap endpoint caps server-side at ~371 days. This walker
reconstructs full history by walking every owned repository's commits,
filtering to the user's identity client-side (the API has no author param),
and bucketing git author dates into UTC days.

Delta discipline: every request diffs first and fetches second. A Redis hash
manifest keyed by ``repo.id`` stores ``{pushed_at, head_sha, oldest_sha,
complete}`` per repo. Unchanged repos reuse their cached day histogram with
zero upstream calls. Changed repos walk newest-first until they reach the
previously recorded head SHA, so only pages newer than the last visit land.
There is no background job; the request path is the refresher, and each
request carries a wall-clock deadline budget.
"""

import asyncio
import json
from datetime import datetime, timezone

from core.cache import delete_key, get_json, get_redis, redis_enabled, set_json
from core.config import settings


def _manifest_key(instance: str, username: str) -> str:
    return f"host:{instance}:histman:{username.lower()}"


def _hist_key(instance: str, username: str, repo_id: int | str) -> str:
    return f"host:{instance}:hist:{username.lower()}:{repo_id}"


def _matches_identity(commit: dict, username: str, emails: set[str]) -> bool:
    uname = (username or "").lower()
    forge_user = commit.get("author") or {}
    if uname and str(forge_user.get("login") or "").lower() == uname:
        return True
    git_author = (commit.get("commit") or {}).get("author") or {}
    email = str(git_author.get("email") or "").strip().lower()
    if email and email in emails:
        return True
    local = email.split("@", 1)[0] if email else ""
    return bool(uname) and local == uname


def _day_of(commit: dict) -> str | None:
    try:
        date_text = ((commit.get("commit") or {}).get("author") or {}).get("date")
        dt = datetime.fromisoformat(str(date_text).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).date().isoformat()
    except (ValueError, TypeError, AttributeError):
        return None


class HistoryService:
    def __init__(self, client, target, instance_key: str):
        self.client = client
        self.target = target
        self.instance_key = instance_key

    async def available(self, username: str) -> bool:
        """True when a warmed manifest exists for this user."""
        client = get_redis()
        if client is None:
            return False
        try:
            manifest = await client.hgetall(_manifest_key(self.instance_key, username))
        except Exception:
            return False
        return bool(manifest)

    async def refresh(
        self,
        username: str,
        repos: list[dict],
        extra_emails: set[str] | None = None,
        budget_seconds: float | None = None,
    ) -> dict:
        """Diff-and-fetch pass across one user's repositories.

        Returns ``{"days": {date: count}, "complete": bool, "repos": n,
        "total_commits": int}``.
        """
        emails = {(e or "").strip().lower() for e in (extra_emails or []) if e}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (
            budget_seconds if budget_seconds is not None else settings.request_deadline_seconds
        )

        own = [
            r for r in (repos or [])
            if not r.get("fork") and not r.get("mirror")
            and ((r.get("owner") or {}).get("login") or "")
        ]

        redis_client = get_redis()
        if redis_client is None:
            return {"days": {}, "complete": False, "repos": 0, "total_commits": 0}

        manifest_key = _manifest_key(self.instance_key, username)
        try:
            raw_manifest = await redis_client.hgetall(manifest_key)
        except Exception:
            raw_manifest = {}
        manifest: dict[str, dict] = {}
        for rid, blob in (raw_manifest or {}).items():
            try:
                manifest[str(rid)] = json.loads(blob)
            except (TypeError, ValueError):
                continue

        current_ids: set[str] = set()
        merged_days: dict[str, int] = {}
        all_complete = True

        for repo in own:
            rid = str(repo["id"])
            current_ids.add(rid)
            pushed_at = str(repo.get("updated_at") or repo.get("pushed_at") or "")
            entry = manifest.get(rid)

            hist_key = _hist_key(self.instance_key, username, rid)
            hist = await get_json(hist_key) or {}

            # Finished last time and nothing changed since: free reuse.
            if (
                entry
                and entry.get("complete")
                and entry.get("pushed_at") == pushed_at
                and hist.get("head_sha") == entry.get("head_sha")
            ):
                for day, count in (hist.get("days") or {}).items():
                    merged_days[day] = merged_days.get(day, 0) + int(count)
                continue

            remaining = deadline - loop.time()
            if remaining <= 0:
                all_complete = False
                for day, count in (hist.get("days") or {}).items():
                    merged_days[day] = merged_days.get(day, 0) + int(count)
                continue

            outcome = await self._walk_repo(
                repo=repo,
                username=username,
                emails=emails,
                entry=entry,
                pushed_at=pushed_at,
                deadline=deadline,
            )
            status = outcome["status"]

            if status == "append":
                final_days = _merge_days(hist.get("days"), outcome["days"])
                complete = True
            elif status == "replace":
                final_days = outcome["days"]
                complete = True
            elif status == "invalidate":
                # History shrank below the bookmark mid-backfill. Rewalk fresh
                # within what is left of this request's budget.
                if deadline - loop.time() > 0.5:
                    outcome = await self._walk_repo(
                        repo=repo,
                        username=username,
                        emails=emails,
                        entry=None,
                        deadline=deadline,
                    )
                    if outcome["status"] == "incomplete":
                        all_complete = False
                        complete = False
                        final_days = outcome["days"]
                    else:
                        final_days = outcome["days"]
                        complete = True
                else:
                    all_complete = False
                    complete = False
                    final_days = dict(hist.get("days") or {})
            else:  # incomplete: capped or timed out mid-history
                all_complete = False
                complete = False
                # Keep the progress as a seed so the next request resumes
                # deeper instead of restarting.
                final_days = _merge_days(hist.get("days"), outcome["days"])

            payload = {
                "days": final_days,
                "head_sha": outcome["head_sha"] or hist.get("head_sha"),
                "pushed_at": pushed_at,
                "complete": complete,
            }
            if final_days or complete:
                await set_json(hist_key, payload, settings.hist_ttl)
                try:
                    await redis_client.hset(
                        manifest_key,
                        rid,
                        json.dumps(
                            {
                                "pushed_at": pushed_at,
                                "head_sha": payload["head_sha"],
                                "oldest_sha": outcome["oldest_sha"]
                                or (entry or {}).get("oldest_sha"),
                                "page": outcome.get("page") or (entry or {}).get("page"),
                                "complete": complete,
                            },
                            separators=(",", ":"),
                        ),
                    )
                except Exception:
                    pass
            for day, count in final_days.items():
                merged_days[day] = merged_days.get(day, 0) + int(count)

        # Repositories deleted upstream leave the manifest.
        dropped = [rid for rid in list((raw_manifest or {}).keys()) if rid not in current_ids]
        if dropped:
            try:
                await redis_client.hdel(manifest_key, *dropped)
                for rid in dropped:
                    await delete_key(_hist_key(self.instance_key, username, rid))
            except Exception:
                pass

        total = sum(merged_days.values())
        return {"days": merged_days, "complete": all_complete, "repos": len(own), "total_commits": total}

    async def _walk_repo(
        self,
        *,
        repo: dict,
        username: str,
        emails: set[str],
        entry: dict | None,
        pushed_at: str,
        deadline: float,
    ) -> dict:
        """Walk one repository newest-first under the deadline budget.

        Returns ``{"status", "days", "head_sha", "oldest_sha"}`` where ``days``
        holds ONLY newly matched commits:

        * ``append``     - reached the stored ``oldest_sha`` boundary; merge
                           these days onto the stored histogram
        * ``replace``    - walked the entire repository without meeting the
                           stored boundaries (force-push rewrite or first-ever
                           complete walk): wholesale replacement
        * ``incomplete`` - hit the page cap or the deadline mid-history;
                           ``days`` carries the progress made so far (possibly
                           empty) plus the new ``oldest_sha`` bookmark so the
                           next request resumes deeper instead of restarting
        """
        owner = (repo.get("owner") or {}).get("login") or ""
        name = repo.get("name") or ""
        path = f"/api/v1/repos/{owner}/{name}/commits"
        limit = self.client.max_page_size

        days: dict[str, int] = {}
        pages = 0
        head_sha: str | None = None
        oldest_sha: str | None = None
        deepest_page = 0

        # Two ways to resume:
        #   * pushed_at unchanged since the seed -> jump straight to the
        #     bookmarked page and count everything older than it (state
        #     starts at "below"); skipping stored pages costs real request
        #     budgets otherwise and can stall progress entirely.
        #   * pushed_at changed -> full scan from page 1 with head/oldest
        #     phases, because commits may have appeared above the stored head.
        entry_pushed = (entry or {}).get("pushed_at")
        can_jump = (
            entry is not None
            and (entry or {}).get("complete") is False
            and bool((entry or {}).get("page"))
            and pushed_at == entry_pushed
        )
        if can_jump:
            page = int(entry["page"])
            state = "below"
            saw_head = True      # stored prefix trusted via unchanged pushed_at
            saw_oldest = True    # boundary semantics: everything stored
            target_head = None
            target_oldest = None
        else:
            page = 1
            state = "above" if entry else "count"
            target_head = (entry or {}).get("head_sha")
            target_oldest = (entry or {}).get("oldest_sha")
            saw_head = False
            saw_oldest = False
        exhausted = False

        while pages < settings.history_max_pages:
            loop = asyncio.get_running_loop()
            timed_out = loop.time() >= deadline
            if timed_out:
                break
            try:
                commits = await self.client.get_json(path, {"limit": limit, "page": page})
            except Exception:
                break
            if not isinstance(commits, list):
                break
            pages += 1
            deepest_page = page

            if not commits:
                exhausted = True
                break

            if head_sha is None and state != "below":
                head_sha = str(commits[0].get("sha") or "") or None

            for commit in commits:
                sha = str(commit.get("sha") or "")
                if not sha:
                    continue
                oldest_sha = sha

                if state == "above":
                    if sha == target_head:
                        saw_head = True
                        state = "inside"
                    elif _matches_identity(commit, username, emails):
                        day = _day_of(commit)
                        if day:
                            days[day] = days.get(day, 0) + 1
                    continue

                if state == "inside":
                    if sha == target_oldest:
                        saw_oldest = True
                        state = "below"
                    continue

                if _matches_identity(commit, username, emails):
                    day = _day_of(commit)
                    if day:
                        days[day] = days.get(day, 0) + 1

            if len(commits) < limit:
                exhausted = True
                break
            page += 1

        # Completion requires exhaustion once inside the below phase: seeing
        # the stored oldest is not enough, because newer-than-bookmark tail
        # pages may follow it and a deadline can cut the walk right after
        # crossing. Everything else stays an unfinished seed.
        if exhausted and saw_oldest:
            return {"status": "append", "days": days, "head_sha": head_sha, "oldest_sha": oldest_sha, "page": deepest_page}
        if exhausted:
            if entry is None or not saw_head:
                # Full history walked fresh, or the stored head vanished from
                # the listing (rewrite above the bookmark): wholesale replace.
                return {"status": "replace", "days": days, "head_sha": head_sha, "oldest_sha": oldest_sha, "page": deepest_page}
            # Saw the head but the repo ended before the stored oldest: the
            # stored tail no longer exists. Stored data is partially stale.
            return {"status": "invalidate", "days": days, "head_sha": head_sha, "oldest_sha": oldest_sha, "page": None}
        # Capped or timed out mid-history: keep the progress as a seed. Days
        # counted in the below phase are valid new work; the caller merges
        # them and stores the advanced bookmark.
        return {"status": "incomplete", "days": days, "head_sha": head_sha, "oldest_sha": oldest_sha, "page": deepest_page + 1}


def _merge_days(base: dict | None, fresh: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {k: int(v) for k, v in (base or {}).items()}
    for day, count in fresh.items():
        merged[day] = merged.get(day, 0) + int(count)
    return merged
