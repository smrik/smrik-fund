import typer
from pathlib import Path

from smrik_fund.legacy import DEFAULT_LEGACY_REPO, run_legacy_pipeline

app = typer.Typer(
    no_args_is_help=True, help="A small fundamental investment research system."
)


@app.command()
def hello(name: str = "world") -> None:
    """Say hello. :)"""
    typer.echo(f"Hello, {name}!")


@app.command()
def status() -> None:

    typer.echo("smrik-fund alive and working :)")


@app.command()
def company(
    ticker: str,
    years: int = typer.Option(5, help="Number of historical years to inspect."),
) -> None:
    """Show the requested company research scope."""
    typer.echo(f"Company: {ticker.upper()}")
    typer.echo(f"Historical years: {years}")


def main() -> None:
    app()
