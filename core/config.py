import os


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class GithostSettings:
    # Registry: "taf=https://git.taf.sh,codeberg=https://codeberg.org,gitea=https://gitea.com"
    instances_raw = os.getenv(
        "GITHOST_INSTANCES",
        "taf=https://git.taf.sh,codeberg=https://codeberg.org,gitea=https://gitea.com",
    )

    # Caller-supplied base_url handling
    allow_custom_base = _flag("GITHOST_ALLOW_CUSTOM_BASE", "true")
    # Disable only when this service itself sits inside a private network and
    # must reach tailnet/LAN instances.
    block_private_ips = _flag("GITHOST_BLOCK_PRIVATE_IPS", "true")
    custom_concurrency = int(os.getenv("GITHOST_CUSTOM_CONCURRENCY", "2"))
    default_registered_concurrency = int(os.getenv("GITHOST_CONCURRENCY", "4"))

    # Deep history delta walk
    history_max_pages = int(os.getenv("GITHOST_HISTORY_MAX_PAGES", "40"))
    request_deadline_seconds = float(os.getenv("GITHOST_REQUEST_DEADLINE", "3.5"))

    # Cache TTLs (seconds)
    version_ttl = int(os.getenv("GITHOST_VERSION_TTL", str(86400)))
    settings_ttl = int(os.getenv("GITHOST_SETTINGS_TTL", str(86400)))
    profile_ttl = int(os.getenv("GITHOST_PROFILE_TTL", "3600"))
    repos_ttl = int(os.getenv("GITHOST_REPOS_TTL", "1800"))
    languages_ttl = int(os.getenv("GITHOST_LANGUAGES_TTL", "86400"))
    heatmap_ttl = int(os.getenv("GITHOST_HEATMAP_TTL", "900"))
    miss_ttl = int(os.getenv("GITHOST_MISS_TTL", "300"))
    hist_ttl = int(os.getenv("GITHOST_HIST_TTL", str(30 * 86400)))

    # Upstream politeness
    upstream_timeout_seconds = float(os.getenv("GITHOST_UPSTREAM_TIMEOUT", "20"))
    max_retries = int(os.getenv("GITHOST_MAX_RETRIES", "2"))

    # Shared cache/rate-limit knobs (same names as the sibling services)
    redis_url = os.getenv("REDIS_URL")
    upstash_rest_url = os.getenv("UPSTASH_REDIS_REST_URL")
    upstash_rest_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    cache_ttl_seconds = int(os.getenv("API_CACHE_TTL_SECONDS", "3600"))
    invalid_user_cache_ttl_seconds = int(os.getenv("INVALID_USER_CACHE_TTL_SECONDS", "300"))
    rate_limit_ip_requests = int(os.getenv("RATE_LIMIT_IP_REQUESTS", "60"))
    rate_limit_handle_requests = int(os.getenv("RATE_LIMIT_HANDLE_REQUESTS", "30"))
    rate_limit_window_seconds = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    invalid_rate_limit_ip_requests = int(os.getenv("INVALID_RATE_LIMIT_IP_REQUESTS", "10"))
    invalid_rate_limit_handle_requests = int(os.getenv("INVALID_RATE_LIMIT_HANDLE_REQUESTS", "5"))
    invalid_rate_limit_window_seconds = int(os.getenv("INVALID_RATE_LIMIT_WINDOW_SECONDS", "600"))
    rate_limit_backoff_base_seconds = int(os.getenv("RATE_LIMIT_BACKOFF_BASE_SECONDS", "5"))
    rate_limit_backoff_max_seconds = int(os.getenv("RATE_LIMIT_BACKOFF_MAX_SECONDS", "300"))


settings = GithostSettings()
