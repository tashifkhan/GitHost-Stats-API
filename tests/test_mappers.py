from services import mappers
from services.client import _parse_next_link


def ts(day: int, hour: int = 0) -> int:
    # 2026-01-15 00:00 UTC + offsets, within the native 15-minute bucket style
    from datetime import datetime, timezone

    return int(datetime(2026, 1, day, hour, 7, tzinfo=timezone.utc).timestamp())


def test_native_buckets_roll_up_to_days():
    entries = [
        {"timestamp": ts(15), "contributions": 2},
        {"timestamp": ts(15, 3), "contributions": 1},  # same day, later bucket
        {"timestamp": ts(16), "contributions": 4},
    ]
    hm = mappers.heatmap_from_native(entries)
    days = {d.date: d.count for d in hm.dailyContributions}
    assert days["2026-01-15"] == 3
    assert days["2026-01-16"] == 4
    # zero-day fill between first and today keeps calendars continuous
    dates = [d.date for d in hm.dailyContributions]
    assert len(dates) == len(set(dates))
    assert hm.source == "native"
    assert hm.complete is True
    assert hm.availableYears == sorted({int(d.date[:4]) for d in hm.dailyContributions}, reverse=True)


def test_levels_quartiles():
    assert mappers._level(0) == 0
    assert mappers._level(1) == 1
    assert mappers._level(3) == 2
    assert mappers._level(6) == 3
    assert mappers._level(50) == 4


def test_repo_totals_skip_private():
    repos = [
        {"id": 1, "name": "a", "owner": {"login": "taf"}, "stars_count": 5, "forks_count": 1},
        {
            "id": 2,
            "name": "b",
            "owner": {"login": "taf"},
            "stars_count": 99,
            "forks_count": 9,
            "private": True,
        },
    ]
    model = mappers.repos_from_list(repos)
    assert model.count == 2
    assert model.totalStars == 5
    assert model.totalForks == 1


def test_identity_matching_rules():
    commit_login = {"author": {"login": "Taf"}, "commit": {"author": {"name": "Other", "email": "x@y.z"}}}
    commit_email_local = {"author": None, "commit": {"author": {"name": "Whatever", "email": "taf@codeberg.org"}}}
    commit_exact_email = {"author": None, "commit": {"author": {"name": "W", "email": "me@private.dev"}}}
    commit_other = {"author": {"login": "someone"}, "commit": {"author": {"name": "Someone Else", "email": "s@x.y"}}}

    from services.history import _matches_identity

    assert _matches_identity(commit_login, "taf", set())
    assert _matches_identity(commit_email_local, "taf", set())
    assert _matches_identity(commit_exact_email, "other-name", {"me@private.dev"})
    assert not _matches_identity(commit_other, "taf", set())


def test_next_link_parsing():
    header = '<https://git.taf.sh/api/v1/users/taf/repos?limit=30&page=2>; rel="next", <https://git.taf.sh/api/v1/users/taf/repos?limit=30&page=1>; rel="prev"'
    assert _parse_next_link(header) == "https://git.taf.sh/api/v1/users/taf/repos?limit=30&page=2"
    assert _parse_next_link(None) is None
    assert _parse_next_link('<https://x/y>; rel="prev"') is None
