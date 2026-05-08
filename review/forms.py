from __future__ import annotations

import re

from django import forms
from django.core.exceptions import ValidationError


MAX_TEXTAREA_WORDS = 300


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
        choices=[
            (1, "Exceptional"),
            (2, "Strong Standard"),
            (3, "Expected Standard"),
            (4, "Needs Attention"),
            (5, "Urgent Improvement"),
        ],
    )
    judgement_evidence = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    to_progress = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
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
        choices=[
            (1, "Exceptional"),
            (2, "Strong Standard"),
            (3, "Expected Standard"),
            (4, "Needs Attention"),
            (5, "Urgent Improvement"),
        ],
    )
