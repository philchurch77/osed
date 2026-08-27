"""Operations & Resources — RAG evaluation.

Four states, not three. **Blue means "not yet benchmarked" and is never Green.**
Where a threshold does not exist (the Primary ICFP bands are the clearest case,
and are not expected to arrive) or where history does not exist yet (a school's
first term of complaints data), the tile is Blue. An unset threshold reading as
"fine" would create exactly the false assurance the tool exists to remove.

Bands live in the database (OperationsMetricBand), not here — they will change.
What lives here is the *shape* of each evaluation: how a value is compared with
whatever bands the metric carries. Each metric names one rule.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

GREEN = "green"
AMBER = "amber"
RED = "red"
BLUE = "blue"

RAG_CHOICES = [
    (GREEN, "Green"),
    (AMBER, "Amber"),
    (RED, "Red"),
    (BLUE, "Blue"),
]

RAG_LABELS = dict(RAG_CHOICES)

RAG_LEGEND = [
    (GREEN, "Green — on track"),
    (AMBER, "Amber — monitor"),
    (RED, "Red — needs action"),
    (BLUE, "Blue — not yet benchmarked"),
]

# Standing text from the source document, shown verbatim beneath the legend.
LEGEND_STANDING_TEXT = (
    "An amber or red flag opens a conversation at TFORS or SIV — it is not, on "
    "its own, a judgement."
)

# Standing small print, shown verbatim wherever ICFP-derived metrics appear.
SMALL_PRINT = (
    "Benchmarks (Finance & ICFP) are set for typical-sized schools. Smaller "
    "schools may show as amber or red for reasons of scale rather than "
    "performance — check the commentary before drawing conclusions. Tiles marked "
    "Blue are not yet benchmarked and should not be read as green."
)

# Ordering for summaries. Blue sits outside the scale deliberately: it is not a
# position on a green-to-red axis, it is the absence of one.
SEVERITY = {GREEN: 0, AMBER: 1, RED: 2}


# --------------------------------------------------------------------------
# Statutory compliance — five dated items, RAG computed from the dates
# --------------------------------------------------------------------------
STATUTORY_ITEMS: list[tuple[str, str]] = [
    ("fire_risk_assessment", "Fire risk assessment"),
    ("legionella", "Legionella"),
    ("asbestos", "Asbestos"),
    ("gas_electrical", "Gas / electrical safety"),
    ("epc", "EPC"),
]

STATUTORY_ITEM_LABELS = dict(STATUTORY_ITEMS)

# "Overdue <1 month" in the source bands.
OVERDUE_AMBER_LIMIT = timedelta(days=30)


def statutory_rag(items, *, today: date | None = None) -> str:
    """Green if all five are in date; Amber if what is overdue is recent and has
    an action plan; Red otherwise. Blue while the five dates are not all known.

    The bands name "one item overdue <1 month, action plan in place" for Amber;
    anything worse — overdue longer, or overdue with no plan — is Red.
    """

    today = today or date.today()
    dated = [i for i in items if i.next_due_date]
    if len(dated) < len(STATUTORY_ITEMS):
        return BLUE

    overdue = [i for i in dated if i.next_due_date < today]
    if not overdue:
        return GREEN

    for item in overdue:
        if (today - item.next_due_date) > OVERDUE_AMBER_LIMIT:
            return RED
        if not item.action_plan_in_place:
            return RED
    return AMBER


# --------------------------------------------------------------------------
# Ring-fenced grants — the applicable set depends on phase and type
# --------------------------------------------------------------------------
GRANT_PUPIL_PREMIUM = "pupil_premium"
GRANT_INCLUSIVE_MAINSTREAM = "inclusive_mainstream"
GRANT_PE_SPORT = "pe_sport"

GRANT_CHOICES = [
    (GRANT_PUPIL_PREMIUM, "Pupil Premium"),
    (GRANT_INCLUSIVE_MAINSTREAM, "Inclusive Mainstream Fund"),
    (GRANT_PE_SPORT, "PE and Sport Premium"),
]

GRANT_LABELS = dict(GRANT_CHOICES)

GRANT_PUBLISHED = "published"
GRANT_DRAFTED = "drafted"
GRANT_MISSED = "missed"

GRANT_STATUS_CHOICES = [
    (GRANT_PUBLISHED, "Published and on file, on time"),
    (GRANT_DRAFTED, "Drafted but not published"),
    (GRANT_MISSED, "Deadline missed"),
]


def applicable_grants(school) -> list[str]:
    """Which grants a school actually has to publish for.

    Pupil Premium applies to all schools; the Inclusive Mainstream Fund to
    mainstream schools; PE and Sport Premium to primaries. "All applicable" in
    the source bands means this set, not a fixed checklist.
    """

    grants = [GRANT_PUPIL_PREMIUM]
    if getattr(school, "is_mainstream", True):
        grants.append(GRANT_INCLUSIVE_MAINSTREAM)
    if getattr(school, "phase", "") == "PRIMARY":
        grants.append(GRANT_PE_SPORT)
    return grants


def grant_rag(school, records) -> str:
    """Green when every applicable grant is published; Blue until they are known."""

    needed = applicable_grants(school)
    by_grant = {r.grant: r for r in records}
    if any(g not in by_grant for g in needed):
        return BLUE

    statuses = [by_grant[g].status for g in needed]
    if any(s == GRANT_MISSED for s in statuses):
        return RED
    if any(s == GRANT_DRAFTED for s in statuses):
        return AMBER
    return GREEN


# --------------------------------------------------------------------------
# Complaints — RAG from the school's own trend, never entered
# --------------------------------------------------------------------------
def complaints_rag(current: int | None, history: list[int], *, step_change: int = 3) -> str:
    """Trend, not volume. No prior term's figure means Blue, never Green.

    `history` is the count for each earlier term, oldest first. Red needs two
    consecutive rises, so it needs two prior terms; a single marked step-change
    also reaches Red.

    NOTE: "a marked step-change in a single term" is not defined in the source
    document. `step_change` is the working threshold and is carried on the
    metric's band record so it can be changed without a deploy — it still needs
    confirming with the client.
    """

    if current is None:
        return BLUE
    if not history:
        # First term of the pilot: nothing to compare against. Do not let
        # "no prior data" collapse into "flat or falling".
        return BLUE

    previous = history[-1]
    if current - previous >= step_change:
        return RED
    if current <= previous:
        return GREEN

    # Rising. Two or more consecutive rises is Red.
    if len(history) >= 2 and previous > history[-2]:
        return RED
    return AMBER


# --------------------------------------------------------------------------
# Entered metrics
# --------------------------------------------------------------------------
def _dec(value) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def band_choice_rag(choice: str | None) -> str:
    """The Principal picks which of the three band statements applies."""

    if choice in (GREEN, AMBER, RED):
        return choice
    return BLUE


def numeric_range_rag(value, band) -> str:
    """Green inside the green range, Amber inside the wider amber range, else Red.

    Revenue reserves (green 3-8, amber 0-15) and staff costs (green 73-76, amber
    69-80, i.e. "up to 4 points outside") are both expressed this way.
    """

    value = _dec(value)
    if value is None:
        return BLUE
    if band is None or band.green_min is None or band.green_max is None:
        # No threshold set for this school's phase — Blue, never Green.
        return BLUE

    if band.green_min <= value <= band.green_max:
        return GREEN
    if band.amber_min is not None and band.amber_max is not None:
        if band.amber_min <= value <= band.amber_max:
            return AMBER
    return RED


def vs_comparator_pct_rag(value, band) -> str:
    """At or below the national figure is Green; within a % tolerance, Amber."""

    value = _dec(value)
    if value is None:
        return BLUE
    if band is None or band.comparator_value is None or band.amber_tolerance is None:
        return BLUE

    comparator = band.comparator_value
    if value <= comparator:
        return GREEN
    if value <= comparator * (1 + band.amber_tolerance / Decimal(100)):
        return AMBER
    return RED


def vs_comparator_points_rag(value, band) -> str:
    """At or below the national rate is Green; within N percentage points, Amber."""

    value = _dec(value)
    if value is None:
        return BLUE
    if band is None or band.comparator_value is None or band.amber_tolerance is None:
        return BLUE

    comparator = band.comparator_value
    if value <= comparator:
        return GREEN
    if value <= comparator + band.amber_tolerance:
        return AMBER
    return RED


def count_threshold_rag(value, band) -> str:
    """Meeting all of N is Green; meeting at least the amber floor is Amber."""

    if value is None:
        return BLUE
    if band is None or band.green_min is None or band.amber_min is None:
        return BLUE

    value = _dec(value)
    if value >= band.green_min:
        return GREEN
    if value >= band.amber_min:
        return AMBER
    return RED


# Rule keys. A metric names one; the band record supplies its numbers.
RULE_BAND_CHOICE = "band_choice"
RULE_NUMERIC_RANGE = "numeric_range"
RULE_VS_COMPARATOR_PCT = "vs_comparator_pct"
RULE_VS_COMPARATOR_POINTS = "vs_comparator_points"
RULE_COUNT_THRESHOLD = "count_threshold"
RULE_STATUTORY_DATES = "statutory_dates"
RULE_COMPLAINTS_TREND = "complaints_trend"
RULE_GRANT_PUBLICATION = "grant_publication"

RULE_CHOICES = [
    (RULE_BAND_CHOICE, "Choose the band statement that applies"),
    (RULE_NUMERIC_RANGE, "Numeric value against banded ranges"),
    (RULE_VS_COMPARATOR_PCT, "Numeric value against a national comparator (% tolerance)"),
    (RULE_VS_COMPARATOR_POINTS, "Numeric value against a national comparator (percentage points)"),
    (RULE_COUNT_THRESHOLD, "Count met against thresholds"),
    (RULE_STATUTORY_DATES, "Computed from statutory compliance due dates"),
    (RULE_COMPLAINTS_TREND, "Computed from the school's own complaints trend"),
    (RULE_GRANT_PUBLICATION, "Computed from the applicable grant checklist"),
]

# Rules whose RAG is derived from other records, never from an entered value.
COMPUTED_RULES = {
    RULE_STATUTORY_DATES,
    RULE_COMPLAINTS_TREND,
    RULE_GRANT_PUBLICATION,
}

# Rules that take a number rather than a band choice.
NUMERIC_RULES = {
    RULE_NUMERIC_RANGE,
    RULE_VS_COMPARATOR_PCT,
    RULE_VS_COMPARATOR_POINTS,
    RULE_COUNT_THRESHOLD,
}


def rag_for_entry(metric, entry, band) -> str:
    """RAG for an entered metric. Computed metrics are evaluated elsewhere."""

    if entry is None:
        return BLUE

    # Some red triggers in the source bands are not computable from a single
    # figure ("a core-subject vacancy unfilled a full term"). Recording one is
    # explicit and carries a reason.
    if getattr(entry, "manual_red_reason", ""):
        return RED

    if metric.rule == RULE_BAND_CHOICE:
        return band_choice_rag(entry.band_choice)
    if metric.rule == RULE_NUMERIC_RANGE:
        return numeric_range_rag(entry.value, band)
    if metric.rule == RULE_VS_COMPARATOR_PCT:
        return vs_comparator_pct_rag(entry.value, band)
    if metric.rule == RULE_VS_COMPARATOR_POINTS:
        return vs_comparator_points_rag(entry.value, band)
    if metric.rule == RULE_COUNT_THRESHOLD:
        return count_threshold_rag(entry.value, band)
    return BLUE


def summarise(rags) -> dict:
    """Counts by colour for a roll-up.

    Hidden metrics never reach this function — they are excluded before it is
    called, so they are out of the denominator rather than counted as complete.
    Blue is reported on its own and never folded into Green.
    """

    rags = list(rags)
    counts = {colour: sum(1 for r in rags if r == colour) for colour, _ in RAG_CHOICES}
    worst = None
    for rag in rags:
        if rag in SEVERITY and (worst is None or SEVERITY[rag] > SEVERITY[worst]):
            worst = rag
    return {
        "counts": counts,
        "total": len(rags),
        "worst": worst,
        "green": counts[GREEN],
        "amber": counts[AMBER],
        "red": counts[RED],
        "blue": counts[BLUE],
    }
