"""A small command line: sts serve, sts seed --reset, sts check-data."""

from __future__ import annotations

import os

import typer

from .config import Settings
from .demo_data import DemoDataError, check_demo_data, load_demo_data

app = typer.Typer(help="Sandbox to Shipped: one front door for AI tool requests.", no_args_is_help=True)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Address to listen on."),
    port: int = typer.Option(None, help="Port. Defaults to the PORT variable, or 8080."),
    reload: bool = typer.Option(False, help="Restart when code changes."),
):
    """Start the web app."""
    import uvicorn

    port = port or int(os.environ.get("PORT", "8080"))
    settings = Settings.from_env()
    if settings.fell_back:
        typer.echo("STS_MODE is live but ANTHROPIC_API_KEY is not set. Running the demo instead.")
    typer.echo(f"Sandbox to Shipped running in {settings.mode} mode on http://{host}:{port}")
    uvicorn.run("sts.web:app", host=host, port=port, reload=reload)


@app.command()
def seed(
    reset: bool = typer.Option(False, "--reset", help="Replace everything in the database with the demo data."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask before replacing data."),
):
    """In live mode, load the demo data into the database."""
    from .store import LiveStore

    settings = Settings.from_env()
    if settings.requested_mode != "live":
        typer.echo("Seeding is for live mode. Demo mode already loads the demo data on every start.")
        raise typer.Exit(1)
    if not reset:
        typer.echo("Add --reset to load the demo data. It replaces what is in the database.")
        raise typer.Exit(1)
    try:
        data = load_demo_data(settings.demo_dir)
    except DemoDataError as exc:
        typer.echo("The demo data has problems:\n" + str(exc))
        raise typer.Exit(1)
    store = LiveStore(settings.data_dir)
    if store.has_data() and not yes:
        typer.confirm(
            f"This replaces every tool, request and decision in {settings.db_path}. Continue?", abort=True
        )
    store.load_demo(data)
    typer.echo(f"Loaded {len(data.tools)} tools, {len(data.requests)} requests and {len(data.decisions)} decisions.")


@app.command("check-data")
def check_data():
    """Check the demo data files and print any problems."""
    problems = check_demo_data(Settings.from_env().demo_dir)
    if problems:
        typer.echo(f"Found {len(problems)} problem(s):")
        for p in problems:
            typer.echo(f"  {p}")
        raise typer.Exit(1)
    typer.echo("Demo data looks good.")


if __name__ == "__main__":
    app()
