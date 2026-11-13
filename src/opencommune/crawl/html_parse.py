"""Recover links when malformed municipal markup confuses the standard parser."""

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

_ANCHOR = re.compile(r"<a\s[^>]*\bhref\s*=", re.I)


def parse_html(html: str) -> BeautifulSoup:
    with warnings.catch_warnings():
        # sitemaps are read on purpose as markup: html_links selects their <loc> elements
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "html.parser")
    # Some Weblication pages lose their entire body after a malformed CDATA tail.
    # An early navigation anchor may survive while later document links vanish.
    # Only try recovery when the source contains more href anchors than were parsed.
    parsed_count = len(soup.find_all("a", href=True))
    raw_count = sum(1 for _ in _ANCHOR.finditer(html))
    if raw_count > parsed_count:
        recovered = BeautifulSoup(html, "lxml")
        if len(recovered.find_all("a", href=True)) > parsed_count:
            return recovered
    return soup
