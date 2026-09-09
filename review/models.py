from django.db import models
from django.contrib.auth.models import User
from simple_history.models import HistoricalRecords
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone

from .operations import (
    COMPUTED_RULES,
    GRANT_CHOICES,
    GRANT_LABELS,
    GRANT_STATUS_CHOICES,
    NUMERIC_RULES,
    RAG_CHOICES,
    RULE_CHOICES,
    STATUTORY_ITEM_LABELS,
    STATUTORY_ITEMS,
    rag_for_entry,
)
from .risk import (
    BAND_CHOICES,
    IMPACT_CHOICES,
    LIKELIHOOD_CHOICES,
    band_for,
    rag_for_band,
)


def current_academic_year_start() -> int:
    """Return the academic year start (UK-style, Sep-Aug).

    Example: May 2026 -> 2025 (academic year 2025/2026)
             Oct 2026 -> 2026 (academic year 2026/2027)
    """

    today = timezone.now().date()
    return today.year if today.month >= 9 else today.year - 1

class School(models.Model):
    class Phase(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        SECONDARY = "SECONDARY", "Secondary"

    name = models.CharField(max_length=200)
    phase = models.CharField(max_length=20, choices=Phase.choices, blank=True, default="")
    # Needed to work out which ring-fenced grants a school must publish for:
    # the Inclusive Mainstream Fund is mainstream-only.
    is_mainstream = models.BooleanField(default=True)
    logo = models.ImageField(upload_to="school_logos/", blank=True, null=True)

    def __str__(self):
        return self.name

class Category(models.Model):
    name = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        # Django's default plural would be "Categorys". Note this is the 8
        # dashboard evaluation categories, not TrustCategory.
        verbose_name = "Category"
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name
    
class SchoolProfile(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    schools = models.ManyToManyField(
        School,
        blank=True,
        related_name="school_profiles",
    )

    def __str__(self):
        return f"{self.user.username} - {self.school.name}"


# A review period's `round` is the school term. The stored values stay 1/2/3
# (no data change); only the labels are termly. Use TERM_LABELS anywhere a round
# number has to be shown to a user.
TERM_LABELS: dict[int, str] = {1: "Autumn", 2: "Spring", 3: "Summer"}


def term_label(round_number: int | None) -> str:
    return TERM_LABELS.get(round_number, "")


class ReviewPeriod(models.Model):
    class Round(models.IntegerChoices):
        AUTUMN = 1, "Autumn"
        SPRING = 2, "Spring"
        SUMMER = 3, "Summer"

    # Stored as academic year start, displayed as YYYY/YYYY+1
    year = models.PositiveSmallIntegerField(default=current_academic_year_start)
    round = models.PositiveSmallIntegerField(choices=Round.choices, default=Round.AUTUMN)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round"],
                name="unique_review_period_year_round",
            )
        ]
        ordering = ("-year", "round")

    @property
    def term_label(self) -> str:
        return term_label(self.round)

    def __str__(self):
        return f"{self.year}/{self.year + 1} - {self.term_label} term"


class Evaluation(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    period = models.ForeignKey(ReviewPeriod, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Version trail. The auto_now stamp is excluded: it changes on every save and
    # would make each history row unique for no gain, and history_date records the
    # same fact. created_at is auto_now_add, so it is constant and worth keeping.
    history = HistoricalRecords(excluded_fields=["updated_at"])

    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_evaluations",
    )
    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    judgement_evidence = models.TextField(blank=True, default="")
    to_progress = models.TextField(blank=True, default="")
    # In-depth-review grade over-write audit trail. When a leader pushes the
    # grade derived from the in-depth review onto the dashboard, `rating` becomes
    # the grade of record and the prior value is kept in `system_rating`.
    rating_overridden = models.BooleanField(default=False)
    system_rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    overridden_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="overridden_evaluations",
    )
    overridden_at = models.DateTimeField(null=True, blank=True)
    override_reason = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "period", "category"],
                name="unique_evaluation_per_school_period_category",
            )
        ]

    def __str__(self):
        return f"{self.school} - {self.period} - {self.category}"


class Branding(models.Model):
    trust_emblem = models.ImageField(upload_to="branding/", blank=True, null=True)

    class Meta:
        # A pk=1 singleton, same as RiskSettings -- there is never more than
        # one, so the plural stays singular rather than reading "Brandings".
        verbose_name = "Branding"
        verbose_name_plural = "Branding"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return "Branding"


