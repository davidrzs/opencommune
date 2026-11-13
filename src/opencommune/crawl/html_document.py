"""Decision pages kept as documents: the element named by the step's `content_selector` and the
hash of its normalised text, which tells fetch whether the page changed.

The stored bytes are always read the same way (the charset from the sidecar's content type, else
what the page declares), so the hash recorded at fetch time matches a later reading."""

from __future__ import annotations

import codecs
import hashlib
import re

from bs4 import BeautifulSoup
from bs4.element import Tag


def _charset(content_type: str | None) -> str | None:
    m = re.search(r"charset=[\"']?([\w.:-]+)", content_type or "", re.I)
    if not m:
        return None
    try:
        return codecs.lookup(m[1]).name
    except LookupError:
        return None


def page_soup(body: bytes, content_type: str | None = None) -> BeautifulSoup:
    return BeautifulSoup(body, "html.parser", from_encoding=_charset(content_type))


def content_elements(soup: BeautifulSoup, selector: str) -> list[Tag]:
    """The matched elements, outermost only: a match inside another match is already in it."""
    found = soup.select(selector)
    ids = {id(el) for el in found}
    return [el for el in found if not any(id(p) in ids for p in el.parents)]


def content_sha256(elements: list[Tag]) -> str:
    """sha256 of the elements' text with all whitespace collapsed to single spaces."""
    text = " ".join(" ".join(el.get_text(" ").split()) for el in elements)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
