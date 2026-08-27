from __future__ import annotations

import re

from django import forms
from django.core.exceptions import ValidationError

from .risk import IMPACT_CHOICES, LIKELIHOOD_CHOICES


MAX_TEXTAREA_WORDS = 300


RATING_CHOICES_DEFAULT: list[tuple[int, str]] = [
    (1, "Exceptional"),
    (2, "Strong Standard"),
    (3, "Expected Standard"),
    (4, "Needs Attention"),
    (5, "Urgent Improvement"),
]


RATING_CHOICES_SAFEGUARDING: list[tuple[int, str]] = [
    (1, "Met"),
    (5, "Not Met"),
]




def _word_count(value: str) -> int:
    if not value:
        return 0
    return len(re.findall(r"\S+", value.strip()))


def _validate_max_words(value: str, *, max_words: int = MAX_TEXTAREA_WORDS) -> None:
    count = _word_count(value)
    if count > max_words:
        raise ValidationError(
            f"Please keep to {max_words} words or fewer (currently {count})."
        )


class EvaluationEntryForm(forms.Form):
    category_id = forms.IntegerField(widget=forms.HiddenInput)
    rating = forms.TypedChoiceField(
        required=False,
        coerce=int,
        empty_value=None,
        choices=RATING_CHOICES_DEFAULT,
    )
    judgement_evidence = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "aria-label": "Commentary"}),
    )
    to_progress = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "aria-label": "Next steps"}),
    )

    def clean_judgement_evidence(self) -> str:
        value = self.cleaned_data.get("judgement_evidence") or ""
        _validate_max_words(value)
        return value

    def clean_to_progress(self) -> str:
        value = self.cleaned_data.get("to_progress") or ""
        _validate_max_words(value)
        return value


class DashboardRatingForm(forms.Form):
    category_id = forms.IntegerField(widget=forms.HiddenInput)
    round = forms.IntegerField(widget=forms.HiddenInput)
    rating = forms.TypedChoiceField(
        required=False,
        coerce=int,
        empty_value=None,
        choices=RATING_CHOICES_DEFAULT,
    )


SAFEGUARDING_GRADE_CHOICES = [
    ("", ""),
    ("not_met", "Not Met"),
    ("met", "Met"),
]

STANDARD_GRADE_CHOICES = [
    ("", ""),
    ("urgent_improvement", "Urgent Improvement"),
    ("needs_attention", "Needs Attention"),
    ("expected_standard", "Expected Standard"),
    ("strong_standard", "Strong Standard"),
    ("exceptional", "Exceptional"),
]

MAX_NEXT_STEPS_WORDS = 150


# ── New-structure (Nov 2025) in-depth review ──────────────────────────────────

RAG_CHOICES = [
    ("red", "Red"),
    ("amber", "Amber"),
    ("green", "Green"),
]

# Per the Guidance sheet, commentary should be kept to 150 words or fewer.
MAX_COMMENTARY_WORDS = 150


class InDepthJudgementAreaForm(forms.Form):
    """One judgement-area response: RAG rating, commentary, and next steps."""

    judgement_area_id = forms.IntegerField(widget=forms.HiddenInput)
    rag = forms.ChoiceField(
        required=False,
        choices=RAG_CHOICES,
        widget=forms.RadioSelect,
    )
    commentary = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "data-max-words": str(MAX_COMMENTARY_WORDS)}),
    )
    next_steps = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "data-max-words": str(MAX_NEXT_STEPS_WORDS)}),
    )

    def clean_commentary(self) -> str:
        value = self.cleaned_data.get("commentary") or ""
        _validate_max_words(value, max_words=MAX_COMMENTARY_WORDS)
        return value

    def clean_next_steps(self) -> str:
        value = self.cleaned_data.get("next_steps") or ""
        _validate_max_words(value, max_words=MAX_NEXT_STEPS_WORDS)
        return value


# ── Risk register ─────────────────────────────────────────────────────────────

MAX_MITIGATION_WORDS = 150
MAX_CLOSE_REASON_WORDS = 150


class RiskEntryForm(forms.Form):
    """Log a new risk, or edit an open one.

    Route (TFORS/SIV) is deliberately absent: it is derived from the category.
    """

    risk_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    title = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Perimeter fencing damaged, site security compromised"}),
    )
    category = forms.ModelChoiceField(queryset=None, empty_label=None)
    impact = forms.ChoiceField(choices=IMPACT_CHOICES)
    likelihood = forms.ChoiceField(choices=LIKELIHOOD_CHOICES)
    mitigation = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "data-max-words": str(MAX_MITIGATION_WORDS)}),
    )
    owner = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": "e.g. COO, Principal, Site Manager"}),
    )
    review_point = forms.CharField(
        required=False,
        max_length=30,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Aut 2, Spring 1"}),
    )

    def __init__(self, *args, categories=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import TrustCategory

        self.fields["category"].queryset = (
            categories if categories is not None else TrustCategory.objects.all()
        )

    def clean_mitigation(self) -> str:
        value = self.cleaned_data.get("mitigation") or ""
        _validate_max_words(value, max_words=MAX_MITIGATION_WORDS)
        return value


class RiskRatingForm(forms.Form):
    """This term's rating of an already-open risk."""

    risk_id = forms.IntegerField(widget=forms.HiddenInput)
    impact = forms.ChoiceField(required=False, choices=[("", "—")] + IMPACT_CHOICES)
    likelihood = forms.ChoiceField(required=False, choices=[("", "—")] + LIKELIHOOD_CHOICES)
    note = forms.CharField(required=False, widget=forms.TextInput())

    def clean(self):
        cleaned = super().clean()
        impact = cleaned.get("impact")
        likelihood = cleaned.get("likelihood")
        if bool(impact) != bool(likelihood):
            raise ValidationError("Set both impact and likelihood, or neither.")
        return cleaned


class RiskCloseForm(forms.Form):
    """Close a risk. The reason is required — the Committee needs the trail."""

    risk_id = forms.IntegerField(widget=forms.HiddenInput)
    close_reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "data-max-words": str(MAX_CLOSE_REASON_WORDS)}),
        error_messages={"required": "Give a reason before closing this risk."},
    )

    def clean_close_reason(self) -> str:
        value = (self.cleaned_data.get("close_reason") or "").strip()
        if not value:
            raise ValidationError("Give a reason before closing this risk.")
        _validate_max_words(value, max_words=MAX_CLOSE_REASON_WORDS)
        return value
