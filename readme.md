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
| Repos | `GET /{username}/repos` | star/fork totals and contributors, including co-authors |
| Orgs | `GET /{username}/orgs` | may be `restricted` without a token |

Target selection: `?host=<registered-key-or-hostname>`,
`?base_url=https://git.example.com` (SSRF-guarded), or the embed-safe prefix
`/f/{host}/{username}/...`. Requests without an explicit host are rejected.

Envelope additions over the canonical schema: `platform` reads `forgejo` or
`gitea` from a live version probe, `instance` is the registry key (hostname for
custom URLs), and `software` carries `{name, version}`.

## Repository contributors

Both `/{username}/repos?host=...` and `/f/{host}/{username}/repos` add a
`contributors` list and `contributors_complete` to each repo. The list contains
the top 10 contributors by authored plus co-authored commits on the default
branch. Each commit counts once per contributor, including when an account
appears as both the primary author and a `Co-authored-by` trailer.

Each entry has `login`, `name`, `avatar_url`, `html_url`, and `contributions`.
Linked commit authors supply account details. Matching commit emails merge
co-author credit into those accounts, even if the linked author appears on a
later page. The requested user's public email and `?emails=...` aliases also
link their credit. If an email has no known account, the entry keeps its name
and count with null account fields. The response does not expose commit emails.

Scans share a request deadline and respect `GITHOST_HISTORY_MAX_PAGES`. Redis
checkpoints pin the head commit and save the next page so later requests can
continue. Changed repo timestamps start a fresh scan. `contributors_complete`
is false until the scan finishes, and partial responses use `Cache-Control:
no-store` so HTTP caching does not prevent progress. Redis must be configured
to preserve progress between requests. Forks and mirrors include their full
default-branch contributor history.

## Deep history

Every Gitea-family heatmap endpoint caps at ~371 days server-side. Pass
`deep=true` to rebuild the full calendar from commit walks.

The walk counts primary authors and `Co-authored-by: Name <email>` trailers.
It matches the forge login, the user's public email, any `extra_emails` supplied
to the history service, or an email whose local part equals the username. A
commit counts once even when multiple authorship fields match the user.

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
