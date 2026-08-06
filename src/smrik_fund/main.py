import typer

from .ingestion.statements import (
    parse_statements,
    save_statements,
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

    statements = parse_statements(ticker)
    output_dir = save_statements(ticker, statements)

    typer.echo(f"Saved statements to {output_dir}")


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
