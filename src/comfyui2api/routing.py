from __future__ import annotations

import random
from collections.abc import Sequence


def pick_instance(
    *,
    policy: str,
    ready_slugs: Sequence[str],
    cursor: str | None,
    rng: random.Random | None = None,
) -> tuple[str | None, str | None]:
    """Pick one ready instance. Returns (slug, next_cursor)."""
    ready = [slug for slug in ready_slugs if slug]
    if not ready:
        return None, cursor
    if policy == "random":
        chooser = rng or random
        return chooser.choice(list(ready)), cursor
    ordered = list(ready)
    start = 0
    if cursor in ordered:
        start = ordered.index(cursor)
    chosen = ordered[start]
    next_index = (start + 1) % len(ordered)
    return chosen, ordered[next_index]


def ordered_pool(slugs: Sequence[str]) -> list[str]:
    return sorted({slug for slug in slugs if slug})
