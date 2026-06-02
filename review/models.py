from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone


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
    logo = models.ImageField(upload_to="school_logos/", blank=True, null=True)

    def __str__(self):
        return self.name

class Category(models.Model):
    name = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

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


class ReviewPeriod(models.Model):
    class Round(models.IntegerChoices):
        ROUND_1 = 1, "Round 1"
        ROUND_2 = 2, "Round 2"
        ROUND_3 = 3, "Round 3"

    # Stored as academic year start, displayed as YYYY/YYYY+1
    year = models.PositiveSmallIntegerField(default=current_academic_year_start)
    round = models.PositiveSmallIntegerField(choices=Round.choices, default=Round.ROUND_1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round"],
                name="unique_review_period_year_round",
            )
        ]
        ordering = ("-year", "round")

    def __str__(self):
        return f"{self.year}/{self.year + 1} - Round {self.round}"


class Evaluation(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    period = models.ForeignKey(ReviewPeriod, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
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
        ordering = ("order", "name")

    def __str__(self):
        return self.name


class InDepthSubSection(models.Model):
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_indepth_reviews",
    )

    class Meta:
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

    review = models.ForeignKey(InDepthReview, on_delete=models.CASCADE)
    subsection = models.ForeignKey(
        InDepthSubSection,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    evidence_text = models.TextField(blank=True, default="")
    grade = models.CharField(max_length=25, choices=Grade.choices, blank=True, default="")
    next_steps = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["review", "subsection"],
                name="unique_indepth_response_per_review_subsection",
            )
        ]
        ordering = ("subsection__area__order", "subsection__order")

    def __str__(self):
        return f"{self.review} — {self.subsection}"