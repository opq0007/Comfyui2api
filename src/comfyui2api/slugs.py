from __future__ import annotations

import re
from urllib.parse import urlparse

from .errors import SlugError, UrlError, ValidationError


SLUG_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]{0,62}[a-zA-Z0-9])?$")
DISPLAY_NAME_MAX = 128
MAX_IN_FLIGHT_MIN = 1
MAX_IN_FLIGHT_MAX = 8
HEALTH_INTERVAL_MIN = 5
HEALTH_INTERVAL_MAX = 3600
ROUTING_POLICIES = frozenset({"round_robin", "random"})


def parse_slug(raw: str) -> str:
    slug = str(raw or "").strip()
    if not slug or len(slug) > 64 or ".." in slug or SLUG_RE.fullmatch(slug) is None:
        raise SlugError(
            "slug must match [a-zA-Z0-9._-], length 1-64, no leading/trailing . or -, and no '..'"
        )
    return slug


def parse_display_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    name = str(raw).strip()
    if not name:
        return None
    if len(name) > DISPLAY_NAME_MAX:
        raise ValidationError(f"display_name must be at most {DISPLAY_NAME_MAX} characters")
    return name


def parse_routing_policy(raw: str | None) -> str:
    policy = (raw or "round_robin").strip()
    if policy not in ROUTING_POLICIES:
        raise ValidationError("routing_policy must be round_robin or random")
    return policy


def parse_max_in_flight(raw: int | str | None) -> int:
    if raw is None or raw == "":
        return 1
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError("max_in_flight must be an integer") from exc
    if value < MAX_IN_FLIGHT_MIN or value > MAX_IN_FLIGHT_MAX:
        raise ValidationError(f"max_in_flight must be {MAX_IN_FLIGHT_MIN}-{MAX_IN_FLIGHT_MAX}")
    return value


def parse_health_interval_s(raw: int | str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError("health_interval_s must be an integer") from exc
    if value < HEALTH_INTERVAL_MIN or value > HEALTH_INTERVAL_MAX:
        raise ValidationError(f"health_interval_s must be {HEALTH_INTERVAL_MIN}-{HEALTH_INTERVAL_MAX}")
    return value


def normalize_base_url(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise UrlError("base_url is required")
    parsed = urlparse(text)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise UrlError("base_url must start with http:// or https://")
    if not parsed.netloc:
        raise UrlError("base_url host is required")
    host = (parsed.hostname or "").lower()
    if not host:
        raise UrlError("base_url host is required")
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    netloc = f"{userinfo}{host}{port}"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{path}{query}"
