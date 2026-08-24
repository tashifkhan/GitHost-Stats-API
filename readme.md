# GitHost Stats API

User stats for any git host: your own Forgejo box, Codeberg, gitea.com, or any
Gitea-compatible instance passed as a base URL. It lives beside the other Stat
APIs services and speaks their canonical envelope
(`status / message / platform / username / cached / data`). Two extra fields,
`instance` and `software`, name the forge that answered.

## Run

```bash
uv sync
cp .env.example .env   # optional: tokens, registry, redis
uv run uvicorn main:app --reload --port 8008
```

## Endpoints

| Section | Path | Notes |
| --- | --- | --- |
| Summary | `GET /{username}` | totals |
| Profile | `GET /{username}/profile` | |
| Stats | `GET /{username}/stats` | language bars; `?exclude=Markdown,SVG` |
| Heatmap | `GET /{username}/heatmap` | `view=all\|last_365\|year`, `year=2026`, `deep=true` |
| Badges | `GET /{username}/badges` | derived achievements |
| Repos | `GET /{username}/repos` | with star/fork totals |
| Orgs | `GET /{username}/orgs` | may be `restricted` without a token |

Target selection: `?host=<registered-key-or-hostname>`,
`?base_url=https://git.example.com` (SSRF-guarded), or the embed-safe prefix
`/f/{host}/{username}/...`. Requests without an explicit host are rejected.

Envelope additions over the canonical schema: `platform` reads `forgejo` or
`gitea` from a live version probe, `instance` is the registry key (hostname for
custom URLs), and `software` carries `{name, version}`.

## Deep history

Every Gitea-family heatmap endpoint caps at ~371 days server-side. Pass
`deep=true` to rebuild the full calendar from commit walks:

* a Redis manifest keyed by `repo.id` stores `{pushed_at, head_sha, oldest_sha,
  complete}` per repo
* repos whose `pushed_at` did not change reuse their cached day histograms at
  zero upstream cost
* changed repos walk newest-first until the stored head SHA, so only new pages
  land
* each request carries a deadline budget; an unfinished walk persists its
  bookmark and resumes on the next call, flagged `complete: false`
* heatmap blocks report `"source": "native" | "synthesized"`

Design notes and the full evaluation live in
[dump 038](https://dump.taf.sh/d/038_githoststats-one-api-every-git-host-plan/)
on dump.taf.sh.
