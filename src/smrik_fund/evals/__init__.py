"""Evaluation harness for the filing-investigation product.

The loop this exists to close: change the product, re-execute frozen cases
against real model calls, and read the delta.  Harness health is independent of
product results - a run in which every case fails is a healthy harness reporting
a real product state.
"""

from __future__ import annotations

from .cases import CHECKS, JUDGE_MODEL, JUDGE_REASONING_EFFORT, discover
from .report import compare, summarize, update_ledger, write_reports
from .runner import run_case, run_iteration

__all__ = [
	"CHECKS",
	"JUDGE_MODEL",
	"JUDGE_REASONING_EFFORT",
	"compare",
	"discover",
	"run_case",
	"run_iteration",
	"summarize",
	"update_ledger",
	"write_reports",
]