class InDepthArea(models.Model):
    name = models.CharField(max_length=200, unique=True)
    order = models.PositiveIntegerField(default=0)
    is_safeguarding = models.BooleanField(default=False)
    purpose = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "In-depth area"
        verbose_name_plural = "In-depth areas"
        ordering = ("order", "name")

    def __str__(self):
        return self.name


class InDepthSubSection(models.Model):
    # DEPRECATED — replaced by InDepthStandard / InDepthJudgementArea. Kept only
    # so prior-year subsection-based reviews stay viewable. Remove once the new
    # flow is validated through a full review cycle (see load_indepth_blueprint).
    area = models.ForeignKey(InDepthArea, on_delete=models.CASCADE, related_name="subsections")
    name = models.CharField(max_length=200)
    overview = models.TextField(blank=True, default="")
    evidence_criteria = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField(default=0)
    # Grade descriptors — standard 5-tier areas
    urgent_improvement_descriptor = models.TextField(blank=True, default="")
    needs_attention_descriptor = models.TextField(blank=True, default="")
    expected_descriptor = models.TextField(blank=True, default="")
    strong_descriptor = models.TextField(blank=True, default="")
    exceptional_descriptor = models.TextField(blank=True, default="")
    # Grade descriptors — safeguarding binary scale
    not_met_descriptor = models.TextField(blank=True, default="")
    met_descriptor = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "In-depth sub-section"
        verbose_name_plural = "In-depth sub-sections"
        ordering = ("area__order", "area__name", "order")
        constraints = [
            models.UniqueConstraint(
                fields=["area", "name"],
                name="unique_indepth_subsection_per_area",
            )
        ]

    def __str__(self):
        return f"{self.area} — {self.name}"


class InDepthReview(models.Model):
    class Step(models.TextChoices):
        REVIEW = "review", "Review"
        REFLECTION = "reflection", "Reflection"

    # Stored as academic year start, displayed as YYYY/YYYY+1
    year = models.PositiveSmallIntegerField(default=current_academic_year_start)
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    area = models.ForeignKey(InDepthArea, on_delete=models.CASCADE)
    step = models.CharField(max_length=20, choices=Step.choices, default=Step.REVIEW)
    overall_grade = models.CharField(max_length=25, blank=True, default="")
    qa_reflection = models.TextField(blank=True, default="")
    # Free-text comment captured on the commentary page when the grade is Needs
    # Attention, in response to "in addition, does one or more of the following
    # (Needs Attention statements) apply?".
    needs_attention_comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Version trail. The auto_now stamp is excluded: it changes on every save and
    # would make each history row unique for no gain, and history_date records the
    # same fact. created_at is auto_now_add, so it is constant and worth keeping.
    history = HistoricalRecords(excluded_fields=["updated_at"])

    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_indepth_reviews",
    )

    class Meta:
        verbose_name = "In-depth review"
        verbose_name_plural = "In-depth reviews"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "year", "area"],
                name="unique_indepth_review_per_school_year_area",
            )
        ]
        ordering = ("-year", "school__name", "area__order", "area__name")

    def __str__(self):
        return f"{self.school} - {self.year}/{self.year + 1} - {self.area}"


