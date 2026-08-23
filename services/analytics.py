"""Section orchestrator: fetches, caches, maps onto canonical models."""

from datetime import datetime, timezone
from typing import Any

from core.cache import get_json, redis_enabled, set_json
from core.config import settings
from models.canonical import (
    Badges,
    Heatmap,
    Orgs,
    Profile,
    Repos,
    Stats,
    Summary,
    make_envelope,
)
from services import mappers
from services.client import HostClient, UpstreamError
from services.history import HistoryService
from services.registry import Target


def _cache_key(instance_key: str, section: str, username: str) -> str:
    return f"githost:{instance_key}:{section}:{username.lower()}"


async def _cached(key: str, ttl: int, producer):
    wrapped = await get_json(key)
    if isinstance(wrapped, dict) and "p" in wrapped:
        return wrapped["p"], True
    payload = await producer()
    await set_json(key, {"p": payload}, ttl)
    return payload, False


class AnalyticsService:
    def __init__(self, client: HostClient, target: Target):
        self.client = client
        self.target = target
        self.history = HistoryService(client, target, target.key)

    # ---- raw upstream fetches (cached) ------------------------------------

    async def get_user(self, username: str) -> dict:
        payload, _ = await _cached(
            _cache_key(self.target.key, "user", username),
            settings.profile_ttl,
            lambda: self.client.get_json(f"/api/v1/users/{username}"),
        )
        if not isinstance(payload, dict) or not payload:
            raise UpstreamError(404, "User does not exist")
        return payload

    async def get_repos(self, username: str) -> list[dict]:
        payload, _ = await _cached(
            _cache_key(self.target.key, "repos", username),
            settings.repos_ttl,
            lambda: self.client.paginate(
                f"/api/v1/users/{username}/repos", max_pages=settings.history_max_pages * 2
            ),
        )
        return [r for r in payload if isinstance(r, dict)]

    async def get_native_heatmap(self, username: str) -> list[dict]:
        payload, _ = await _cached(
            _cache_key(self.target.key, "heat", username),
            settings.heatmap_ttl,
            lambda: self.client.get_json(f"/api/v1/users/{username}/heatmap"),
        )
        return payload if isinstance(payload, list) else []

    # ---- canonical sections ----------------------------------------------

    async def get_profile(self, username: str) -> Profile:
        user = await self.get_user(username)
        return mappers.profile_from_user(user, username)

    async def _full_calendar(
        self,
        username: str,
        *,
        deep: bool = False,
        extra_emails: set[str] | None = None,
    ) -> tuple[Heatmap, dict]:
        """Full-history calendar plus facts needed by other sections.

        Decision rule: ``view=all`` serves the synthesized calendar whenever
        manifest data exists (or a deep walk was asked for); everything else
        comes from the native endpoint.
        """
        native_entries = await self.get_native_heatmap(username)

        ran_walk = False
        walk_result: dict | None = None
        use_deep = deep or (redis_enabled() and await self.history.available(username))
        if use_deep and redis_enabled():
            repos = await self.get_repos(username)
            walk_result = await self.history.refresh(
                username,
                repos=repos,
                extra_emails=extra_emails,
            )
            ran_walk = True

        if ran_walk and walk_result and (walk_result["days"] or walk_result["repos"] > 0):
            heatmap = mappers.heatmap_from_day_map(
                walk_result["days"],
                source="synthesized",
                complete=bool(walk_result["complete"]),
            )
        else:
            heatmap = mappers.heatmap_from_native(native_entries)

        facts = {
            "total_commits": (walk_result or {}).get("total_commits") or 0,
            "deep_used": ran_walk,
        }
        return heatmap, facts

    async def get_heatmap(
        self,
        username: str,
        view: str = "all",
        year: int | None = None,
        *,
        deep: bool = False,
        extra_emails: set[str] | None = None,
    ) -> Heatmap:
        from services.heatmap_window import normalize_view, window_heatmap

        normalized_view, normalized_year = normalize_view(view, year)

        if normalized_view != "all":
            entries = await self.get_native_heatmap(username)
            hm = mappers.heatmap_from_native(entries)
            years = sorted({int(d.date[:4]) for d in hm.dailyContributions}, reverse=True)
            if not years:
                years = [datetime.now(timezone.utc).year]
            return window_heatmap(hm, normalized_view, normalized_year, available_years=years)

        heatmap, _facts = await self._full_calendar(username, deep=deep, extra_emails=extra_emails)
        return window_heatmap(heatmap, "all")

    async def get_stats(
        self,
        username: str,
        *,
        deep: bool = False,
        extra_emails: set[str] | None = None,
        exclude: list[str] | None = None,
    ) -> Stats:
        user = await self.get_user(username)
        repos_raw = await self.get_repos(username)
        repos_model = mappers.repos_from_list(repos_raw)
        languages = await mappers.languages_from_repos(
            self.client, repos_model.repos, self.target.key
        )
        if exclude:
            lowered = {e.lower() for e in exclude}
            languages = {k: v for k, v in languages.items() if k.lower() not in lowered}
        calendar, facts = await self._full_calendar(username, deep=deep, extra_emails=extra_emails)
        return mappers.stats_from(facts.get("total_commits") or 0, languages)

    async def get_summary(
        self,
        username: str,
        *,
        deep: bool = False,
        extra_emails: set[str] | None = None,
    ) -> Summary:
        user = await self.get_user(username)
        repos_raw = await self.get_repos(username)
        repos_model = mappers.repos_from_list(repos_raw)
        calendar, facts = await self._full_calendar(username, deep=deep, extra_emails=extra_emails)
        stats = mappers.stats_from(facts.get("total_commits") or 0, {})
        return mappers.summary_from(stats, calendar, repos_model, user.get("followers_count"))

    async def get_badges(
        self,
        username: str,
        *,
        deep: bool = False,
        extra_emails: set[str] | None = None,
    ) -> Badges:
        user = await self.get_user(username)
        repos_raw = await self.get_repos(username)
        repos_model = mappers.repos_from_list(repos_raw)
        calendar, _facts = await self._full_calendar(username, deep=deep, extra_emails=extra_emails)
        return mappers.derive_badges(
            heatmap=calendar,
            total_stars=repos_model.totalStars,
            total_forks=repos_model.totalForks,
            total_repos=len([r for r in repos_model.repos if not r.isPrivate]),
            followers=user.get("followers_count"),
        )

    async def get_card(
        self,
        username: str,
        *,
        deep: bool = False,
        extra_emails: set[str] | None = None,
        exclude: list[str] | None = None,
    ) -> tuple[Stats, dict]:
        """Everything the SVG card renders, in one pass."""
        repos_raw = await self.get_repos(username)
        repos_model = mappers.repos_from_list(repos_raw)
        languages = await mappers.languages_from_repos(
            self.client, repos_model.repos, self.target.key
        )
        if exclude:
            lowered = {e.lower() for e in exclude}
            languages = {k: v for k, v in languages.items() if k.lower() not in lowered}
        calendar, facts = await self._full_calendar(username, deep=deep, extra_emails=extra_emails)
        stats = mappers.stats_from(facts.get("total_commits") or 0, languages)
        extras = {
            "totalStars": repos_model.totalStars,
            "totalRepos": len([r for r in repos_model.repos if not r.isPrivate]),
            "currentStreak": calendar.currentStreak,
            "longestStreak": calendar.longestStreak,
        }
        return stats, extras

    async def get_repos_section(self, username: str) -> Repos:
        repos_raw = await self.get_repos(username)
        return mappers.repos_from_list(repos_raw)

    async def get_orgs_section(self, username: str) -> Orgs:
        try:
            payload = await self.client.paginate(f"/api/v1/users/{username}/orgs", max_pages=10)
        except UpstreamError as exc:
            # Forgejo answers 401 "token is required" for anonymous callers on
            # some instances. Degrade instead of failing the whole section.
            if exc.status_code in (401, 403):
                return Orgs(count=0, orgs=[], restricted=True)
            raise
        orgs = [
            {
                "id": o.get("id"),
                "username": o.get("username") or o.get("name"),
                "fullName": o.get("full_name") or None,
                "avatar": o.get("avatar_url"),
                "description": o.get("description"),
                "website": o.get("website"),
            }
            for o in (payload or [])
            if isinstance(o, dict)
        ]
        return Orgs(count=len(orgs), orgs=orgs)


def envelope(target: Target, username: str, data: Any, cached: bool = False) -> dict:
    return make_envelope(
        username,
        data,
        family=target.family,
        instance=target.key,
        software=target.software or None,
        cached=cached,
    )
