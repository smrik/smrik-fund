"""Golden tests for the deterministic metric layer.

This is step one of the analyst loop: derive margins, year-over-year change, and
common-size percentages from EDGAR data.  It runs before any model call, so it
must be locked down deterministically - when a later LLM stage misbehaves, these
tests are what let you rule out the numbers underneath it.

No live calls, no fixtures to regenerate: the inputs are the frozen artifacts
already pinned by the evaluation case registry.

Two kinds of assertion, on purpose:

* **pinned values** catch input drift - EdgarTools changing, or a frozen file
  being regenerated;
* **invariants** catch computation drift - the formula changing while still
  producing plausible-looking numbers.

A pinned value alone would not tell you which of those broke.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from smrik_fund.evals.cases import sha256_file
from smrik_fund.ingestion.segments import load_segment_analytics
from smrik_fund.ingestion.statements import load_analytical_pnl

INPUT_ROOT = "data/live-segment-enrichment-i1"
FY26 = "2026-06-30 (FY)"
FY25 = "2025-06-30 (FY)"
FY24 = "2024-06-30 (FY)"

# Frozen input identity, matching the evaluation case registry.
PNL_SHA256 = "0CC3C663056E3CF4DC1F3DEEE956566D849472742F822632614212EF2F0432E0"
SEGMENTS_SHA256 = "5E0EF5152A052E63B655817DF80741F30A99AF65FC1B237EF23710EF625C81FE"

TOLERANCE = 1e-6


@pytest.fixture(scope="module")
def pnl() -> pd.DataFrame:
	return load_analytical_pnl("MSFT", INPUT_ROOT)


@pytest.fixture(scope="module")
def segments() -> pd.DataFrame:
	return load_segment_analytics("MSFT", INPUT_ROOT)


def _row(frame: pd.DataFrame, label: str) -> pd.Series:
	matched = frame[frame["label"] == label]
	assert len(matched) == 1, f"expected exactly one {label!r} row, got {len(matched)}"
	return matched.iloc[0]


def test_frozen_inputs_are_unchanged():
	"""If this fails, every other assertion here is measuring a different file."""
	assert sha256_file(f"{INPUT_ROOT}/MSFT/03_output/analytical_pnl.csv") == PNL_SHA256
	assert (
		sha256_file(f"{INPUT_ROOT}/MSFT/03_output/segment_analytics.csv")
		== SEGMENTS_SHA256
	)


# --- pinned values ----------------------------------------------------------


@pytest.mark.parametrize(
	("label", "period", "expected"),
	[
		("Revenue", FY26, 331_839_000_000.0),
		("Revenue", FY25, 281_724_000_000.0),
		("Gross margin", FY26, 225_465_000_000.0),
		("Gross margin", FY25, 193_893_000_000.0),
		("Research and development", FY26, 35_562_000_000.0),
		("Operating income", FY26, 155_237_000_000.0),
		("Operating income", FY25, 128_528_000_000.0),
	],
)
def test_reported_values_are_pinned(pnl, label, period, expected):
	assert _row(pnl, label)[period] == pytest.approx(expected)


@pytest.mark.parametrize(
	("label", "column", "expected"),
	[
		("Revenue", f"yoy_growth_{FY26}", 0.177887),
		("Gross margin", f"yoy_growth_{FY26}", 0.162832),
		("Research and development", f"yoy_growth_{FY26}", 0.094620),
		("Operating income", f"yoy_growth_{FY26}", 0.207807),
		("Revenue", f"percent_of_revenue_{FY26}", 1.0),
		("Gross margin", f"percent_of_revenue_{FY26}", 0.679441),
		("Research and development", f"percent_of_revenue_{FY26}", 0.107166),
		("Operating income", f"percent_of_revenue_{FY26}", 0.467808),
		("Gross margin", f"gross_margin_{FY26}", 0.679441),
		("Gross margin", f"gross_margin_bps_change_{FY26}", -87.964902),
	],
)
def test_derived_metrics_are_pinned(pnl, label, column, expected):
	assert _row(pnl, label)[column] == pytest.approx(expected, rel=1e-5)


@pytest.mark.parametrize(
	("segment", "period", "margin", "bps_change"),
	[
		("Productivity and Business Processes", FY26, 0.599153, 216.095832),
		("Productivity and Business Processes", FY25, 0.577543, 190.242458),
		("Intelligent Cloud", FY26, 0.413467, -61.351664),
		("Intelligent Cloud", FY25, 0.419602, -127.245043),
		("More Personal Computing", FY26, 0.266151, 69.331958),
		("More Personal Computing", FY25, 0.259218, 239.804972),
	],
)
def test_segment_operating_margins_are_pinned(
	segments, segment, period, margin, bps_change
):
	"""These are the figures the investigation stage is supposed to reuse."""
	rows = segments[
		(segments["segment_label"] == segment)
		& (segments["period"] == period)
		& (segments["metric"] == "OperatingIncomeLoss")
	]
	assert len(rows) == 1
	assert rows.iloc[0]["operating_margin"] == pytest.approx(margin, rel=1e-5)
	assert rows.iloc[0]["operating_margin_bps_change"] == pytest.approx(
		bps_change, rel=1e-5
	)


# --- invariants -------------------------------------------------------------


@pytest.mark.parametrize("label", ["Gross margin", "Research and development", "Operating income"])
def test_yoy_growth_matches_its_definition(pnl, label):
	row = _row(pnl, label)
	current, previous = row[FY26], row[FY25]
	assert row[f"yoy_growth_{FY26}"] == pytest.approx((current - previous) / previous)
	assert row[f"absolute_yoy_change_{FY26}"] == pytest.approx(current - previous)


@pytest.mark.parametrize("period", [FY26, FY25, FY24])
def test_percent_of_revenue_matches_its_definition(pnl, period):
	revenue = _row(pnl, "Revenue")[period]
	for label in ("Gross margin", "Research and development", "Operating income"):
		row = _row(pnl, label)
		assert row[f"percent_of_revenue_{period}"] == pytest.approx(
			row[period] / revenue
		)


def test_gross_margin_bps_change_matches_its_definition(pnl):
	row = _row(pnl, "Gross margin")
	delta = row[f"gross_margin_{FY26}"] - row[f"gross_margin_{FY25}"]
	assert row[f"gross_margin_bps_change_{FY26}"] == pytest.approx(delta * 10_000)


def test_segment_margin_matches_operating_income_over_revenue(segments):
	"""operating_margin must be the segment's own income divided by its revenue."""
	for segment in (
		"Productivity and Business Processes",
		"Intelligent Cloud",
		"More Personal Computing",
	):
		for period in (FY26, FY25, FY24):
			scope = segments[
				(segments["segment_label"] == segment) & (segments["period"] == period)
			]
			revenue = scope[scope["metric"] == "Revenue"]["numeric_value"]
			income = scope[scope["metric"] == "OperatingIncomeLoss"]
			assert len(revenue) == 1 and len(income) == 1
			assert income.iloc[0]["operating_margin"] == pytest.approx(
				income.iloc[0]["numeric_value"] / revenue.iloc[0]
			)


def test_segment_revenue_sums_to_consolidated_revenue(pnl, segments):
	"""Segment detail must tie back to the consolidated line it decomposes."""
	for period in (FY26, FY25, FY24):
		segment_total = segments[
			(segments["metric"] == "Revenue") & (segments["period"] == period)
		]["numeric_value"].sum()
		assert segment_total == pytest.approx(_row(pnl, "Revenue")[period], rel=1e-9)


def test_no_derived_metric_is_silently_infinite(pnl):
	"""A divide-by-zero must surface as NaN, never as inf masquerading as data."""
	derived = [c for c in pnl.columns if c.startswith(("yoy_growth_", "percent_of_revenue_", "gross_margin_"))]
	for column in derived:
		values = pd.to_numeric(pnl[column], errors="coerce").dropna()
		assert not any(math.isinf(float(v)) for v in values), f"{column} contains inf"