class InDepthResponse(models.Model):
    class Grade(models.TextChoices):
        # Safeguarding binary scale
        NOT_MET = "not_met", "Not Met"
        MET = "met", "Met"
        # Standard 5-tier scale
        URGENT_IMPROVEMENT = "urgent_improvement", "Urgent Improvement"
        NEEDS_ATTENTION = "needs_attention", "Needs Attention"
        EXPECTED_STANDARD = "expected_standard", "Expected Standard"
        STRONG_STANDARD = "strong_standard", "Strong Standard"
        EXCEPTIONAL = "exceptional", "Exceptional"

    class Rag(models.TextChoices):
        RED = "red", "Red"
        AMBER = "amber", "Amber"
        GREEN = "green", "Green"

    review = models.ForeignKey(InDepthReview, on_delete=models.CASCADE)
    # Legacy link — kept for prior-year reviews built on the subsection model.
    subsection = models.ForeignKey(
        InDepthSubSection,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    # New-structure link: a response now attaches to a single judgement area.
    judgement_area = models.ForeignKey(
        "InDepthJudgementArea",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="responses",
    )
    evidence_text = models.TextField(blank=True, default="")
    # Area-level grade is recorded on InDepthReview.overall_grade; this column is
    # retained for legacy subsection responses and left blank in the new flow.
    grade = models.CharField(max_length=25, choices=Grade.choices, blank=True, default="")
    # Per-judgement-area self-rating in the new flow.
    rag = models.CharField(max_length=10, choices=Rag.choices, blank=True, default="")
    next_steps = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    # Version trail. The auto_now stamp is excluded: it changes on every save and
    # would make each history row unique for no gain, and history_date records the
    # same fact. created_at is auto_now_add, so it is constant and worth keeping.
    history = HistoricalRecords(excluded_fields=["updated_at"])


    class Meta:
        verbose_name = "In-depth response"
        verbose_name_plural = "In-depth responses"
        constraints = [
            models.UniqueConstraint(
                fields=["review", "subsection"],
                name="unique_indepth_response_per_review_subsection",
            ),
            models.UniqueConstraint(
                fields=["review", "judgement_area"],
                name="unique_indepth_response_per_review_judgement_area",
            ),
        ]
        ordering = ("id",)

    def __str__(self):
        return f"{self.review} — {self.judgement_area or self.subsection}"


# ---------------------------------------------------------------------------
# New criteria structure (Nov 2025 framework drafts)
#
# Unlike InDepthSubSection (one row carrying a descriptor per grade), the new
# Ofsted draft criteria define a *different* set of judgement areas for each
# grade band. These models capture that: Area -> Standard (grade band) ->
# JudgementArea (statement + key questions + suggested evidence + sources).
# They are additive; the legacy InDepthSubSection models are left intact so
# existing review screens keep working until the UI is migrated over.
# Loaded by:  python manage.py load_indepth_criteria
# ---------------------------------------------------------------------------
class InDepthStandard(models.Model):
    """A grade band within an area, carrying its own judgement areas."""

    class Key(models.TextChoices):
        URGENT_IMPROVEMENT = "urgent_improvement", "Urgent Improvement"
        NEEDS_ATTENTION = "needs_attention", "Needs Attention"
        EXPECTED_STANDARD = "expected_standard", "Expected Standard"
        STRONG_STANDARD = "strong_standard", "Strong Standard"
        EXCEPTIONAL = "exceptional", "Exceptional"
        MET = "met", "Met"
        NOT_MET = "not_met", "Not Met"

    area = models.ForeignKey(
        InDepthArea, on_delete=models.CASCADE, related_name="standards"
    )
    key = models.CharField(max_length=25, choices=Key.choices)
    focus = models.TextField(blank=True, default="")
    # Sheet-level usage guidance (mainly for the flat lists: Urgent Improvement,
    # Needs Attention, Exceptional, Not Met).
    usage_notes = models.JSONField(default=list, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "In-depth standard"
        verbose_name_plural = "In-depth standards"
        ordering = ("area__order", "order")
        constraints = [
            models.UniqueConstraint(
                fields=["area", "key"],
                name="unique_indepth_standard_per_area",
            )
        ]

    def __str__(self):
        return f"{self.area} — {self.get_key_display()}"


class InDepthJudgementArea(models.Model):
    """A single judgement area / statement within a standard."""

    standard = models.ForeignKey(
        InDepthStandard, on_delete=models.CASCADE, related_name="judgement_areas"
    )
    statement = models.TextField()
    key_questions = models.JSONField(default=list, blank=True)
    suggested_evidence = models.JSONField(default=list, blank=True)
    # Leadership & Governance carries an extra "How do we know this?" column;
    # empty for tools without it.
    how_we_know = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)
    # Worked "Example" commentary/next-steps from the rich sheets (Expected/
    # Strong), present on some judgement areas. Displayed as an in-app exemplar.
    example_commentary = models.TextField(blank=True, default="")
    example_next_steps = models.TextField(blank=True, default="")
    # True for the flat trigger/example lists (Urgent Improvement, Needs
    # Attention, Exceptional, Not Met), where each row is a single statement
    # with no key questions / evidence / sources.
    is_flat = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "In-depth judgement area"
        verbose_name_plural = "In-depth judgement areas"
        ordering = ("standard", "order")

    def __str__(self):
        return f"{self.standard} — {self.statement[:60]}"


# ---------------------------------------------------------------------------
# Risk register (TFORS/OSED risk proposal v7, Aug 2026)
#
# TrustCategory is the shared 14-value list used by the Risk tab and (in phase
# two) the Operations & Resources tab: the nine OSED evaluation areas, which
# route to SIV, plus the five Operations & Resources domains, which route to
# TFORS. It is deliberately NOT the existing `Category` model — that is the
# eight dashboard evaluation categories and means something different.
#
# The nine evaluation-area rows reference InDepthArea rather than copying its
# name, so renaming an area cannot silently fork the list.
# Seeded by:  python manage.py seed_trust_categories
# ---------------------------------------------------------------------------
class TrustCategory(models.Model):
    class Group(models.TextChoices):
        EVALUATION_AREA = "evaluation_area", "OSED evaluation area"
        OPERATIONS_DOMAIN = "operations_domain", "Operations & Resources domain"

    class Route(models.TextChoices):
        SIV = "SIV", "SIV"
        TFORS = "TFORS", "TFORS"

    group = models.CharField(max_length=20, choices=Group.choices)
    # Set for evaluation areas only; the display name is taken from the area.
    indepth_area = models.OneToOneField(
        InDepthArea,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="trust_category",
    )
    # Set for Operations & Resources domains only.
    domain_key = models.SlugField(max_length=50, blank=True, default="")
    domain_name = models.CharField(max_length=100, blank=True, default="")
    # Stored rather than derived from `group` so the Trust can move a category
    # between meetings in the admin without a deploy.
    routes_to = models.CharField(max_length=10, choices=Route.choices)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "Trust category"
        verbose_name_plural = "Trust categories"

    @property
    def name(self) -> str:
        if self.indepth_area_id:
            return self.indepth_area.name
        return self.domain_name

    def __str__(self):
        return self.name


class RiskSettings(models.Model):
    """Trust-wide risk configuration. Singleton, same pattern as Branding.

    The escalation threshold lives here rather than in code because the client
    expects to revisit it once there is real data — switching persisting Amber
    on must not require a deploy.
    """

    # Band keys (see review/risk.py) that escalate to the Finance, Audit and
    # Risk Committee. The agreed starting rule is Red only, i.e. ["critical"].
    escalate_bands = models.JSONField(default=list, blank=True)
    escalate_persisting_amber = models.BooleanField(
        default=False,
        help_text=(
            "Also escalate a risk that has stayed at Amber across terms. Off by "
            "agreement — the starting rule is Red only."
        ),
    )

    class Meta:
        verbose_name = "Risk settings"
        verbose_name_plural = "Risk settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "RiskSettings":
        obj, _ = cls.objects.get_or_create(
            pk=1, defaults={"escalate_bands": ["critical"]}
        )
        return obj

    def __str__(self):
        return "Risk settings"


class Risk(models.Model):
    """A long-lived risk. Not a termly form entry.

    A risk stays open and visible across terms until someone actively closes it
    with a reason. Its rating is recorded per term on RiskRating, which is what
    makes worsening/persisting/improving computable rather than judged.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="risks")
    category = models.ForeignKey(
        TrustCategory, on_delete=models.PROTECT, related_name="risks"
    )
    title = models.CharField(max_length=255)
    mitigation = models.TextField(blank=True, default="")
    # Free-text role label, as the register does today ("COO", "Site Manager").
    owner = models.CharField(max_length=100, blank=True, default="")
    # The term the risk is next looked at ("Aut 2", "Spring 1"). Free text
    # because the register works in half-terms, which ReviewPeriod does not model.
    review_point = models.CharField(max_length=30, blank=True, default="")

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN
    )
    opened_period = models.ForeignKey(
        ReviewPeriod,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="risks_opened",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="closed_risks",
    )
    # Required to close — the Committee needs an audit trail rather than risks
    # quietly vanishing off the register.
    close_reason = models.TextField(blank=True, default="")
    # Closing goes through the same CFO QA as opening.
    close_qa_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qa_closed_risks",
    )
    close_qa_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_risks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Version trail. The auto_now stamp is excluded: it changes on every save and
    # would make each history row unique for no gain, and history_date records the
    # same fact. created_at is auto_now_add, so it is constant and worth keeping.
    history = HistoricalRecords(excluded_fields=["updated_at"])


    class Meta:
        ordering = ("status", "-created_at")
        permissions = [("qa_risk", "Can QA risk register entries")]

    @property
    def route(self) -> str:
        """TFORS or SIV — always derived from the category, never entered."""
        return self.category.routes_to

    @property
    def is_closed(self) -> bool:
        return self.status == self.Status.CLOSED

    @property
    def close_awaiting_qa(self) -> bool:
        return self.is_closed and self.close_qa_at is None

    def __str__(self):
        return f"{self.school} — {self.title[:60]}"


class RiskRating(models.Model):
    """One term's rating of a risk. The full history is kept."""

    risk = models.ForeignKey(Risk, on_delete=models.CASCADE, related_name="ratings")
    period = models.ForeignKey(
        ReviewPeriod, on_delete=models.CASCADE, related_name="risk_ratings"
    )
    impact = models.CharField(max_length=10, choices=IMPACT_CHOICES)
    likelihood = models.CharField(max_length=20, choices=LIKELIHOOD_CHOICES)
    # Cached for querying only — recomputed from the matrix on every save and
    # never editable by hand.
    band = models.CharField(max_length=20, choices=BAND_CHOICES, blank=True, default="")
    note = models.TextField(blank=True, default="")

    recorded_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recorded_risk_ratings",
    )
    recorded_at = models.DateTimeField(auto_now=True)
    # CFO sign-off, before the meeting.
    qa_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qa_risk_ratings",
    )
    qa_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-period__year", "-period__round")
        constraints = [
            models.UniqueConstraint(
                fields=["risk", "period"],
                name="unique_risk_rating_per_period",
            )
        ]

    def save(self, *args, **kwargs):
        self.band = band_for(self.impact, self.likelihood)
        super().save(*args, **kwargs)

    @property
    def rag(self) -> str:
        return rag_for_band(self.band) if self.band else ""

    @property
    def awaiting_qa(self) -> bool:
        return self.qa_at is None

    def __str__(self):
        return f"{self.risk} — {self.period} — {self.get_band_display()}"

