"""Shared judgement-area reload used by load_indepth_criteria and
import_indepth_workbooks.

Both commands run unattended on every Azure deploy (startup.sh). They used to
rebuild a standard's judgement areas with `standard.judgement_areas.all().delete()`
followed by a bulk_create. InDepthResponse.judgement_area is a CASCADE, so that
deleted every school's commentary and next steps on each deploy, then rebuilt the
statements at fresh pks so the app looked untouched afterwards.

This module reloads the same data in place instead. A statement whose wording has
not changed keeps its pk, so the responses hanging off it survive. A statement that
has genuinely gone is only deleted when nobody has written against it; if it holds
written work it is kept and reported, because losing a leader's write-up is worse
than carrying a retired statement.

The filename starts with an underscore so Django's command discovery skips it.
"""
from __future__ import annotations

import re

from review.models import InDepthJudgementArea

_WHITESPACE = re.compile(r"\s+")


def _identity(statement: str) -> str:
    """Match key for a statement: ignore casing and whitespace churn only."""
    return _WHITESPACE.sub(" ", (statement or "").strip()).casefold()


def sync_judgement_areas(standard, rows: list[dict]) -> tuple[int, int, int]:
    """Reload one standard's judgement areas without destroying written work.

    `rows` holds the incoming field values in display order, excluding `standard`
    and `order` (both are set here).

    Returns (written, deleted, kept_with_responses).
    """
    existing = list(standard.judgement_areas.all())
    by_identity: dict[str, list] = {}
    for ja in existing:
        by_identity.setdefault(_identity(ja.statement), []).append(ja)

    written = 0
    for index, data in enumerate(rows):
        order = index + 1
        bucket = by_identity.get(_identity(data.get("statement", "")))
        match = bucket.pop(0) if bucket else None
        if match is None:
            InDepthJudgementArea.objects.create(standard=standard, order=order, **data)
        else:
            for field, value in data.items():
                setattr(match, field, value)
            match.order = order
            match.save()
        written += 1

    # Anything left unmatched is no longer in the source data.
    leftovers = [ja for bucket in by_identity.values() for ja in bucket]
    deleted = kept = 0
    for offset, ja in enumerate(leftovers):
        if ja.responses.exists():
            # Someone has written against this statement. Keep it, and park it
            # after the current ones so the live statements render in order.
            ja.order = len(rows) + offset + 1
            ja.save(update_fields=["order"])
            kept += 1
        else:
            ja.delete()
            deleted += 1

    return written, deleted, kept
