"""Risk scoring — the Trust's Risk Management Framework, in one place.

Impact x Likelihood -> band -> RAG colour. Nothing else in the app may map a
risk to a colour: if the Risk Management Framework (Final, Sept 2025) arrives
and disagrees, BAND_MATRIX / BAND_TO_RAG are the only edits needed.

Note: the client mockup's illustrative register rows do not all agree with the
mockup's own matrix (four of six disagree). The matrix is the specification;
the rows are sample content.
"""

from __future__ import annotations


# Field values are the human-readable strings so the matrix can be keyed
# directly off what is stored on RiskRating.
IMPACT_HIGH = "High"
IMPACT_MEDIUM = "Medium"
IMPACT_LOW = "Low"

LIKELIHOOD_UNLIKELY = "Unlikely"
LIKELIHOOD_POSSIBLE = "Possible"
LIKELIHOOD_HIGHLY_PROBABLE = "Highly probable"

IMPACT_CHOICES = [
    (IMPACT_LOW, "Low"),
    (IMPACT_MEDIUM, "Medium"),
    (IMPACT_HIGH, "High"),
]

LIKELIHOOD_CHOICES = [
    (LIKELIHOOD_UNLIKELY, "Unlikely"),
    (LIKELIHOOD_POSSIBLE, "Possible"),
    (LIKELIHOOD_HIGHLY_PROBABLE, "Highly probable"),
]


# Band keys
CRITICAL = "critical"
HIGH_PRIORITY = "high_priority"
MEDIUM_PRIORITY = "medium_priority"
MONITOR = "monitor"
LOW_RISK = "low_risk"

BAND_CHOICES = [
    (CRITICAL, "Critical"),
    (HIGH_PRIORITY, "High priority"),
    (MEDIUM_PRIORITY, "Medium priority"),
    (MONITOR, "Monitor"),
    (LOW_RISK, "Low risk"),
]

BAND_LABELS = dict(BAND_CHOICES)


#                       Unlikely        Possible          Highly probable
# High impact           Monitor         High priority     Critical
# Medium impact         Low risk        Medium priority   High priority
# Low impact            Low risk        Low risk          Monitor
BAND_MATRIX: dict[tuple[str, str], str] = {
    (IMPACT_HIGH, LIKELIHOOD_UNLIKELY): MONITOR,
    (IMPACT_HIGH, LIKELIHOOD_POSSIBLE): HIGH_PRIORITY,
    (IMPACT_HIGH, LIKELIHOOD_HIGHLY_PROBABLE): CRITICAL,
    (IMPACT_MEDIUM, LIKELIHOOD_UNLIKELY): LOW_RISK,
    (IMPACT_MEDIUM, LIKELIHOOD_POSSIBLE): MEDIUM_PRIORITY,
    (IMPACT_MEDIUM, LIKELIHOOD_HIGHLY_PROBABLE): HIGH_PRIORITY,
    (IMPACT_LOW, LIKELIHOOD_UNLIKELY): LOW_RISK,
    (IMPACT_LOW, LIKELIHOOD_POSSIBLE): LOW_RISK,
    (IMPACT_LOW, LIKELIHOOD_HIGHLY_PROBABLE): MONITOR,
}


# Four colours, not three — Yellow sits between Green and Amber.
RED = "Red"
AMBER = "Amber"
YELLOW = "Yellow"
GREEN = "Green"

BAND_TO_RAG: dict[str, str] = {
    CRITICAL: RED,
    HIGH_PRIORITY: AMBER,
    MEDIUM_PRIORITY: YELLOW,
    MONITOR: YELLOW,
    LOW_RISK: GREEN,
}

RAG_LEGEND = [
    (RED, "Red — immediate action"),
    (AMBER, "Amber — mitigate asap"),
    (YELLOW, "Yellow — monitor"),
    (GREEN, "Green — under control"),
]

# Ordering used for "worsening" / "improving" and for the RAG threshold filter.
SEVERITY: dict[str, int] = {GREEN: 0, YELLOW: 1, AMBER: 2, RED: 3}

# CSS modifier suffix per colour, e.g. .risk-chip--red
RAG_CSS = {RED: "red", AMBER: "amber", YELLOW: "yellow", GREEN: "green"}


def band_for(impact: str, likelihood: str) -> str:
    """Return the framework band key for an impact/likelihood pair."""

    return BAND_MATRIX[(impact, likelihood)]


def rag_for(impact: str, likelihood: str) -> str:
    """Return the RAG colour ("Red"/"Amber"/"Yellow"/"Green") for a pair."""

    return BAND_TO_RAG[band_for(impact, likelihood)]


def rag_for_band(band: str) -> str:
    return BAND_TO_RAG[band]


def severity_for_band(band: str) -> int:
    return SEVERITY[BAND_TO_RAG[band]]


# Trend states
IMPROVING = "improving"
PERSISTING = "persisting"
WORSENING = "worsening"

TREND_LABELS = {
    IMPROVING: "Improving",
    PERSISTING: "Persisting",
    WORSENING: "Worsening",
}


def trend_for(current_band: str | None, previous_band: str | None) -> str | None:
    """Compare this term's band with last term's.

    Returns "improving", "persisting", "worsening", or None when there is no
    prior rating to compare against. "Persisting" is reserved for a rating that
    is unchanged and still Amber or Red — an unchanged Green is not a concern.
    """

    if not current_band or not previous_band:
        return None

    current = severity_for_band(current_band)
    previous = severity_for_band(previous_band)

    if current > previous:
        return WORSENING
    if current < previous:
        return IMPROVING
    if current >= SEVERITY[AMBER]:
        return PERSISTING
    return None


def matrix_rows() -> list[dict]:
    """The 3x3 matrix as rows, for rendering the scoring card."""

    rows = []
    for impact in (IMPACT_HIGH, IMPACT_MEDIUM, IMPACT_LOW):
        cells = []
        for likelihood in (
            LIKELIHOOD_UNLIKELY,
            LIKELIHOOD_POSSIBLE,
            LIKELIHOOD_HIGHLY_PROBABLE,
        ):
            band = band_for(impact, likelihood)
            rag = BAND_TO_RAG[band]
            cells.append({
                "impact": impact,
                "likelihood": likelihood,
                "band": band,
                "band_label": BAND_LABELS[band],
                "rag": rag,
                "rag_css": RAG_CSS[rag],
            })
        rows.append({"impact": impact, "label": f"{impact} impact", "cells": cells})
    return rows


def matrix_lookup() -> dict[str, dict[str, str]]:
    """Flat {impact: {likelihood: band_label}} map, for the form live preview."""

    out: dict[str, dict[str, str]] = {}
    for (impact, likelihood), band in BAND_MATRIX.items():
        out.setdefault(impact, {})[likelihood] = {
            "band": BAND_LABELS[band],
            "rag": BAND_TO_RAG[band],
            "css": RAG_CSS[BAND_TO_RAG[band]],
        }
    return out


def is_escalated(band: str | None, trend: str | None, settings) -> bool:
    """Should this rating escalate to the Finance, Audit and Risk Committee?

    The starting rule is Red only — a risk may sit at Amber for several terms
    without escalating. The threshold is configurable (RiskSettings) because the
    client expects to revisit it once there is real data; flipping the setting
    must not need a code change.
    """

    if not band:
        return False

    if band in (settings.escalate_bands or []):
        return True

    if (
        getattr(settings, "escalate_persisting_amber", False)
        and trend == PERSISTING
        and BAND_TO_RAG[band] == AMBER
    ):
        return True

    return False