# ---------------------------------------------------------------------------
# Operations & Resources (TFORS/OSED risk proposal v7, Aug 2026) — phase two
#
# Metrics are records, not hard-coded fields: the bands will change, and the
# client changed one before the document reached us. Every metric is behind a
# per-school, per-year visibility switch that defaults to OFF, because this is
# shipping as a pilot.
#
# There is deliberately NO ownership field. Principal-owned / Trust-owned was
# dropped by the client: who acts on an amber or red is agreed jointly in the
# room at TFORS or SIV, and a static tag would pre-decide it.
#
# Seeded by:  python manage.py seed_operations_metrics
# ---------------------------------------------------------------------------
class OperationsMetric(models.Model):
    class Evidence(models.TextChoices):
        BENCHMARKED = "benchmarked", "Hard-benchmarked"
        JUDGEMENT = "judgement", "Judgement-based"

    class Cycle(models.TextChoices):
        TERMLY = "termly", "Termly"
        ANNUAL = "annual", "Annual"

    domain = models.ForeignKey(
        TrustCategory,
        on_delete=models.PROTECT,
        related_name="operations_metrics",
        limit_choices_to={"group": TrustCategory.Group.OPERATIONS_DOMAIN},
    )
    key = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=200)
    benchmark_source = models.TextField(blank=True, default="")
    rule = models.CharField(max_length=30, choices=RULE_CHOICES)
    # Nobody should read a judgement tile with the confidence of a benchmarked
    # one, so this is shown on the tile.
    evidence = models.CharField(
        max_length=20, choices=Evidence.choices, default=Evidence.JUDGEMENT
    )
    # Condition Data Collection and the DfE Digital Standards are annual by
    # nature; an annual metric is not chased for an entry every term.
    cycle = models.CharField(max_length=10, choices=Cycle.choices, default=Cycle.TERMLY)
    value_label = models.CharField(max_length=100, blank=True, default="")
    help_text = models.TextField(blank=True, default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("domain__order", "order", "id")
        verbose_name = "Operations metric"

    @property
    def is_computed(self) -> bool:
        return self.rule in COMPUTED_RULES

    @property
    def is_numeric(self) -> bool:
        return self.rule in NUMERIC_RULES

    def band_for_phase(self, phase: str):
        """The band for a school's phase, falling back to the all-phases band.

        Returns None when no band covers the phase — which is how Primary ICFP
        stays Blue rather than quietly borrowing the secondary thresholds.
        """
        bands = list(self.bands.all())
        for band in bands:
            if band.phase == phase:
                return band
        for band in bands:
            if band.phase == "":
                return band
        return None

    def __str__(self):
        return self.name


class OperationsMetricBand(models.Model):
    """The thresholds for one metric, optionally per phase.

    Phase-awareness is built in from the start rather than special-cased later:
    the staff-costs band is a secondary illustration and must not be applied to
    primaries. A metric with no band for a school's phase evaluates to Blue.
    """

    metric = models.ForeignKey(
        OperationsMetric, on_delete=models.CASCADE, related_name="bands"
    )
    # "" means the band applies to every phase.
    phase = models.CharField(
        max_length=20, choices=School.Phase.choices, blank=True, default=""
    )

    green_descriptor = models.TextField(blank=True, default="")
    amber_descriptor = models.TextField(blank=True, default="")
    red_descriptor = models.TextField(blank=True, default="")

    green_min = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    green_max = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    amber_min = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    amber_max = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    # Percentage or percentage-point tolerance for the comparator rules.
    amber_tolerance = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )

    # National comparators are refreshed on external cycles — DfE workforce
    # figures annually, ISBL/ASOT thresholds twice yearly. The year is stored and
    # shown on the tile so a RAG computed against a stale figure is visible
    # rather than silent.
    comparator_value = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    comparator_year = models.CharField(max_length=20, blank=True, default="")
    comparator_source = models.CharField(max_length=200, blank=True, default="")

    # Complaints only: what counts as "a marked step-change in a single term".
    # Not defined in the source document — held here so it can be corrected
    # without a deploy.
    step_change = models.PositiveSmallIntegerField(default=3)

    class Meta:
        ordering = ("metric__order", "phase")
        constraints = [
            models.UniqueConstraint(
                fields=["metric", "phase"],
                name="unique_operations_band_per_metric_phase",
            )
        ]

    def __str__(self):
        return f"{self.metric} — {self.get_phase_display() or 'All phases'}"


