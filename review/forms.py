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
    (5, "Not met"),
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
        choices=RATING_CHOICES_DEFAULT,
    )


class InDepthResponseForm(forms.Form):
    """Step 1 — Expected Standard: just Met / Not met, no free text."""

    statement_id = forms.IntegerField(widget=forms.HiddenInput)
    applies = forms.ChoiceField(
        required=False,
        choices=[
            ("1", "Met"),
            ("0", "Not met"),
        ],
        widget=forms.RadioSelect,
    )

    def clean_applies(self):
        raw = self.cleaned_data.get("applies")
        if raw in (None, "", " "):
            return None
        if str(raw) == "1":
            return True
        if str(raw) == "0":
            return False
        return None


class InDepthSecondaryForm(forms.Form):
    """Step 2 — area-level Met / Not met for Needs Attention or Strong Standard."""

    applies = forms.ChoiceField(
        required=False,
        choices=[
            ("1", "Met"),
            ("0", "Not met"),
        ],
        widget=forms.RadioSelect,
    )

    def clean_applies(self):
        raw = self.cleaned_data.get("applies")
        if raw in (None, "", " "):
            return None
        if str(raw) == "1":
            return True
        if str(raw) == "0":
            return False
        return None


class InDepthJustificationForm(forms.Form):
    """Step 3 — Justification and next steps per statement."""

    statement_id = forms.IntegerField(widget=forms.HiddenInput)
    justification = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    next_steps = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean_justification(self) -> str:
        value = self.cleaned_data.get("justification") or ""
        _validate_max_words(value)
        return value

    def clean_next_steps(self) -> str:
        value = self.cleaned_data.get("next_steps") or ""
        _validate_max_words(value)
        return value
