from __future__ import annotations

import re

from django import forms
from django.core.exceptions import ValidationError


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
        widget=forms.Textarea(attrs={"rows": 4, "aria-label": "Judgement evidence"}),
    )
    to_progress = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "aria-label": "To progress"}),
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

MAX_EVIDENCE_WORDS = 300
MAX_NEXT_STEPS_WORDS = 150


class InDepthSubSectionForm(forms.Form):
    """One sub-section response: evidence text, grade, and next steps."""

    subsection_id = forms.IntegerField(widget=forms.HiddenInput)
    evidence_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "data-max-words": str(MAX_EVIDENCE_WORDS)}),
    )
    grade = forms.ChoiceField(
        required=False,
        choices=STANDARD_GRADE_CHOICES,
        widget=forms.RadioSelect,
    )
    next_steps = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "data-max-words": str(MAX_NEXT_STEPS_WORDS)}),
    )

    def __init__(self, *args, is_safeguarding: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        if is_safeguarding:
            self.fields["grade"].choices = SAFEGUARDING_GRADE_CHOICES

    def clean_evidence_text(self) -> str:
        value = self.cleaned_data.get("evidence_text") or ""
        _validate_max_words(value, max_words=MAX_EVIDENCE_WORDS)
        return value

    def clean_next_steps(self) -> str:
        value = self.cleaned_data.get("next_steps") or ""
        _validate_max_words(value, max_words=MAX_NEXT_STEPS_WORDS)
        return value

    def clean_grade(self) -> str:
        value = self.cleaned_data.get("grade") or ""
        valid = {c[0] for c in SAFEGUARDING_GRADE_CHOICES + STANDARD_GRADE_CHOICES if c[0]}
        return value if value in valid else ""


class ReflectionForm(forms.Form):
    """Principal reflects on what changed as a result of QA and feedback."""

    qa_reflection = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 6, "data-max-words": "0"}),
    )