class OperationsMetricVisibility(models.Model):
    """Per-school, per-year pilot switch. Absent or False means hidden.

    Hidden means *absent*: no tile, no grey placeholder, no contribution to a
    domain header count, and no domain card at all if everything under it is
    hidden. Hidden metrics are also excluded from any roll-up denominator, so a
    school piloting two domains never looks healthier than one running five.
    """

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="operations_visibility"
    )
    # Academic year start, as elsewhere in the app.
    year = models.PositiveSmallIntegerField(default=current_academic_year_start)
    metric = models.ForeignKey(
        OperationsMetric, on_delete=models.CASCADE, related_name="visibility"
    )
    # Default off: a metric nobody was told about appearing on a Principal's
    # page mid-term is worse than one missing.
    is_visible = models.BooleanField(default=False)

    class Meta:
        ordering = ("school__name", "-year", "metric__order")
        verbose_name_plural = "Operations metric visibility"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "year", "metric"],
                name="unique_operations_visibility",
            )
        ]

    def __str__(self):
        state = "visible" if self.is_visible else "hidden"
        return f"{self.school} {self.year}/{self.year + 1} — {self.metric} ({state})"


class OperationsEntry(models.Model):
    """One school's figure for one metric in one term.

    The entry path is kept separable from storage: `source` records whether a
    human or an importer wrote the row, so adding an IMP/FBIT feed later is a
    new writer rather than a rewrite.
    """

    class Source(models.TextChoices):
        MANUAL = "manual", "Entered by hand"
        IMPORT = "import", "Imported from a feed"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="operations_entries")
    period = models.ForeignKey(ReviewPeriod, on_delete=models.CASCADE, related_name="operations_entries")
    metric = models.ForeignKey(OperationsMetric, on_delete=models.CASCADE, related_name="entries")

    value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # For metrics where the Principal picks which band statement applies.
    band_choice = models.CharField(max_length=10, choices=RAG_CHOICES, blank=True, default="")
    commentary = models.TextField(blank=True, default="")
    # Red triggers that no single figure can express, e.g. "a core-subject
    # vacancy unfilled a full term". Setting a reason forces Red.
    manual_red_reason = models.TextField(blank=True, default="")

    # Complaints only: a short note shown next to the trend colour, from an
    # admin-editable list so themes stay comparable across schools.
    theme = models.ForeignKey(
        "ComplaintTheme",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="entries",
    )

    # Cached for querying; recomputed on every save for entered metrics.
    rag = models.CharField(max_length=10, choices=RAG_CHOICES, blank=True, default="")
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    recorded_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="operations_entries"
    )
    recorded_at = models.DateTimeField(auto_now=True)
    # Version trail. The auto_now stamp is excluded: it changes on every save and
    # would make each history row unique for no gain, and history_date records the
    # same fact. created_at is auto_now_add, so it is constant and worth keeping.
    history = HistoricalRecords(excluded_fields=["recorded_at"])


    class Meta:
        ordering = ("-period__year", "-period__round", "metric__order")
        verbose_name_plural = "Operations entries"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "period", "metric"],
                name="unique_operations_entry",
            )
        ]

    def save(self, *args, **kwargs):
        if self.metric_id and not self.metric.is_computed:
            band = self.metric.band_for_phase(self.school.phase)
            self.rag = rag_for_entry(self.metric, self, band)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.school} — {self.period} — {self.metric}"


