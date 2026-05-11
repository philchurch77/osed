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


class InDepthResponseForm(forms.Form):
    statement_id = forms.IntegerField(widget=forms.HiddenInput)
    applies = forms.ChoiceField(
        required=False,
        choices=[
            ("1", "✓ Applies"),
            ("0", "✕ Doesn't apply"),
        ],
        widget=forms.RadioSelect,
    )
    justification = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean_applies(self):
        raw = self.cleaned_data.get("applies")
        if raw in (None, "", " "):
            return None
        # RadioSelect will provide the string value from `choices`.
        if str(raw) == "1":
            return True
        if str(raw) == "0":
            return False
        return None

    def clean_justification(self) -> str:
        value = self.cleaned_data.get("justification") or ""
        _validate_max_words(value)
        return value
