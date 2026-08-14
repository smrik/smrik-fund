import typer

from .ingestion.artifacts import save_statement_artifacts
from .ingestion.parser import parse_statement_artifacts
from .ingestion.statements import (
    build_analytical_pnl,
    save_analytical_pnl,
)

app = typer.Typer(
    no_args_is_help=True, help="A small fundamental investment research system."
)

# region EDGAR


# region Statements
@app.command()
def parse(ticker: str) -> None:
    """
    Fetch the latest financial statements
    """

    artifacts = parse_statement_artifacts(ticker)
    output_dir = save_statement_artifacts(artifacts)

    typer.echo(f"Saved: {output_dir}")
    typer.echo(f"facts: {len(artifacts.facts)} rows")
    for name, frame in artifacts.statements.items():
        typer.echo(f"{name}: {len(frame)} rows x {len(frame.columns)} columns")


@app.command()
def analyze(
    ticker: str,
    years: int = typer.Option(default=3, help="Number of annual periods to include."),
) -> None:
    """Build and save the derived analytical P&L."""
    pnl = build_analytical_pnl(ticker, years=years)
    output_path = save_analytical_pnl(ticker, pnl)
    typer.echo(f"Saved analytical P&L: {output_path}")


# endregion


# region Basic commands
@app.command()
def hello(name: str = "world") -> None:
    """Say hello. :)"""
    typer.echo(f"Hello, {name}!")


@app.command()
def status() -> None:
    typer.echo("smrik-fund alive and working :)")


# endregion


# endregion


# region Company research
@app.command()
def company(
    ticker: str,
    years: int = typer.Option(default=5, help="Number of historical years to inspect."),
) -> None:
    """Show the requested company research scope."""

    # print company and year
    typer.echo(message=f"Company: {ticker.upper()}")
    typer.echo(message=f"Historical years: {years}")


# endregion


def main() -> None:
    app()
