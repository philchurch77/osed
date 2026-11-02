"""Possible spelling mistakes in saved in-depth write-ups.

The client asked (Sept 2026) whether users could be prompted about spelling
before saving. The browser's red underlines cannot be read from JavaScript, so
OSED runs its own check instead: after a save, against a British English word
list (review/data/en_GB_words.txt) plus a Trust allow-list
(review/data/spelling_allow.txt). It only ever produces a warning message. It
never blocks a save and never changes what was typed.

To keep school and place names from being flagged, a word is skipped when it
is written in capitals (EHCP), contains a digit (KS2), or is capitalised
somewhere other than the start of a sentence (Mendlesham, Designated
Safeguarding Lead).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data"
_WORD_FILES = ("en_GB_words.txt", "spelling_allow.txt")

_TOKEN = re.compile(r"[\w'’]+")
# Characters that end a sentence or start a new line/bullet: the next word may
# be capitalised without being a name.
_SENTENCE_BREAK = set(".!?:;\n\r•*-–—")
_OPENERS = " \t\"'“‘(["

# Keep the message readable on a long page.
MAX_WORDS_PER_LABEL = 8


@lru_cache(maxsize=1)
def _dictionary() -> frozenset[str]:
    words = set()
    for name in _WORD_FILES:
        with open(_DATA / name, encoding="utf-8") as fh:
            for line in fh:
                word = line.strip()
                if word and not word.startswith("#"):
                    words.add(word.casefold())
    return frozenset(words)


def _at_sentence_start(text: str, index: int) -> bool:
    prefix = text[:index].rstrip(_OPENERS)
    return not prefix or prefix[-1] in _SENTENCE_BREAK


def _is_known(word: str, known: frozenset[str]) -> bool:
    folded = word.casefold()
    if folded in known:
        return True
    # Possessives: "pupil's", "pupils'" (the trailing apostrophe is stripped
    # before this is called).
    return folded.endswith("'s") and folded[:-2] in known


def possible_misspellings(text: str) -> list[str]:
    """Words not in the dictionary, deduplicated, in order of first appearance."""
    known = _dictionary()
    found: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN.finditer(text or ""):
        word = match.group().replace("’", "'").strip("'")
        if len(word) < 2 or "_" in word or any(ch.isdigit() for ch in word):
            continue
        if any(ch.isupper() for ch in word[1:]):
            continue  # EHCP, CPOMs, McDonald
        if word[0].isupper() and not _at_sentence_start(text, match.start()):
            continue  # a name, mid-sentence
        if _is_known(word, known):
            continue
        folded = word.casefold()
        if folded not in seen:
            seen.add(folded)
            found.append(word)
    return found


def indepth_texts(forms, judgement_areas, needs_attention_comment=None):
    """(label, text) pairs for a saved in-depth commentary page.

    `forms` are valid InDepthJudgementAreaForms; `judgement_areas` maps id to
    the statements that were saved (anything else was skipped by the save).
    """
    for form in forms:
        ja = judgement_areas.get(form.cleaned_data.get("judgement_area_id"))
        if ja is None:
            continue
        yield f"{ja.label} commentary", form.cleaned_data["commentary"]
        yield f"{ja.label} next steps", form.cleaned_data["next_steps"]
    if needs_attention_comment is not None:
        yield "Needs Attention comment", needs_attention_comment


def spelling_warning(labelled_texts) -> str:
    """One warning message for a save, or "" when nothing looks misspelt.

    `labelled_texts` is an iterable of (label, text) pairs, e.g.
    ("Met 3", commentary). Texts sharing a label are reported together.
    """
    by_label: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for label, text in labelled_texts:
        words = by_label.setdefault(label, [])
        folded_seen = seen.setdefault(label, set())
        for word in possible_misspellings(text):
            folded = word.casefold()
            if folded not in folded_seen:
                folded_seen.add(folded)
                words.append(word)
    parts = []
    for label, words in by_label.items():
        if not words:
            continue
        shown = ", ".join(words[:MAX_WORDS_PER_LABEL])
        extra = len(words) - MAX_WORDS_PER_LABEL
        if extra > 0:
            shown += f" and {extra} more"
        parts.append(f"{label}: {shown}")
    if not parts:
        return ""
    return (
        "Your work is saved. Possible spelling mistakes — "
        + "; ".join(parts)
        + ". Correct any that are wrong and save again."
    )
