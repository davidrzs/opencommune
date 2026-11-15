"""Redaction: page text with the personal data the privacy check found replaced by a mark.

Nothing is changed in place. The text stays as text.db holds it and the spans as privacy.db holds
them; the index build calls `redact` each time it writes fulltext.db. A new privacy run or a change
here takes effect at the next build.

Every span of a label in MARKS is replaced, whatever its score: gheim's calibrated detector has
already decided it. Spans of a label in KEPT stay as text. A name found once is replaced only where
it was found.
"""

from __future__ import annotations

from collections import Counter

# A mark is a word in full-width brackets (U+FF3B, U+FF3D), which page text does not use. The index
# keeps these brackets inside a word (fulltext.SCHEMA), so a search for "Name" does not find the
# mark for a name.
OPEN, CLOSE = "\uff3b", "\uff3d"
MARKS = {
    label: f"{OPEN}{word}{CLOSE}"
    for label, word in (
        ("private_person", "name"),
        ("private_address", "address"),
        ("private_email", "email"),
        ("secret", "secret"),
    )
}
# Dates, web pages, phone numbers and account numbers (IBAN, AHV) stay as text. Most are meeting
# dates and the commune's own pages, numbers and accounts; most "account numbers" the model finds
# are budget account codes.
KEPT = ("private_date", "private_url", "private_phone", "account_number")

RULE = (
    "Personal data found by the privacy check is replaced by a mark: "
    + ", ".join(f"{label} by {mark}" for label, mark in MARKS.items())
    + f" (full-width brackets). Kept as text: {', '.join(KEPT)}. Each span is replaced where it "
    "was found, whatever its score. Overlapping spans become one mark. A page is indexed only "
    "when the privacy check read the same text."
)


def redact(text: str, spans: list) -> tuple[str, Counter]:
    """`text` with each span [label, start, end, score] of a label in MARKS replaced, and the
    number of marks per label. A label in neither MARKS nor KEPT is an error: it needs a decision."""
    unknown = {span[0] for span in spans} - MARKS.keys() - set(KEPT)
    if unknown:
        raise ValueError(f"no rule for the labels {sorted(unknown)}")
    hidden = sorted((s for s in spans if s[0] in MARKS), key=lambda s: (s[1], -s[2]))
    parts: list[str] = []
    marks: Counter = Counter()
    at = 0
    for label, start, end, _score in hidden:
        if start < at:  # overlaps the mark before
            at = max(at, end)
            continue
        parts += [text[at:start], MARKS[label]]
        marks[label] += 1
        at = end
    parts.append(text[at:])
    return "".join(parts), marks
