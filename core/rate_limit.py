"""Atomic counters and backoff, one bounded store call per dimension."""

import time
from dataclasses import dataclass

from core.cache import command
from core.config import settings

# KEYS: backoff, counter, violations. ARGV: limit, window, backoff base, backoff max.
# Returns {allowed, ttl, remaining}. Mirrors the old multi-call flow in one
# round trip, so a slow store costs at most one bounded call per check.
RATE_SCRIPT = """
local backoff = redis.call('TTL', KEYS[1])
if backoff > 0 then return {0, backoff, 0} end
local limit = tonumber(ARGV[1])
local count = redis.call('INCR', KEYS[2])
if count == 1 or redis.call('TTL', KEYS[2]) < 0 then
  redis.call('EXPIRE', KEYS[2], ARGV[2])
end
local ttl = redis.call('TTL', KEYS[2])
if count <= limit then
  redis.call('DEL', KEYS[3])
  return {1, ttl, limit - count}
end
local violations = redis.call('INCR', KEYS[3])
redis.call('EXPIRE', KEYS[3], ARGV[4])
local delay = math.floor(math.min(tonumber(ARGV[3]) * 2 ^ math.min(violations - 1, 20), tonumber(ARGV[4])))
if delay < 1 then delay = 1 end
redis.call('SET', KEYS[1], '1', 'EX', delay)
return {0, delay, 0}
"""


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after: int = 0
    limited_by: str | None = None
    limit: int | None = None
    remaining: int | None = None
    reset_at: int | None = None


async def check_rate_limit(key: str, limit: int, window_seconds: int, label: str) -> RateLimitResult:
    result = await command(
        "eval", RATE_SCRIPT, 3, "backoff:" + key, "rl:" + key, "violations:" + key,
        limit, window_seconds,
        settings.rate_limit_backoff_base_seconds, settings.rate_limit_backoff_max_seconds,
    )
    try:
        allowed, ttl, remaining = (int(value) for value in result)
    except (TypeError, ValueError):
        # Store down, slow, or unexpected reply: fail open.
        return RateLimitResult(allowed=True)
    now = int(time.time())
    if allowed:
        return RateLimitResult(True, 0, label, limit, max(remaining, 0), now + max(ttl, 0))
    retry_after = max(1, ttl)
    return RateLimitResult(False, retry_after, label, limit, 0, now + retry_after)