class ComplaintTheme(models.Model):
    """Admin-editable list. The client has not yet agreed a theme taxonomy, so
    this is neither a hard-coded enum nor free text that cannot be compared."""

    name = models.CharField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("order", "name")

    def __str__(self):
        return self.name


class StatutoryComplianceItem(models.Model):
    """One of the five dated statutory items, per school.

    Stored separately precisely so a reader can see *which* one is overdue; the
    compliance tile's RAG is computed from these dates, never entered.
    """

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="statutory_items"
    )
    item = models.CharField(max_length=30, choices=STATUTORY_ITEMS)
    next_due_date = models.DateField(null=True, blank=True)
    action_plan_in_place = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("school__name", "item")
        constraints = [
            models.UniqueConstraint(
                fields=["school", "item"], name="unique_statutory_item_per_school"
            )
        ]

    @property
    def label(self) -> str:
        return STATUTORY_ITEM_LABELS.get(self.item, self.item)

    def __str__(self):
        return f"{self.school} — {self.label}"


class GrantPublication(models.Model):
    """Publication state for one ring-fenced grant, per school per year.

    Which grants apply is derived from the school's phase and type, not a fixed
    checklist: PE and Sport Premium is primary-only, the Inclusive Mainstream
    Fund mainstream-only.
    """

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="grant_publications"
    )
    year = models.PositiveSmallIntegerField(default=current_academic_year_start)
    grant = models.CharField(max_length=30, choices=GRANT_CHOICES)
    status = models.CharField(max_length=20, choices=GRANT_STATUS_CHOICES)
    note = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("school__name", "-year", "grant")
        constraints = [
            models.UniqueConstraint(
                fields=["school", "year", "grant"],
                name="unique_grant_publication_per_school_year",
            )
        ]

    @property
    def label(self) -> str:
        return GRANT_LABELS.get(self.grant, self.grant)

    def __str__(self):
        return f"{self.school} {self.year}/{self.year + 1} — {self.label}"


class OperationsNote(models.Model):
    """"Anything else to raise" — the place for things that do not fit.

    Deliberately plain: not RAG-rated, not rolled up, not aggregated to the
    Trust Dashboard. It persists per term so it forms a record.
    """

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="operations_notes"
    )
    period = models.ForeignKey(
        ReviewPeriod, on_delete=models.CASCADE, related_name="operations_notes"
    )
    text = models.TextField(blank=True, default="")
    updated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="operations_notes"
    )
    updated_at = models.DateTimeField(auto_now=True)
    # Version trail. The auto_now stamp is excluded: it changes on every save and
    # would make each history row unique for no gain, and history_date records the
    # same fact. created_at is auto_now_add, so it is constant and worth keeping.
    history = HistoricalRecords(excluded_fields=["updated_at"])


    class Meta:
        ordering = ("-period__year", "-period__round")
        constraints = [
            models.UniqueConstraint(
                fields=["school", "period"], name="unique_operations_note_per_term"
            )
        ]

    def __str__(self):
        return f"{self.school} — {self.period} — anything else to raise"
