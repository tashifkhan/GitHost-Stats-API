"""Map upstream Gitea/Forgejo JSON onto canonical models."""

from datetime import datetime, timezone
from typing import Iterable

from models.canonical import (
    BadgeItem,
    Badges,
    HeatDay,
    Heatmap,
    Profile,
    RepoSummary,
    Repos,
    Social,
    Stats,
    Summary,
    TopicCount,
    YearContribution,
)


def profile_from_user(user: dict, username: str) -> Profile:
    website = (user.get("website") or "").strip()
    return Profile(
        displayName=(user.get("full_name") or "").strip() or user.get("login") or username,
        username=user.get("login") or username,
        avatar=user.get("avatar_url"),
        country=(user.get("location") or "").strip() or None,
        bio=user.get("description") or None,
        websites=[website] if website else [],
        social=Social(github=None),
        verified=bool(user.get("active")),
    )


def repo_summary_from(repo: dict) -> RepoSummary:
    owner_login = ((repo.get("owner") or {}).get("login")) or ""
    return RepoSummary(
        id=int(repo.get("id") or 0),
        name=repo.get("name") or "",
        fullName=f"{owner_login}/{repo.get('name')}" if owner_login else repo.get("full_name"),
        description=repo.get("description") or None,
        htmlUrl=repo.get("html_url"),
        stars=int(repo.get("stars_count") or 0),
        forks=int(repo.get("forks_count") or 0),
        watchers=int(repo.get("watchers_count") or 0),
        openIssues=int(repo.get("open_issues_count") or 0),
        language=repo.get("language") or None,
        isFork=bool(repo.get("fork")),
        isMirror=bool(repo.get("mirror")),
        isPrivate=bool(repo.get("private")),
        createdAt=_iso(repo.get("created_at")),
        updatedAt=_iso(repo.get("updated_at")),
        pushedAt=_iso(repo.get("updated_at")),
    )


def repos_from_list(items: Iterable[dict]) -> Repos:
    repos = [repo_summary_from(r) for r in items]
    public = [r for r in repos if not r.isPrivate]
    return Repos(
        count=len(repos),
        totalStars=sum(r.stars for r in public),
        totalForks=sum(r.forks for r in public),
        repos=repos,
    )


async def languages_from_repos(client, repos: Iterable[RepoSummary], instance_key: str) -> dict[str, int]:
    """Fetch per-repo language byte counts concurrently, capped politely."""
    import asyncio

    from core.config import settings as cfg
    from core.cache import get_json, set_json

    own = [
        r for r in repos
        if not r.isPrivate and not r.isMirror and r.fullName and "/" in r.fullName
    ]

    async def one(r: RepoSummary) -> dict[str, int]:
        key = f"githost:{instance_key}:lang:{r.fullName}"
        cached = await get_json(key)
        if cached is not None:
            return {k: int(v) for k, v in (cached or {}).items()}
        try:
            payload = await client.get_json(f"/api/v1/repos/{r.fullName}/languages")
            data = {str(k): int(v) for k, v in (payload or {}).items()}
        except Exception:
            data = {}
        await set_json(key, data, cfg.languages_ttl)
        return data

    results = await asyncio.gather(*(one(r) for r in own))
    merged: dict[str, int] = {}
    for result in results:
        for lang, size in result.items():
            merged[lang] = merged.get(lang, 0) + size
    return merged


