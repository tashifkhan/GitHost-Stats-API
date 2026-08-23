"""Render canonical Stats as an embeddable SVG card (README-friendly).

Ported from the GitHub sibling service with forge-specific accents and
labels. Responses set ``Cache-Control: public, max-age=86400`` so README
embeds never hammer the instance.
"""

from __future__ import annotations

import html
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from fastapi.responses import Response

SVG_CACHE_SECONDS = 86400
SVG_CACHE_CONTROL = f"public, max-age={SVG_CACHE_SECONDS}, s-maxage={SVG_CACHE_SECONDS}"

PLATFORM_ACCENTS: Dict[str, str] = {
    "forgejo": "#fb923c",
    "gitea": "#609926",
}

PLATFORM_TITLES: Dict[str, str] = {
    "forgejo": "Forgejo",
    "gitea": "Gitea",
}

TOTAL_LABELS: Dict[str, str] = {
    "forgejo": "Total Commits",
    "gitea": "Total Commits",
}

DIFFICULTY_META: Dict[str, Tuple[str, str]] = {
    "easy": ("Easy", "#00b8a3"),
    "medium": ("Medium", "#ffc01e"),
    "hard": ("Hard", "#ff375f"),
}

THEMES = {
    "dark": {
        "bg": "#0a0a0c",
        "panel": "#121214",
        "border": "#1f1f22",
        "ink": "#fafafa",
        "muted": "#9b9ba4",
        "faint": "#6b6b73",
        "bar_track": "#1f1f22",
    },
    "light": {
        "bg": "#ffffff",
        "panel": "#f6f8fa",
        "border": "#d0d7de",
        "ink": "#1f2328",
        "muted": "#656d76",
        "faint": "#8c959f",
        "bar_track": "#eaeef2",
    },
}


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def parse_exclude_list(exclude: Optional[str] = None) -> List[str]:
    if not exclude:
        return []
    return [part.strip() for part in exclude.split(",") if part.strip()]


def _stats_dict(stats: Any) -> Dict[str, Any]:
    if stats is None:
        return {}
    if isinstance(stats, Mapping):
        return dict(stats)
    if hasattr(stats, "model_dump"):
        return stats.model_dump()
    if is_dataclass(stats) and not isinstance(stats, type):
        return asdict(stats)
    return {}


def _topic_pairs(raw: Any, exclude: Optional[Sequence[str]] = None) -> List[Tuple[str, int]]:
    banned = {item.lower() for item in (exclude or []) if item}
    pairs: List[Tuple[str, int]] = []
    if not raw:
        return pairs
    for item in raw:
        if isinstance(item, Mapping):
            topic = item.get("topic") or item.get("name") or ""
            count = int(item.get("count") or 0)
        else:
            topic = getattr(item, "topic", None) or getattr(item, "name", "") or ""
            count = int(getattr(item, "count", 0) or 0)
        if not topic:
            continue
        if str(topic).lower() in banned:
            continue
        pairs.append((str(topic), count))
    return pairs


def _fmt_num(value: Optional[Union[int, float]]) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.1f}"
    return f"{int(value):,}"


def _extra_metrics(
    platform_key: str,
    data: Mapping[str, Any],
    extras: Optional[Mapping[str, Any]],
) -> List[Tuple[str, str]]:
    """(label, value) chips shown under the primary total."""
    merged: Dict[str, Any] = {}
    if extras:
        merged.update(extras)

    metrics: List[Tuple[str, str]] = []
    stars = merged.get("totalStars")
    if stars is not None:
        metrics.append(("Total Stars", _fmt_num(stars)))
    repos = merged.get("totalRepos")
    if repos is not None:
        metrics.append(("Repositories", _fmt_num(repos)))
    current = merged.get("currentStreak")
    if current is not None:
        metrics.append(("Current Streak", f"{_fmt_num(current)}d"))
    longest = merged.get("longestStreak")
    if longest is not None:
        metrics.append(("Longest Streak", f"{_fmt_num(longest)}d"))
    return metrics[:4]


