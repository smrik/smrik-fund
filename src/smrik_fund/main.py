from pathlib import Path

import pandas as pd
import typer

from .ingestion.adjustment_analysis import (
	DEFAULT_MODEL,
	DEFAULT_REASONING_EFFORT,
	AdjustmentAnalysisError,
	run_analyst,
	save_analyst_result,
)
from .ingestion.reconciliation import (
	reconcile_pnl,
	save_reconciliation_checks,
)
from .ingestion.statements import (
	build_analytical_pnl,
	load_analytical_pnl,
	save_analytical_pnl,
)

app = typer.Typer(
	no_args_is_help=True, help="A small fundamental investment research system."
)


def _save_and_report_reconciliation(
	ticker: str,
	pnl: pd.DataFrame,
) -> Path:
	checks = reconcile_pnl(pnl)
	output_path = save_reconciliation_checks(ticker, checks)

	for check in checks.to_dict(orient="records"):
		if check["status"] in {"FAIL", "SKIPPED"}:
			typer.echo(
				f"WARNING {check['check_id']} {check['period']}: {check['message']}"
			)

	passed = int((checks["status"] == "PASS").sum())
	failed = int((checks["status"] == "FAIL").sum())
	skipped = int((checks["status"] == "SKIPPED").sum())
	typer.echo(f"Reconciliation: {passed} passed, {failed} failed, {skipped} skipped")
	typer.echo(f"Saved reconciliation checks: {output_path}")
	return output_path


def _evidence_by_id(packet: str) -> dict[str, dict[str, str]]:
	"""Map stable packet IDs to their metadata and quoted excerpts."""
	evidence: dict[str, dict[str, str]] = {}
	current_id: str | None = None
	for line in packet.splitlines():
		if line.startswith("### E") and line[5:].isdigit():
			current_id = line[4:].strip()
			evidence[current_id] = {"excerpt": ""}
		elif current_id and line.startswith(("Source: ", "Section: ", "Locator: ")):
			key, _, value = line.partition(": ")
			evidence[current_id][key.lower()] = value
		elif current_id and line.startswith("> "):
			evidence[current_id]["excerpt"] += f"{line[2:].strip()} "
	return {
		key: {field: value.strip() for field, value in block.items()}
		for key, block in evidence.items()
	}


def _run_adjustment_analysis(
	ticker: str,
	pnl: pd.DataFrame,
	model: str,
	reasoning_effort: str,
) -> None:
	"""Run Task 7 against the already-frozen evidence packet."""

	# Task 7 consumes a packet; filing retrieval belongs to a separate task.
	evidence_path = (
		Path("data")
		/ ticker.strip().upper()
		/ "03_output"
		/ "evidence"
		/ "restructuring.md"
	)
	try:
		evidence_text = evidence_path.read_text(encoding="utf-8")
	except OSError as exc:
		raise AdjustmentAnalysisError(
			f"frozen evidence packet not found: {evidence_path}"
		) from exc

	evidence_packet = evidence_text
	evidence_by_id = _evidence_by_id(evidence_packet)

	# Keep the P&L and packet together for one transparent Analyst call.
	result, metadata = run_analyst(
		ticker,
		pnl,
		evidence_packet,
		model=model,
		reasoning_effort=reasoning_effort,
		evidence_ref=str(evidence_path),
	)
	unknown_refs = sorted(
		{
			evidence_id
			for candidate in result.candidates
			for evidence_id in candidate.evidence_refs
			if evidence_id not in evidence_by_id
		}
	)
	if unknown_refs:
		raise AdjustmentAnalysisError(
			"Analyst returned unknown evidence reference(s): "
			+ ", ".join(unknown_refs)
		)
	# Persist first, then print a compact human-readable view of the same result.
	output_path = save_analyst_result(ticker, result, metadata)
	typer.echo("Analyst result:")
	typer.echo(f"Model: {metadata['model']}")
	typer.echo(f"Reasoning effort: {metadata['reasoning_effort']}")
	for number, candidate in enumerate(result.candidates, start=1):
		amount = (
			"null"
			if candidate.adjustment_amount is None
			else str(candidate.adjustment_amount)
		)
		typer.echo(f"Candidate {number}:")
		typer.echo(f"  Target line: {candidate.target_line}")
		typer.echo(f"  Sub-item: {candidate.sub_item or 'null'}")
		typer.echo(f"  Period: {candidate.period}")
		typer.echo(f"  Amount: {amount}")
		typer.echo(f"  Amount basis: {candidate.amount_basis}")
		if candidate.calculation is not None:
			typer.echo(f"  Calculation: {candidate.calculation}")
		typer.echo(f"  Reason: {candidate.reason}")
		typer.echo(f"  Uncertainty: {candidate.uncertainty or 'null'}")
		typer.echo("  Cited evidence:")
		for evidence_id in candidate.evidence_refs:
			evidence = evidence_by_id.get(evidence_id)
			if evidence is None:
				typer.echo(f"    {evidence_id}: [evidence ID not found]")
				continue
			typer.echo(f"    {evidence_id}:")
			for label in ("source", "section", "locator"):
				if label in evidence:
					typer.echo(f"      {label.title()}: {evidence[label]}")
			typer.echo(f"      Excerpt: {evidence['excerpt']}")
	typer.echo(f"Saved Analyst JSON: {output_path}")


@app.command()
def analyze(
	ticker: str,
	years: int = typer.Option(default=3, help="Number of annual periods to include."),
	adjustments: bool = typer.Option(
		default=False,
		help="Run optional proposal-only LLM adjustment analysis.",
	),
	model: str = typer.Option(
		default=DEFAULT_MODEL, help="OpenAI model for proposals."
	),
	reasoning_effort: str = typer.Option(
		default=DEFAULT_REASONING_EFFORT,
		help="OpenAI reasoning effort for proposals; override as needed.",
	),
) -> None:
	"""Build the analytical P&L and save deterministic reconciliation checks."""
	pnl = build_analytical_pnl(ticker, years=years)
	output_path = save_analytical_pnl(ticker, pnl)
	typer.echo(f"Saved analytical P&L: {output_path}")
 
	# Reconciliation stays deterministic and runs before the optional Analyst.
	_save_and_report_reconciliation(ticker, pnl)
	if adjustments:
		try:
			_run_adjustment_analysis(ticker, pnl, model, reasoning_effort)
		except AdjustmentAnalysisError as exc:
			typer.echo(f"Adjustment analysis unavailable: {exc}", err=True)


@app.command()
def reconcile(ticker: str) -> None:
	"""Reconcile safe reported P&L subtotals from the existing analytical P&L."""
	pnl = load_analytical_pnl(ticker)
	_save_and_report_reconciliation(ticker, pnl)


def main() -> None:
	app()
