import typer

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

@app.command()
def analyze(
    ticker: str,
    years: int = typer.Option(default=3, help="Number of annual periods to include."),
) -> None:
    """Build and save the derived analytical P&L."""
    pnl = build_analytical_pnl(ticker, years=years)
    output_path = save_analytical_pnl(ticker, pnl)
    typer.echo(f"Saved analytical P&L: {output_path}")


@app.command()
def reconcile(ticker: str) -> None:
    """Reconcile safe reported P&L subtotals from the existing analytical P&L."""
    pnl = load_analytical_pnl(ticker)
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
    typer.echo(
        f"Reconciliation: {passed} passed, {failed} failed, {skipped} skipped"
    )
    typer.echo(f"Saved reconciliation checks: {output_path}")


def main() -> None:
    app()
