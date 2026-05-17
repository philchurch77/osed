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

    def __str__(self):
        return "Branding"


class InDepthArea(models.Model):
    name = models.CharField(max_length=200, unique=True)
    order = models.PositiveIntegerField(default=0)
    needs_attention_text = models.TextField(blank=True, default="")
    strong_standard_text = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("order", "name")

    def __str__(self):
        return self.name


class InDepthStatement(models.Model):
    area = models.ForeignKey(InDepthArea, on_delete=models.CASCADE)
    statement_number = models.PositiveIntegerField()
    text = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["area", "statement_number"],
                name="unique_indepth_statement_per_area_number",
            )
        ]
        ordering = ("area__order", "area__name", "statement_number")

    def __str__(self):
        return f"{self.area} #{self.statement_number}"


class InDepthReview(models.Model):
    class Step(models.TextChoices):
        EXPECTED = "expected", "Expected Standard"
        SECONDARY = "secondary", "Secondary Standard"
        JUSTIFICATION = "justification", "Justification"

    # Stored as academic year start, displayed as YYYY/YYYY+1
    year = models.PositiveSmallIntegerField(default=current_academic_year_start)
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    area = models.ForeignKey(InDepthArea, on_delete=models.CASCADE)
    step = models.CharField(max_length=20, choices=Step.choices, default=Step.EXPECTED)
    secondary_level = models.CharField(max_length=20, blank=True, default="")
    secondary_applies = models.BooleanField(null=True, blank=True)
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
    review = models.ForeignKey(InDepthReview, on_delete=models.CASCADE)
    statement = models.ForeignKey(InDepthStatement, on_delete=models.CASCADE)
    applies = models.BooleanField(null=True, blank=True)
    justification = models.TextField(blank=True, default="")
    next_steps = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["review", "statement"],
                name="unique_indepth_response_per_review_statement",
            )
        ]
        ordering = ("statement__area__order", "statement__area__name", "statement__statement_number")

    def __str__(self):
        return f"{self.review} - {self.statement}"