"""Commands for the free-first daily research funnel."""

import json
from datetime import UTC, datetime
from pathlib import Path

import typer

from smrik_fund.daily_research import build_report, export_report
from smrik_fund.market_screen import DEFAULT_FILTERS, capture, symbol, write_json

app = typer.Typer(no_args_is_help=True, help="Free screening and research briefs; paid IC only by explicit opt-in.")


@app.command()
def run(
	output_dir: Path | None = typer.Option(None, help="New output directory; defaults to a timestamp under data/daily."),
	tickers: str = typer.Option("", help="Optional comma-separated US watchlist; otherwise screen the US universe."),
	snapshot: Path | None = typer.Option(None, help="Replay a frozen snapshot without network calls."),
	shortlist: int = typer.Option(20, min=1, max=30),
	max_enrich: int = typer.Option(0, min=0, help="Free fundamental fetch cap; default 0 fetches all value seeds."),
	min_cap: float = typer.Option(DEFAULT_FILTERS["min_cap"], min=0),
	min_price: float = typer.Option(DEFAULT_FILTERS["min_price"], min=0),
	min_volume: float = typer.Option(DEFAULT_FILTERS["min_volume"], min=0),
	refresh: bool = typer.Option(False, help="Bypass the 20-hour fundamentals cache."),
	model_dir: list[Path] | None = typer.Option(None, help="Attach a hash-verified existing company DCF run; repeatable."),
	previous: Path | None = typer.Option(None, help="Prior report.json for shortlist changes."),
) -> None:
	"""Screen → cheapness/quality checks → shortlist → free company briefs. EUR0 in LLM calls."""
	output_dir = output_dir or Path("data/daily") / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	try:
		if output_dir.exists() and any(output_dir.iterdir()):
			raise ValueError("Output directory must be new/empty; previous runs remain immutable")
		if snapshot and (tickers or refresh):
			raise ValueError("Snapshot replay cannot also fetch tickers or refresh")
		output_dir.mkdir(parents=True, exist_ok=True)
		if snapshot:
			data = json.loads(snapshot.read_text(encoding="utf-8"))
			write_json(output_dir / "snapshot.json", data)
		else:
			data = capture(output_dir, tickers=[t for t in tickers.split(",") if t.strip()], filters={"min_cap": min_cap, "min_price": min_price, "min_volume": min_volume}, max_enrich=max_enrich, refresh=refresh, progress=typer.echo)
		old = json.loads(previous.read_text(encoding="utf-8")) if previous else None
		report = build_report(data, shortlist_size=shortlist, model_dirs=model_dir or (), previous=old)
		export_report(report, output_dir)
	except (ValueError, OSError, KeyError) as exc:
		typer.echo(f"Daily run blocked: {exc}", err=True)
		raise typer.Exit(1) from exc
	typer.echo(json.dumps({"status": report["status"], "counts": report["counts"], "shortlist": report["shortlist"], "issues": report["issues"], "paid_calls": 0, "report": str((output_dir / "index.html").resolve())}, indent=2))


@app.command()
def ic(
	run_dir: Path,
	ticker: str,
	output_dir: Path = typer.Option(...),
	thesis: str = typer.Option(..., help="Why you suspect a genuine mispricing after reviewing the free brief."),
	question: str = typer.Option(..., help="The unresolved question where LLM interpretation could add value."),
	live: bool = typer.Option(False, help="Explicitly authorize one paid IC call; default only prepares a free packet."),
	budget: Path = typer.Option(Path("data/build-guide-api-budget.json")),
	price_snapshot: Path | None = typer.Option(None, help="Verified current model pricing; required for --live."),
) -> None:
	"""Prepare an IC evidence packet; only --live can spend API budget."""
	from smrik_fund.daily_ic import prepare_packet, run_ic

	try:
		packet = prepare_packet(run_dir, symbol(ticker), thesis=thesis, question=question)
		prices = json.loads(price_snapshot.read_text(encoding="utf-8")) if price_snapshot else None
		result = run_ic(packet, output_dir, live=live, budget_path=budget, prices=prices)
	except (ValueError, OSError, KeyError) as exc:
		typer.echo(f"IC blocked: {exc}", err=True)
		raise typer.Exit(1) from exc
	typer.echo(json.dumps(result, indent=2))


@app.command()
def deep(
	run_dir: Path,
	ticker: str,
	output_dir: Path = typer.Option(...),
	case_dir: Path | None = typer.Option(None, help="Reuse an immutable SEC case with today's information cutoff."),
	assumptions: Path | None = typer.Option(None, help="JSON with free operator controls, rationale and limitations."),
) -> None:
	"""On-demand SEC source capture and provisional operating-company DCF. No paid agents."""
	from smrik_fund.company_case import freeze_company, validate_case
	from smrik_fund.company_run import run_case

	created = False
	try:
		ticker = symbol(ticker)
		report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
		rows = [r for r in report["rows"] if r["ticker"] == ticker]
		if not rows:
			raise ValueError("Ticker not in this research run")
		if output_dir.exists() and any(output_dir.iterdir()):
			raise ValueError("Deep output directory must be new/empty")
		output_dir.mkdir(parents=True, exist_ok=True)
		created = True
		cutoff = datetime.now(UTC).date().isoformat()
		source = case_dir or output_dir / "source"
		if case_dir:
			manifest = validate_case(source)
			if manifest["information_cutoff"] != cutoff:
				raise ValueError("Frozen source cutoff differs from today; fetch a new case")
			if manifest["ticker"] != ticker or str(manifest["cik"]) != str(rows[0]["issuer_cik"]):
				raise ValueError("Frozen source ticker/issuer differs from selected research company")
		else:
			freeze_company(ticker, cutoff, source)
		if not rows[0]["method"].startswith("Operating company:"):
			result = {"ticker": ticker, "status": "SOURCE_ONLY_SPECIALIST_METHOD_REQUIRED", "method": rows[0]["method"], "source": str(source.resolve()), "valuation_complete": False, "paid_calls": 0}
		else:
			options = {"assumptions": json.loads(assumptions.read_text(encoding="utf-8"))} if assumptions else {}
			result = run_case(ticker, source, output_dir, live=False, **options)
		write_json(output_dir / "deep-result.json", result)
	except (ValueError, OSError, KeyError) as exc:
		result = {"ticker": ticker, "status": "BLOCKED", "reason": str(exc), "valuation_complete": False, "paid_calls": 0}
		if created:
			blocked = output_dir / "blocked.json"
			if not blocked.exists():
				write_json(blocked, result)
		typer.echo(json.dumps(result), err=True)
		raise typer.Exit(1) from exc
	typer.echo(json.dumps(result, indent=2))
