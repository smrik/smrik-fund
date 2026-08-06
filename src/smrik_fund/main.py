import typer

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


def main() -> None:
    app()
