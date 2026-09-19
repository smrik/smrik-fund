"""CLI implementation for the evaluation harness.

Kept here rather than in ``main.py`` so the eval code lives together and the
CLI module stays a thin registration layer.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from .report import compare, update_ledger, write_reports
from .runner import run_iteration


def run(
	ticker: str | None,
	*,
	suite: str | None,
	case: str | None,
	baseline: Path | None,
	output_root: Path,
	judge: bool,
	max_calls: int | None,
	preflight: str | None,
) -> None:
	"""Execute frozen evaluation cases against the live product."""
	try:
		iteration = run_iteration(
			ticker.strip().upper() if ticker else None,
			suite=suite,
			case_id=case,
			output_root=output_root,
			max_calls=max_calls,
			judge_enabled=judge,
			preflight_target=preflight,
		)
	except (OSError, ValueError, RuntimeError) as exc:
		raise typer.BadParameter(str(exc)) from exc

	run_dir = Path(iteration["paths"]["run_dir"])
	summary_path = write_reports(iteration, run_dir)
	update_ledger(output_root)

	typer.echo(f"{iteration['harness_status']}: {iteration['iteration_id']}")
	typer.echo(f"Definition: {iteration['definition_hash']}")
	typer.echo(
		f"Calls: product {iteration['calls']['product']}, "
		f"judge {iteration['calls']['judge']}"
	)
	for record in iteration["cases"]:
		typer.echo(
			f"{record['ticker']} {record['case_id']}: "
			f"{record['case_status']} / {record['product_status']} / "
			f"{record['judge_status']} / {record.get('qualitative_verdict') or '-'}"
		)
	typer.echo(f"Saved: {run_dir / 'iteration.json'}")
	typer.echo(f"Summary: {summary_path}")

	if baseline is not None:
		delta = compare(run_dir, baseline)
		(run_dir / "comparison.json").write_text(
			json.dumps(delta, indent=2), encoding="utf-8"
		)
		typer.echo(f"Comparison: {delta['status']}")
