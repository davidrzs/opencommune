"""Exact FINSTA exports from configured public report-selector options.

No network discovery or broad publisher scope: `data/linked-sources.yaml` names the
years and report choices, and the normal downloader renders exactly those municipal
selections with its usual robots, pacing and hash checks.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..html_parse import parse_html
from ..iweb import clean_url


class ReportChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    parameters: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_parameters(self):
        # These optional first-level selections export the entire chosen group;
        # deeper filters would only create overlapping subsets of its data.
        expected = (
            {"Funktionsstufe1"}
            if "Einzelauszug_Funktionsstufen" in self.name
            else {"Kontokennung"}
            if "Einzelauszug_Sachgruppen" in self.name
            else {"KPI"}
            if "KPI_HRM2" in self.name
            else set()
        )
        if set(self.parameters) != expected or any(
            not re.fullmatch(r"[0-9]+", value) for value in self.parameters.values()
        ):
            raise ValueError(
                "report requires its configured first-level selector, without overrides"
            )
        return self


class FinstaExports(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str
    folder: str = Field(pattern=r"^/[A-Za-z0-9_]+/$")
    years: list[int] = Field(min_length=1)
    reports: list[ReportChoice] = Field(min_length=1)

    @model_validator(mode="after")
    def check_manifest(self):
        parts = urlsplit(self.endpoint)
        if (
            clean_url(self.endpoint) is None
            or parts.path in {"", "/"}
            or parts.path.endswith("/")
            or parts.query
            or parts.fragment
            or "\\" in unquote(parts.path)
            or any(p in {".", ".."} for p in unquote(parts.path).split("/"))
        ):
            raise ValueError("configured native report endpoint required")
        if len(set(self.years)) != len(self.years) or any(y < 1900 or y > 9999 for y in self.years):
            raise ValueError("distinct published accounting years required")
        choices = [(r.name, tuple(sorted(r.parameters.items()))) for r in self.reports]
        if len(set(choices)) != len(choices):
            raise ValueError("duplicate report selection")
        return self

    def urls(self, bfs_id: int):
        if bfs_id <= 0:
            raise ValueError("explicit municipal BFS required")
        for year in self.years:
            for report in self.reports:
                path = quote(self.folder + report.name, safe="").replace("%2F", "%2f")
                params = {
                    "rs:Command": "Render",
                    "rs:Format": "PDF",
                    "rc:Parameters": "false",
                    "Buchjahr": str(year),
                    "Absolut_Relativ": "1",
                    "BFS_Nr": str(bfs_id),
                    **report.parameters,
                    "rs:ParameterLanguage": "de-CH",
                }
                yield self.endpoint + "?" + path + "&" + urlencode(params, safe=":")


def from_selector(html: str, endpoint: str, bfs_id: int, name: str):
    """Fail closed if configured public controls or municipal identity have changed."""
    soup = parse_html(html)

    def options(selector, *, municipal=False):
        nodes = soup.select("#" + selector)
        if len(nodes) != 1:
            raise ValueError(f"expected one published {selector} selector")
        rows = [
            (o.get("value", ""), " ".join(o.get_text(" ", strip=True).split()))
            for o in nodes[0].select("option")
            if o.get("value", "") != ""
        ]
        if not rows or (not municipal and len({value for value, _ in rows}) != len(rows)):
            raise ValueError(f"missing or duplicate {selector} options")
        return rows

    names = [
        label for value, label in options("GemeindeByName", municipal=True) if value == str(bfs_id)
    ]
    numbers = {value for value, _ in options("GemeindeByBfsNr", municipal=True)}
    if names != [name] or str(bfs_id) not in numbers:
        raise ValueError("municipality must match both published BFS and name selectors")
    # The JS publishes the viewer route; its native SSRS endpoint was configured
    # separately in the viewer's no-script link. Never accept an arbitrary host.
    routes = re.findall(r'["\'](https?://[^"\']+/Pages/ReportViewer\.aspx)\?([^"\']+)["\']', html)
    if len(routes) != 1 or routes[0][0] != endpoint + "/Pages/ReportViewer.aspx":
        raise ValueError("published viewer route differs from configured endpoint")
    folder = unquote(routes[0][1])
    years = [int(value) for value, _ in options("SelectedFinancialYear")]
    reports = []
    for report, _ in options("ReportName"):
        selector = (
            "Funktionsstufe1"
            if "Einzelauszug_Funktionsstufen" in report
            else "Kontokennung"
            if "Einzelauszug_Sachgruppen" in report
            else "KPI"
            if "KPI_HRM2" in report
            else None
        )
        for value in [v for v, _ in options(selector)] if selector else [None]:
            reports.append(
                ReportChoice(name=report, parameters={selector: value} if selector else {})
            )
    return FinstaExports(endpoint=endpoint, folder=folder, years=years, reports=reports)