def render_stats_svg(
    platform: str,
    username: str,
    stats: Any,
    *,
    accent: Optional[str] = None,
    theme: str = "dark",
    title: Optional[str] = None,
    exclude: Optional[Iterable[str]] = None,
    extras: Optional[Mapping[str, Any]] = None,
) -> str:
    platform_key = (platform or "").lower()
    accent_color = accent or PLATFORM_ACCENTS.get(platform_key, "#609926")
    platform_title = title or PLATFORM_TITLES.get(platform_key, platform_key.title() or "Git Host")
    colors = THEMES.get((theme or "dark").lower(), THEMES["dark"])
    exclude_list = [str(item) for item in (exclude or []) if item]

    data = _stats_dict(stats)
    total_commits = int(data.get("totalSolved") or 0)
    topics = _topic_pairs(data.get("topicAnalysis"), exclude_list)
    total_label = TOTAL_LABELS.get(platform_key, "Total Commits")
    metrics = _extra_metrics(platform_key, data, extras)

    width = 420
    pad_x = 22
    y = 28
    lines: List[str] = []

    lines.append(
        f'<text x="{pad_x}" y="{y}" fill="{_escape(accent_color)}" font-size="13" '
        f'font-weight="700" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">'
        f'{_escape(platform_title)} Stats</text>'
    )
    lines.append(
        f'<text x="{width - pad_x}" y="{y}" fill="{_escape(colors["muted"])}" font-size="12" '
        f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" text-anchor="end">'
        f'@{_escape(username)}</text>'
    )
    y += 18
    lines.append(
        f'<line x1="{pad_x}" y1="{y}" x2="{width - pad_x}" y2="{y}" '
        f'stroke="{_escape(colors["border"])}" stroke-width="1"/>'
    )
    y += 28

    lines.append(
        f'<text x="{pad_x}" y="{y}" fill="{_escape(colors["faint"])}" font-size="11" '
        f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
        f'letter-spacing="0.06em">{_escape(total_label.upper())}</text>'
    )
    y += 26
    lines.append(
        f'<text x="{pad_x}" y="{y}" fill="{_escape(colors["ink"])}" font-size="28" '
        f'font-weight="700" font-family="Inter,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">'
        f'{_escape(_fmt_num(total_commits))}</text>'
    )
    y += 22

    if metrics:
        y += 10
        col_w = (width - 2 * pad_x) / max(len(metrics), 1)
        for idx, (label, value) in enumerate(metrics):
            x = pad_x + idx * col_w
            lines.append(
                f'<text x="{x:.1f}" y="{y}" fill="{_escape(colors["faint"])}" font-size="10" '
                f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" letter-spacing="0.05em">'
                f'{_escape(label.upper())}</text>'
            )
            lines.append(
                f'<text x="{x:.1f}" y="{y + 18}" fill="{_escape(colors["ink"])}" font-size="16" '
                f'font-weight="600" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">'
                f'{_escape(value)}</text>'
            )
        y += 30

    top_topics = topics[:5]
    if top_topics:
        y += 10
        lines.append(
            f'<text x="{pad_x}" y="{y}" fill="{_escape(colors["faint"])}" font-size="11" '
            f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" letter-spacing="0.06em">'
            f'TOP LANGUAGES</text>'
        )
        y += 16
        max_topic = max((count for _, count in top_topics), default=1) or 1
        bar_x = pad_x + 148
        bar_w = width - pad_x - bar_x - 48
        for topic, count in top_topics:
            short = topic if len(topic) <= 18 else topic[:16] + "..."
            lines.append(
                f'<text x="{pad_x}" y="{y + 10}" fill="{_escape(colors["muted"])}" font-size="11" '
                f'font-family="Inter,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">'
                f'{_escape(short)}</text>'
            )
            lines.append(
                f'<rect x="{bar_x}" y="{y + 1}" width="{bar_w}" height="8" rx="3" '
                f'fill="{_escape(colors["bar_track"])}"/>'
            )
            fill_w = max(3, int(bar_w * (count / max_topic))) if count else 0
            if fill_w:
                lines.append(
                    f'<rect x="{bar_x}" y="{y + 1}" width="{fill_w}" height="8" rx="3" '
                    f'fill="{_escape(accent_color)}" opacity="0.85"/>'
                )
            lines.append(
                f'<text x="{width - pad_x}" y="{y + 10}" fill="{_escape(colors["ink"])}" font-size="11" '
                f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace" text-anchor="end">'
                f'{_escape(_fmt_num(count))}</text>'
            )
            y += 18

    height = y + 22
    body = "\n  ".join(lines)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_escape(platform_title)} stats for {_escape(username)}">'
        f"\n  <title>{_escape(platform_title)} Stats - {_escape(username)}</title>\n"
        f'  <rect width="100%" height="100%" rx="8" fill="{_escape(colors["bg"])}" '
        f'stroke="{_escape(colors["border"])}" stroke-width="1"/>\n'
        f"  {body}\n"
        f"</svg>"
    )


def stats_svg_response(
    platform: str,
    username: str,
    stats: Any,
    *,
    theme: str = "dark",
    exclude: Optional[Iterable[str]] = None,
    extras: Optional[Mapping[str, Any]] = None,
) -> Response:
    svg = render_stats_svg(
        platform,
        username,
        stats,
        theme=theme,
        exclude=exclude,
        extras=extras,
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": SVG_CACHE_CONTROL,
            "Content-Type": "image/svg+xml; charset=utf-8",
        },
    )
