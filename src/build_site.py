from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from fasthtml.common import (
    A,
    Body,
    Div,
    Footer,
    Head,
    H2,
    H3,
    H4,
    Html,
    Li,
    Link,
    Main,
    Meta,
    P,
    Script,
    Section,
    Span,
    Strong,
    Title,
    Ul,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "neural_recording_papers.csv"
PUBLIC_DIR = BASE_DIR / "public"
ASSETS_DIR = PUBLIC_DIR / "assets"
MONTH_NAMES = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
DEFAULT_MONTH = 7
FIT_RANGE_PADDING_YEARS = 5
MAX_FUTURE_YEARS = 20
X_RANGE_MAX = 2040
BIO_REFERENCES = [
    {"label": "Fruit fly brain (~1.5e5)", "neurons": 150_000},
    {"label": "Mouse cortex (~1.4e7)", "neurons": 14_000_000},
    {"label": "Mouse brain (~7.1e7)", "neurons": 71_000_000},
]
MAX_REFERENCE_NEURONS = max(ref["neurons"] for ref in BIO_REFERENCES)


@dataclass
class RegressionResult:
    label: str
    slope: float
    intercept: float
    doubling_time_years: float | None
    series: list[dict[str, float]]


def _decimal_year(year: int, month: int | float | None) -> float:
    month = month if isinstance(month, (int, float)) and not math.isnan(month) else DEFAULT_MONTH
    return float(year) + (float(month) - 0.5) / 12.0


def _format_date(year: int, month: int | float | None) -> str:
    month_idx = int(month) if isinstance(month, (int, float)) and not math.isnan(month) else DEFAULT_MONTH
    month_idx = max(1, min(12, month_idx))
    return f"{MONTH_NAMES[month_idx - 1]} {int(year)}"


def _short_label(label: str) -> str:
    return label.split("(")[0].strip()


def _row_to_point(row: pd.Series) -> dict:
    method_note = row.get("Method Note")
    method_value = row.get("Method")
    method_value = method_value if isinstance(method_value, str) and method_value.strip() else "Unknown"
    return {
        "id": int(row["id"]),
        "year": int(row["Year"]),
        "month": int(row["Month"]),
        "dateLabel": _format_date(int(row["Year"]), int(row["Month"])),
        "decimalYear": float(row["decimal_year"]),
        "neurons": float(row["Neurons"]),
        "authors": row["Authors"],
        "method": method_value,
        "source": row["Source"],
        "publication": row["Publication"],
        "methodNote": method_note if isinstance(method_note, str) else "",
        "doi": row["DOI"],
    }


def _fit_regression(df: pd.DataFrame, label: str, x_range: tuple[float, float]) -> RegressionResult:
    xs = df["decimal_year"].to_numpy()
    ys = df["Neurons"].to_numpy()
    mask = ys > 0
    xs = xs[mask]
    ys = ys[mask]
    log_y = np.log(ys)
    slope, intercept = np.polyfit(xs, log_y, 1)
    doubling = math.log(2) / slope if slope > 0 else None
    line_xs = np.linspace(x_range[0], x_range[1], 200)
    series = [
        {"decimalYear": float(x), "neurons": float(math.exp(intercept + slope * x))}
        for x in line_xs
    ]
    return RegressionResult(label=label, slope=slope, intercept=intercept, doubling_time_years=doubling, series=series)


def _year_for_target(reg: RegressionResult, target: float) -> float | None:
    if reg.slope <= 0 or target <= 0:
        return None
    return (math.log(target) - reg.intercept) / reg.slope


def _reference_hits(reg: RegressionResult) -> list[dict[str, float]]:
    hits = []
    for ref in BIO_REFERENCES:
        estimate = _year_for_target(reg, ref["neurons"])
        if estimate is None:
            continue
        hits.append({"label": ref["label"], "year": estimate})
    return hits


def _render(document: Iterable) -> str:
    return "".join(str(node) for node in document)


def build_site() -> Path:
    df = pd.read_csv(DATA_PATH)
    df = df[df["Neurons"].notna()].copy()
    df["Month"] = df["Month"].fillna(DEFAULT_MONTH).astype(int)
    df["decimal_year"] = df.apply(lambda r: _decimal_year(int(r["Year"]), r["Month"]), axis=1)
    df["id"] = range(len(df))

    points = [_row_to_point(row) for _, row in df.iterrows()]

    min_year = float(df["decimal_year"].min())
    max_year = float(df["decimal_year"].max())
    frontier = (
        df.sort_values(["Year", "Neurons"], ascending=[True, True])
        .groupby("Year", as_index=False)
        .tail(1)
    )
    methods = sorted(df["Method"].fillna("Unknown").unique().tolist())

    def compute_regressions(range_end: float):
        current_range = (min_year, range_end)
        reg_all = _fit_regression(df, "All datapoints", current_range)
        reg_frontier = _fit_regression(frontier, "Best in year", current_range)
        method_results = []
        for method_name in methods:
            subset = df[df["Method"] == method_name]
            if subset.empty:
                continue
            reg_method = _fit_regression(subset, method_name, current_range)
            method_results.append(
                {
                    "method": method_name,
                    "count": int(len(subset)),
                    "reg": reg_method,
                    "referenceHits": _reference_hits(reg_method),
                }
            )
        return current_range, reg_all, reg_frontier, method_results

    initial_end = max_year + FIT_RANGE_PADDING_YEARS
    fit_range, reg_all, reg_frontier, method_results = compute_regressions(initial_end)
    frontier_hits = _reference_hits(reg_frontier)

    cap_year = min(max_year + MAX_FUTURE_YEARS, X_RANGE_MAX)

    def _max_hit_within(hits: list[dict[str, float]]) -> float:
        filtered = [h["year"] for h in hits if h["year"] <= cap_year]
        return max(filtered) if filtered else 0.0

    base_need = max_year + FIT_RANGE_PADDING_YEARS
    candidates = [base_need, _max_hit_within(frontier_hits)]
    for entry in method_results:
        candidates.append(_max_hit_within(entry["referenceHits"]))
    desired_end = min(cap_year, max(candidates))
    if abs(desired_end - fit_range[1]) > 1e-6:
        fit_range, reg_all, reg_frontier, method_results = compute_regressions(desired_end)
        frontier_hits = _reference_hits(reg_frontier)

    method_stats = [
        {
            "method": entry["method"],
            "count": entry["count"],
            "doublingTimeYears": entry["reg"].doubling_time_years,
            "series": entry["reg"].series,
            "referenceHits": entry["referenceHits"],
        }
        for entry in method_results
    ]

    top_row = df.loc[df["Neurons"].idxmax()]
    latest_row = df.loc[df["decimal_year"].idxmax()]
    source_counts = (
        df.groupby("Source")
        .size()
        .sort_values(ascending=False)
        .reset_index(name="count")
        .to_dict("records")
    )

    payload = {
        "points": points,
        "regressions": {
            "overall": {
                "label": reg_all.label,
                "doublingTimeYears": reg_all.doubling_time_years,
                "series": reg_all.series,
            },
            "frontier": {
                "label": reg_frontier.label,
                "doublingTimeYears": reg_frontier.doubling_time_years,
                "series": reg_frontier.series,
            },
        },
        "methods": methods,
        "methodRegressions": method_stats,
        "maxNeurons": float(df["Neurons"].max()),
        "xRange": {"min": fit_range[0], "max": fit_range[1]},
        "references": BIO_REFERENCES,
    }

    summary = {
        "rows": len(df),
        "latestDate": _format_date(int(latest_row["Year"]), int(latest_row["Month"])),
        "latestAuthors": latest_row["Authors"],
        "latestPublication": latest_row["Publication"],
        "latestMethod": latest_row["Method"],
        "latestNeurons": int(latest_row["Neurons"]),
        "maxNeurons": int(top_row["Neurons"]),
        "maxPublication": top_row["Publication"],
        "maxAuthors": top_row["Authors"],
        "maxYear": int(top_row["Year"]),
        "maxMethod": top_row["Method"],
        "sources": source_counts,
    }

    doc = Html(
        Head(
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            Meta(
                name="description",
                content="neurotrends – neurons simultaneously recorded vs. year, with transparent data and citations.",
            ),
            Title("neurotrends"),
            Link(rel="stylesheet", href="./assets/styles.css"),
            Script(src="./assets/d3.min.js", defer=True),
            Script(src="./assets/observable-plot.js", defer=True),
            Script(src="./assets/plot.js", defer=True),
        ),
        Body(
            Main(
                Div(
                    Div(
                        H2("neurotrends"),
                        Div(
                            Div(
                                Span("Latest datapoint", cls="nt-label"),
                                Strong(summary["latestDate"], cls="nt-value"),
                                P(
                                    f"{summary['latestNeurons']:,} neurons • {summary['latestPublication']}",
                                    cls="nt-meta",
                                ),
                            ),
                            Div(
                                Span("Frontier max", cls="nt-label"),
                                Strong(f"{summary['maxNeurons']:,}", cls="nt-value"),
                                P(
                                    f"{summary['maxPublication']} ({summary['maxYear']})",
                                    cls="nt-meta",
                                ),
                            ),
                            Div(
                                Span("Dataset size", cls="nt-label"),
                                Strong(str(summary["rows"]), cls="nt-value"),
                                P("papers from curated sources", cls="nt-meta"),
                            ),
                            cls="nt-metrics",
                        ),
                        cls="nt-hero",
                    ),
                    Section(
                        Div(id="neuro-plot", cls="nt-plot"),
                        Div(id="nt-legend", cls="nt-legend"),
                        Div(
                            Div(
                                Span("Doubling time (frontier)", cls="nt-label"),
                                Strong(
                                    _format_doubling(payload["regressions"]["frontier"]["doublingTimeYears"]),
                                    cls="nt-value",
                                ),
                                P("Best-in-year datapoints", cls="nt-meta"),
                            ),
                            cls="nt-annotations",
                        ),
                        Div(
                            H4("Doubling by modality"),
                            Div(
                                *[
                                    Div(
                                        Span(stat["method"], cls="nt-label"),
                                        Strong(_format_doubling(stat["doublingTimeYears"]), cls="nt-value"),
                                        P(f"{stat['count']} papers", cls="nt-meta"),
                                        Ul(
                                            *[
                                                Li(f"{_short_label(hit['label'])} ≈ {_format_year(hit['year'])}")
                                                for hit in stat["referenceHits"][:3]
                                            ],
                                            cls="nt-milestones",
                                        ),
                                    )
                                    for stat in method_stats
                                ],
                                cls="nt-method-grid",
                            ),
                            cls="nt-method-wrap",
                        ),
                        cls="nt-chart-card",
                    ),
                    Div(
                        Div(
                            H3("Download & extend"),
                            P(
                                "Want to audit or extend this view? Grab the CSV and regenerate the site. "
                                "Columns include neurons captured, method, authors, and DOIs.",
                            ),
                            A("Download CSV", href="./neural_recording_papers.csv", cls="nt-button"),
                            cls="nt-download",
                        ),
                        cls="nt-download-row",
                    ),
                    cls="nt-shell",
                ),
            ),
            Footer(
                P(
                    "Built with FastHTML + Observable Plot. Deploy anywhere static files are welcome.",
                    cls="nt-footer-text",
                )
            ),
            Script(
                json.dumps(payload, separators=(",", ":")),
                id="neuro-data",
                type="application/json",
            ),
            cls="nt-body",
        ),
    )

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = PUBLIC_DIR / "index.html"
    html_path.write_text(_render(doc), encoding="utf-8")
    csv_target = PUBLIC_DIR / DATA_PATH.name
    csv_target.write_bytes(DATA_PATH.read_bytes())
    return html_path


def _format_doubling(value: float | None) -> str:
    if value is None or math.isinf(value):
        return "n/a"
    if value >= 8:
        return f"{value:.1f} yr"
    return f"{value:.2f} yr"


def _format_year(value: float | None) -> str:
    if value is None or math.isinf(value):
        return "n/a"
    return f"{value:.0f}"


if __name__ == "__main__":
    output = build_site()
    print(f"Wrote {output}")
