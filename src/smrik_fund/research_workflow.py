"""One free company workflow shared by the Typer CLI and the local workbench."""

import json
from datetime import UTC, datetime
from pathlib import Path

from smrik_fund.company_model import DEFAULT_CONTROLS
from smrik_fund.market_screen import symbol, write_json
from smrik_fund.research_audit import file_hash, verify_screen


def run_deep(run_dir, ticker, output_dir, *, case_dir=None, assumptions=None):
	"""Freeze evidence, calculate a provisional model, and retain every stop reason.

	A nonempty output folder is never reused. A failure preserves the evidence and
	stage reached, while a fresh run receives a new directory and audit timeline.
	"""
	from smrik_fund.company_case import freeze_company, validate_case
	from smrik_fund.company_run import run_case

	run_dir, output_dir = Path(run_dir), Path(output_dir)
	ticker = symbol(ticker)
	if output_dir.exists() and any(output_dir.iterdir()):
		raise ValueError("Deep output directory must be new/empty")
	output_dir.mkdir(parents=True, exist_ok=True)
	stage = "selection"

	def progress(phase, status, detail):
		nonlocal stage
		stage = phase
		event = {
			"at": datetime.now(UTC).isoformat(),
			"phase": phase,
			"status": status,
			"detail": detail,
		}
		with (output_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
			stream.write(json.dumps(event) + "\n")

	try:
		progress(
			"selection", "RUNNING", "Verify frozen screening inputs and issuer routing"
		)
		report = verify_screen(run_dir)
		rows = [r for r in report["rows"] if r["ticker"] == ticker]
		if len(rows) != 1:
			raise ValueError("Ticker must appear exactly once in the research run")
		company = rows[0]
		if not company["issuer_cik"]:
			raise ValueError("SEC issuer identity is missing; refresh the screen")
		if company["currency"] != "USD" or company["financial_currency"] != "USD":
			raise ValueError(
				"Deep valuation currently requires USD quote and financial currency"
			)
		quote_age = datetime.now(UTC).timestamp() - (company["quote_time"] or 0)
		if not 0 <= quote_age <= 7 * 86400:
			raise ValueError(
				"Refresh the screen: quote is missing, future-dated or older than seven days"
			)
		cutoff = datetime.now(UTC).date().isoformat()
		source = Path(case_dir) if case_dir else output_dir / "source"
		write_json(
			output_dir / "deep-inputs.json",
			{
				"ticker": ticker,
				"screen": str(run_dir.resolve()),
				"report_sha256": file_hash(run_dir / "report.json"),
				"snapshot_hash": report["snapshot_hash"],
				"source": str(source.resolve()),
				"information_cutoff": cutoff,
				"paid_calls": 0,
			},
		)
		progress(
			"selection",
			"PASS",
			f"Selected {ticker}; SEC issuer {company['issuer_cik']}",
		)
		progress(
			"sources",
			"RUNNING",
			"Reuse today's frozen case"
			if case_dir
			else "Fetch and freeze annual/interim SEC filings",
		)
		manifest = (
			validate_case(source)
			if case_dir
			else freeze_company(ticker, cutoff, source)
		)
		if manifest["information_cutoff"] != cutoff:
			raise ValueError(
				"Frozen source cutoff differs from today; fetch a new case"
			)
		if manifest["ticker"] != ticker or str(manifest["cik"]) != str(
			company["issuer_cik"]
		):
			raise ValueError(
				"Frozen source ticker/issuer differs from selected research company"
			)
		progress(
			"sources",
			"PASS",
			f"Frozen source measurement {manifest['measurement_date']}",
		)
		if not company["method"].startswith("Operating company:"):
			result = {
				"ticker": ticker,
				"status": "SOURCE_ONLY_SPECIALIST_METHOD_REQUIRED",
				"method": company["method"],
				"source": str(source.resolve()),
				"valuation_complete": False,
				"paid_calls": 0,
			}
			progress(
				"method",
				"BLOCKED",
				company["method"] + "; dedicated valuation method required",
			)
		else:
			if assumptions is None:
				# Keep scenario rates explicit; replace the old generic $250 price
				# with this company's dated quote in the WACC capital weights.
				assumptions = {
					"controls": {
						**DEFAULT_CONTROLS,
						"share_price_proxy": company["metrics"]["price"],
						"payout_ratio": 0,
						"services_growth": 0,
						"intangible_additions_ratio": 0,
					},
					"rationale": f"Free provisional defaults; capital weights use the {ticker} USD quote observed at Unix time {company['quote_time']}. Other rates and forecast assumptions are scenario estimates.",
					"limitations": [
						"Reported TTM history includes one-offs unless explicitly adjusted. This is a provisional research baseline, not a normalized price target."
					],
				}
			result = run_case(
				ticker,
				source,
				output_dir,
				live=False,
				assumptions=assumptions,
				progress=progress,
			)
		write_json(output_dir / "deep-result.json", result)
		return result
	except Exception as exc:
		# Includes provider, native Excel and formula-process failures. Do not
		# silently retry, claim completion or discard the partial source capture.
		reason = str(exc)
		# Native Excel and formula-engine exceptions carry useful stderr that
		# would otherwise be hidden behind a generic subprocess exit code.
		for name in ("stdout", "stderr"):
			detail = getattr(exc, name, None)
			if detail:
				if isinstance(detail, bytes):
					detail = detail.decode("utf-8", errors="replace")
				(output_dir / f"failed-process-{name}.txt").write_text(
					detail, encoding="utf-8"
				)
				if name == "stderr":
					reason += "\n" + detail[-3000:]
		progress(stage, "BLOCKED", reason)
		write_json(
			output_dir / "blocked.json",
			{
				"ticker": ticker,
				"status": "BLOCKED",
				"stage": stage,
				"reason": reason,
				"valuation_complete": False,
				"paid_calls": 0,
			},
		)
		raise
