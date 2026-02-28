"""Parsing helpers for the medical data ingestion pipeline.

All functions are pure (no I/O) and handle messy real-world inputs gracefully.
"""
from __future__ import annotations

import math
import re

# ---------------------------------------------------------------------------
# Lesion size parsing
# ---------------------------------------------------------------------------

def parse_lesion_sizes(value: object) -> list[float]:
    """Parse a raw cell value into a list of lesion sizes in mm.

    Handles:
    - Single number:             ``"12.5"``       → ``[12.5]``
    - Comma-separated:           ``"12.5, 14.3"`` → ``[12.5, 14.3]``
    - Semicolon-separated:       ``"12.5;14.3"``  → ``[12.5, 14.3]``
    - Whitespace-separated:      ``"12.5 14.3"``  → ``[12.5, 14.3]``
    - Numeric scalar (int/float):``12``           → ``[12.0]``
    - Empty / NaN / None:                          → ``[]``
    - Non-numeric tokens are silently skipped.

    Args:
        value: Raw cell value from a pandas DataFrame.

    Returns:
        Sorted list of floats. Empty list when no valid number is found.
    """
    # Reject None / NaN / empty
    if value is None:
        return []
    if isinstance(value, float):
        if math.isnan(value):
            return []
        return [value]
    if isinstance(value, int):
        return [float(value)]

    # Convert to string and clean up
    text = str(value).strip()
    if not text:
        return []

    # Normalise line endings first (Excel Alt+Enter cells contain \r\n or \n)
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    # Replace other common separators with spaces, then split
    normalized = re.sub(r"[,;|/\\]+", " ", text)
    tokens = normalized.split()

    sizes: list[float] = []
    for token in tokens:
        # Strip trailing units like "mm", "cm" etc.
        token_clean = re.sub(r"[a-zA-Z°]+$", "", token).strip(" .")
        if not token_clean:
            continue
        try:
            sizes.append(float(token_clean))
        except ValueError:
            pass  # skip non-numeric tokens

    return sorted(sizes)


# ---------------------------------------------------------------------------
# Report section splitting
# ---------------------------------------------------------------------------

# Ordered list of (output_key, regex_pattern) for each known section header.
# Patterns are matched case-insensitively. The dot after the marker is optional
# so "CONCLUSIONS" and "CONCLUSIONS." both work.
_SECTION_PATTERNS: list[tuple[str, str]] = [
    ("clinical_information", r"CLINICAL\s+INFORMATION\.?"),
    ("study_technique",      r"STUDY\s+TECHNIQUE\.?"),
    ("report",               r"REPORT\.?"),
    ("conclusions",          r"CONCLUSIONS?\.?"),
]

_ALL_KEYS = [k for k, _ in _SECTION_PATTERNS]
_EMPTY_SECTIONS: dict[str, str | None] = {k: None for k in _ALL_KEYS}


def split_report_sections(text: object) -> dict[str, str | None]:
    """Split a raw pseudo-report into labelled sections.

    Recognised markers (case-insensitive, trailing dot optional):
    - ``CLINICAL INFORMATION.``
    - ``STUDY TECHNIQUE.``
    - ``REPORT.``
    - ``CONCLUSIONS.``

    Args:
        text: Raw report string. ``None`` / empty string are accepted.

    Returns:
        Dict with keys ``clinical_information``, ``study_technique``,
        ``report``, ``conclusions``. Each value is ``None`` when the
        corresponding marker is absent or the section content is empty.
    """
    result = dict(_EMPTY_SECTIONS)  # fresh copy

    if not text or not isinstance(text, str):
        return result

    text = text.strip()
    if not text:
        return result

    # Locate every marker and record (position_start, position_end, key)
    found: list[tuple[int, int, str]] = []
    for key, pattern in _SECTION_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            found.append((m.start(), m.end(), key))

    if not found:
        return result

    # Sort by position of occurrence in the text
    found.sort(key=lambda x: x[0])

    # Extract content between consecutive markers
    for i, (_, end_pos, key) in enumerate(found):
        if i + 1 < len(found):
            next_start = found[i + 1][0]
            content = text[end_pos:next_start].strip()
        else:
            content = text[end_pos:].strip()

        result[key] = content if content else None

    return result
