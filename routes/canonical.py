"""Canonical section endpoints in both route shapes.

``/{username}/profile`` requires an explicit target via ``?host=`` or
``?base_url=``. The prefixed form ``/f/{host}/{username}/profile`` selects a
registered host in the path and is embed-safe for README badges.
"""

from collections.abc import AsyncIterator
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query

from routes.dependencies import Context, prefixed_context, request_context
from services.analytics import envelope

router = APIRouter()


async def _ctx(
    host: Optional[str] = Query(None),
    base_url: Optional[str] = Query(None),
    emails: Optional[str] = Query(None, description="Extra commit emails for identity matching"),
) -> AsyncIterator[Context]:
    async for ctx in request_context(host=host, base_url=base_url, emails=emails):
        yield ctx


async def _ctx_prefixed(
    host: str = Path(..., description="Registered instance key"),
    emails: Optional[str] = Query(None),
) -> AsyncIterator[Context]:
    async for ctx in prefixed_context(host=host, emails=emails):
        yield ctx


def _emails(ctx: Context) -> set[str]:
    return set(ctx.emails or [])


# ---- query-selected shape --------------------------------------------------


@router.get("/{username}/profile", summary="Canonical profile")
async def profile(username: str, ctx: Context = Depends(_ctx)):
    data = await ctx.analytics.get_profile(username)
    return envelope(ctx.target, username, data)


@router.get("/{username}", summary="Canonical summary")
async def summary(
    username: str,
    deep: bool = Query(False, description="Run/continue the deep history walk inline"),
    ctx: Context = Depends(_ctx),
):
    data = await ctx.analytics.get_summary(username, deep=deep, extra_emails=_emails(ctx))
    return envelope(ctx.target, username, data)


@router.get("/{username}/stats", summary="Canonical stats")
async def stats(
    username: str,
    deep: bool = Query(False),
    exclude: Optional[str] = Query(None, description="Comma-separated languages to omit from bars"),
    ctx: Context = Depends(_ctx),
):
    excluded = [e.strip() for e in (exclude or "").split(",") if e.strip()]
    data = await ctx.analytics.get_stats(
        username,
        deep=deep,
        extra_emails=_emails(ctx),
        exclude=excluded,
    )
    return envelope(ctx.target, username, data)


def _parse_excludes(exclude: Optional[str]) -> list[str]:
    return [e.strip() for e in (exclude or "").split(",") if e.strip()]


async def _render_svg(ctx: Context, username: str, deep: bool, theme: str, exclude: Optional[str]):
    from services.stats_svg import stats_svg_response

    stats, extras = await ctx.analytics.get_card(
        username,
        deep=deep,
        extra_emails=_emails(ctx),
        exclude=_parse_excludes(exclude),
    )
    return stats_svg_response(ctx.target.family, username, stats, theme=theme, extras=extras)


@router.get("/{username}/stats/svg", summary="Embeddable SVG card")
async def stats_svg_route(
    username: str,
    deep: bool = Query(False),
    theme: str = Query("dark", pattern="^(dark|light)$"),
    exclude: Optional[str] = Query(None),
    ctx: Context = Depends(_ctx),
):
    return await _render_svg(ctx, username, deep, theme, exclude)


@router.get("/{username}/heatmap", summary="Canonical heatmap")
async def heatmap(
    username: str,
    view: str = Query("all"),
    year: Optional[int] = Query(None, ge=1970, le=2100),
    deep: bool = Query(False),
    ctx: Context = Depends(_ctx),
):
    data = await ctx.analytics.get_heatmap(
        username,
        view=view,
        year=year,
        deep=deep,
        extra_emails=_emails(ctx),
    )
    return envelope(ctx.target, username, data)


@router.get("/{username}/badges", summary="Derived badges")
async def badges(
    username: str,
    deep: bool = Query(False),
    ctx: Context = Depends(_ctx),
):
    data = await ctx.analytics.get_badges(username, deep=deep, extra_emails=_emails(ctx))
    return envelope(ctx.target, username, data)


@router.get("/{username}/repos", summary="Repositories with totals")
async def repos(username: str, ctx: Context = Depends(_ctx)):
    data = await ctx.analytics.get_repos_section(username)
    return envelope(ctx.target, username, data)


@router.get("/{username}/orgs", summary="Organization memberships")
async def orgs(username: str, ctx: Context = Depends(_ctx)):
    data = await ctx.analytics.get_orgs_section(username)
    return envelope(ctx.target, username, data)


# ---- prefixed shape (/f/{host}/...) ----------------------------------------


@router.get("/f/{host}/{username}/profile", include_in_schema=False)
async def profile_p(username: str, ctx: Context = Depends(_ctx_prefixed)):
    data = await ctx.analytics.get_profile(username)
    return envelope(ctx.target, username, data)


@router.get("/f/{host}/{username}", include_in_schema=False)
async def summary_p(
    username: str,
    deep: bool = Query(False),
    ctx: Context = Depends(_ctx_prefixed),
):
    data = await ctx.analytics.get_summary(username, deep=deep, extra_emails=_emails(ctx))
    return envelope(ctx.target, username, data)


@router.get("/f/{host}/{username}/stats", include_in_schema=False)
async def stats_p(
    username: str,
    deep: bool = Query(False),
    ctx: Context = Depends(_ctx_prefixed),
):
    data = await ctx.analytics.get_stats(username, deep=deep, extra_emails=_emails(ctx))
    return envelope(ctx.target, username, data)


@router.get("/f/{host}/{username}/stats/svg", include_in_schema=False)
async def stats_svg_p(
    username: str,
    deep: bool = Query(False),
    theme: str = Query("dark", pattern="^(dark|light)$"),
    exclude: Optional[str] = Query(None),
    ctx: Context = Depends(_ctx_prefixed),
):
    return await _render_svg(ctx, username, deep, theme, exclude)


@router.get("/f/{host}/{username}/heatmap", include_in_schema=False)
async def heatmap_p(
    username: str,
    view: str = Query("all"),
    year: Optional[int] = Query(None, ge=1970, le=2100),
    deep: bool = Query(False),
    ctx: Context = Depends(_ctx_prefixed),
):
    data = await ctx.analytics.get_heatmap(
        username, view=view, year=year, deep=deep, extra_emails=_emails(ctx)
    )
    return envelope(ctx.target, username, data)


@router.get("/f/{host}/{username}/badges", include_in_schema=False)
async def badges_p(
    username: str,
    deep: bool = Query(False),
    ctx: Context = Depends(_ctx_prefixed),
):
    data = await ctx.analytics.get_badges(username, deep=deep, extra_emails=_emails(ctx))
    return envelope(ctx.target, username, data)


@router.get("/f/{host}/{username}/repos", include_in_schema=False)
async def repos_p(username: str, ctx: Context = Depends(_ctx_prefixed)):
    data = await ctx.analytics.get_repos_section(username)
    return envelope(ctx.target, username, data)


@router.get("/f/{host}/{username}/orgs", include_in_schema=False)
async def orgs_p(username: str, ctx: Context = Depends(_ctx_prefixed)):
    data = await ctx.analytics.get_orgs_section(username)
    return envelope(ctx.target, username, data)
