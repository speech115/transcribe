"""Lightweight language detection for transcript metadata.

The ASR engine can run without an explicit language, but it does not always
return a detected language. For the workspace standard we only need a robust
ru/en/mixed label for manifest/frontmatter.
"""

import re

CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    """Return ru, en, mixed, or auto from transcript text."""
    cyr = len(CYRILLIC_RE.findall(text or ""))
    lat = len(LATIN_RE.findall(text or ""))
    total = cyr + lat
    if total < 20:
        return "auto"
    cyr_ratio = cyr / total
    lat_ratio = lat / total
    if cyr_ratio >= 0.2 and lat_ratio >= 0.2:
        return "mixed"
    if cyr_ratio >= 0.5:
        return "ru"
    if lat_ratio >= 0.5:
        return "en"
    return "auto"
