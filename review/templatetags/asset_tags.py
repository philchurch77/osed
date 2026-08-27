from __future__ import annotations

from pathlib import Path

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_v(path):
    """`{% static %}` plus a cache-busting stamp that maintains itself.

    In production the manifest storage already hashes the filename, so the URL
    changes whenever the file does and this returns it untouched. Under DEBUG
    the filename is stable, so we append the file's modification time: the URL
    then changes the moment the file is edited and the browser refetches on an
    ordinary reload, instead of needing a hard refresh.

    This replaces the hand-typed `?v=20260823-1` stamps, which only worked for
    as long as someone remembered to bump them.
    """

    url = static(path)
    if not settings.DEBUG:
        return url
    found = finders.find(path)
    if isinstance(found, (list, tuple)):
        found = found[0] if found else None
    if not found:
        return url
    try:
        stamp = int(Path(found).stat().st_mtime)
    except OSError:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}v={stamp}"
