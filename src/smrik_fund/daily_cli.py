"""Commands for the free-first daily research funnel."""

import json
from datetime import UTC, datetime
from pathlib import Path

import typer

from smrik_fund.daily_research import build_report, export_report
from smrik_fund.market_screen import DEFAULT_FILTERS, capture, symbol, write_json

app = typer.Typer(
	no_args_is_help=True,
	help="Free screening and research briefs; paid IC only by explicit opt-in.",
)


@app.command()
def serve(port: int = typer.Option(8787, min=1024, max=65535)) -> None:
	"""Open a local research workbench with free runs and evidence inspection."""
	from smrik_fund.research_workspace import serve as serve_workbench

	serve_workbench(port)


@app.command()
def audit(run_dir: Path) -> None:
	"""Verify a saved run's sources, calculations and published artifact hashes."""
	from smrik_fund.research_audit import audit_run

	result = audit_run(run_dir)
	typer.echo(json.dumps(result, indent=2))
	if result["integrity"] == "FAIL":
		raise typer.Exit(1)


@app.command()
def run(
	output_dir: Path | None = typer.Option(
		None, help="New output directory; defaults to a timestamp under data/daily."
	),
	tickers: str = typer.Option(
		"",
		help="Optional comma-separated US watchlist; otherwise screen the US universe.",
	),
	snapshot: Path | None = typer.Option(
		None, help="Replay a frozen snapshot without network calls."
	),
	shortlist: int = typer.Option(20, min=1, max=30),
	max_enrich: int = typer.Option(
		0, min=0, help="Free fundamental fetch cap; default 0 fetches all value seeds."
	),
	min_cap: float = typer.Option(DEFAULT_FILTERS["min_cap"], min=0),
	min_price: float = typer.Option(DEFAULT_FILTERS["min_price"], min=0),
	min_volume: float = typer.Option(DEFAULT_FILTERS["min_volume"], min=0),
	refresh: bool = typer.Option(False, help="Bypass the 20-hour fundamentals cache."),
	model_dir: list[Path] | None = typer.Option(
		None, help="Attach a hash-verified existing company DCF run; repeatable."
	),
	previous: Path | None = typer.Option(
		None, help="Prior report.json for shortlist changes."
	),
) -> None:
	"""Screen → cheapness/quality checks → shortlist → free company briefs. EUR0 in LLM calls."""
	output_dir = output_dir or Path("data/daily") / datetime.now(UTC).strftime(
		"%Y%m%dT%H%M%S%fZ"
	)
	try:
		if output_dir.exists() and any(output_dir.iterdir()):
			raise ValueError(
				"Output directory must be new/empty; previous runs remain immutable"
			)
		if snapshot and (tickers or refresh):
			raise ValueError("Snapshot replay cannot also fetch tickers or refresh")
		output_dir.mkdir(parents=True, exist_ok=True)
		if snapshot:
			data = json.loads(snapshot.read_text(encoding="utf-8"))
			write_json(output_dir / "snapshot.json", data)
		else:
			data = capture(
				output_dir,
				tickers=[t for t in tickers.split(",") if t.strip()],
				filters={
					"min_cap": min_cap,
					"min_price": min_price,
					"min_volume": min_volume,
				},
				max_enrich=max_enrich,
				refresh=refresh,
				progress=typer.echo,
			)
		old = json.loads(previous.read_text(encoding="utf-8")) if previous else None
		report = build_report(
			data, shortlist_size=shortlist, model_dirs=model_dir or (), previous=old
		)
		export_report(report, output_dir)
	except (ValueError, OSError, KeyError) as exc:
		typer.echo(f"Daily run blocked: {exc}", err=True)
		raise typer.Exit(1) from exc
	typer.echo(
		json.dumps(
			{
				"status": report["status"],
				"counts": report["counts"],
				"shortlist": report["shortlist"],
				"issues": report["issues"],
				"paid_calls": 0,
				"report": str((output_dir / "index.html").resolve()),
			},
			indent=2,
		)
	)


@app.command()
def ic(
	run_dir: Path,
	ticker: str,
	output_dir: Path = typer.Option(...),
	thesis: str = typer.Option(
		..., help="Why you suspect a genuine mispricing after reviewing the free brief."
	),
	question: str = typer.Option(
		..., help="The unresolved question where LLM interpretation could add value."
	),
	live: bool = typer.Option(
		False,
		help="Explicitly authorize one paid IC call; default only prepares a free packet.",
	),
	budget: Path = typer.Option(Path("data/build-guide-api-budget.json")),
	price_snapshot: Path | None = typer.Option(
		None, help="Verified current model pricing; required for --live."
	),
) -> None:
	"""Prepare an IC evidence packet; only --live can spend API budget."""
	from smrik_fund.daily_ic import prepare_packet, run_ic

	try:
		packet = prepare_packet(
			run_dir, symbol(ticker), thesis=thesis, question=question
		)
		prices = (
			json.loads(price_snapshot.read_text(encoding="utf-8"))
			if price_snapshot
			else None
		)
		result = run_ic(
			packet, output_dir, live=live, budget_path=budget, prices=prices
		)
	except (ValueError, OSError, KeyError) as exc:
		typer.echo(f"IC blocked: {exc}", err=True)
		raise typer.Exit(1) from exc
	typer.echo(json.dumps(result, indent=2))


@app.command()
def deep(
	run_dir: Path,
	ticker: str,
	output_dir: Path = typer.Option(...),
	case_dir: Path | None = typer.Option(
		None, help="Reuse an immutable SEC case with today's information cutoff."
	),
	assumptions: Path | None = typer.Option(
		None, help="JSON with free operator controls, rationale and limitations."
	),
) -> None:
	"""Freeze SEC sources and build a provisional DCF. All stages retained; no paid agents."""
	from smrik_fund.research_workflow import run_deep

	try:
		inputs = (
			json.loads(assumptions.read_text(encoding="utf-8")) if assumptions else None
		)
		result = run_deep(
			run_dir, ticker, output_dir, case_dir=case_dir, assumptions=inputs
		)
	except Exception as exc:
		typer.echo(f"Deep run blocked: {exc}", err=True)
		raise typer.Exit(1) from exc
	typer.echo(json.dumps(result, indent=2))