def stats_from(total_commits: int | None, languages: dict[str, int], top_n: int = 8) -> Stats:
    topics = sorted(languages.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return Stats(
        totalSolved=int(total_commits or 0),
        totalQuestions=None,
        acceptanceRate=None,
        byDifficulty={"easy": 0, "medium": 0, "hard": 0},
        topicAnalysis=[
            TopicCount(topic=name, count=size) for name, size in topics if size > 0
        ],
    )


def heatmap_from_native(entries: list[dict], *, source: str = "native", complete: bool = True) -> Heatmap:
    """Bucket the instance's 15-minute action buckets into UTC days.

    The endpoint caps server-side at ~371 days; ``availableYears`` therefore
    reports only what the window still holds.
    """
    per_day: dict[str, int] = {}
    for entry in entries or []:
        try:
            ts = int(entry.get("timestamp") or 0)
            contributions = int(entry.get("contributions") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        per_day[day] = per_day.get(day, 0) + contributions
    return _rollup(_heatmap_from_days(per_day, source=source, complete=complete))


def heatmap_from_day_map(per_day: dict[str, int], *, source: str, complete: bool) -> Heatmap:
    return _rollup(_heatmap_from_days({k: int(v) for k, v in (per_day or {}).items()}, source=source, complete=complete))


_LEVEL_BREAKS = (0, 1, 3, 6, 10)


def _level(count: int) -> int:
    if count <= 0:
        return 0
    if count <= 1:
        return 1
    if count <= 3:
        return 2
    if count <= 6:
        return 3
    return 4


def _heatmap_from_days(per_day: dict[str, int], *, source: str, complete: bool) -> Heatmap:
    if per_day:
        from datetime import date, timedelta

        first = date.fromisoformat(min(per_day))
        last = date.fromisoformat(max(per_day))
        today = datetime.now(timezone.utc).date()
        if last < today:
            last = today
        days = []
        cursor = first
        while cursor <= last:
            iso = cursor.isoformat()
            count = per_day.get(iso, 0)
            days.append(HeatDay(date=iso, count=count, level=_level(count)))
            cursor += timedelta(days=1)
        daily = days
    else:
        daily = []

    years: dict[int, YearContribution] = {}
    for d in daily:
        year = int(d.date[:4])
        agg = years.setdefault(year, YearContribution(year=year, totalSubmissions=0, activeDays=0))
        agg.totalSubmissions += d.count
        if d.count > 0:
            agg.activeDays += 1
    yearly = sorted(years.values(), key=lambda y: y.year, reverse=True)

    return Heatmap(
        dailyContributions=daily,
        yearlyContributions=yearly,
        availableYears=[y.year for y in yearly],
        view="all",
        source=source,
        complete=complete,
    )


def _rollup(hm):
    """Fill all view=all rollups on an unwindowed calendar."""
    from services.heatmap_window import window_heatmap

    return window_heatmap(hm, "all")


def derive_badges(
    *,
    heatmap: Heatmap,
    total_stars: int,
    total_forks: int,
    total_repos: int,
    followers: int | None,
) -> Badges:
    """Git hosts ship no badge system, so badges are derived achievements."""
    earned: list[BadgeItem] = []

    def add(name: str, level: str | None = None):
        earned.append(BadgeItem(id=name.lower().replace(" ", "-"), name=name, level=level))

    longest = heatmap.longestStreak
    for threshold, label in [(365, "Year Long"), (100, "Century Streak"), (30, "Monthly Streak"), (7, "Week Streak")]:
        if longest >= threshold:
            add(label, f"{longest} day best streak")
            break

    for threshold, label in [
        (1000, "Kilo-Star"),
        (500, "Half-K Star"),
        (100, "Centurion"),
        (50, "Half-Century"),
        (10, "Double Digits"),
        (1, "First Star"),
    ]:
        if total_stars >= threshold:
            add(label, f"{total_stars} stars earned")
            break

    for threshold, label in [(25, "Repository Hoarder"), (10, "Serial Builder"), (1, "Hello World")]:
        if total_repos >= threshold:
            add(label, f"{total_repos} repositories")
            break

    if followers is not None:
        for threshold, label in [(50, "Micro Famous"), (10, "Followed")]:
            if followers >= threshold:
                add(label, f"{followers} followers")
                break

    active_days = heatmap.totalActiveDays
    for threshold, label in [(200, "Regular"), (50, "Showing Up"), (5, "Warming Up")]:
        if active_days >= threshold:
            add(label, f"{active_days} active days")
            break

    return Badges(count=len(earned), active=earned[0] if earned else None, list=earned)


def summary_from(stats: Stats, heatmap: Heatmap, repos: Repos, followers: int | None) -> Summary:
    return Summary(
        totalSolved=stats.totalSolved,
        totalActiveDays=heatmap.totalActiveDays,
        totalRepos=repos.count,
        totalStars=repos.totalStars,
        totalForks=repos.totalForks,
        followers=followers,
    )


def _iso(value) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return text
