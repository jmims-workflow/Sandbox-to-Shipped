"""A small command line: sts serve, sts seed --reset, sts check-data, sts eval-matching."""

from __future__ import annotations

import os

import typer

from .config import Settings
from .demo_data import DemoDataError, check_demo_data, load_demo_data

app = typer.Typer(help="Sandbox to Shipped: one front door for AI tool requests.", no_args_is_help=True)


def _refuse_bad_settings(settings: Settings) -> None:
    problem = settings.startup_problem()
    if problem:
        typer.echo("Not starting: " + problem, err=True)
        raise typer.Exit(1)


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
    _refuse_bad_settings(settings)
    if settings.fell_back:
        typer.echo(f"STS_MODE is {settings.requested_mode} but ANTHROPIC_API_KEY is not set. Running the demo instead.")
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
    _refuse_bad_settings(settings)
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
    """Check the demo data files and security_rules.yaml, and print any problems."""
    settings = Settings.from_env()
    problems = check_demo_data(settings.demo_dir, settings.security_rules_path)
    if problems:
        typer.echo(f"Found {len(problems)} problem(s):")
        for p in problems:
            typer.echo(f"  {p}")
        raise typer.Exit(1)
    typer.echo("Demo data and security rules look good.")


@app.command("eval-matching")
def eval_matching(
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask before making Claude calls."),
    max_calls: int = typer.Option(60, "--max-calls", help="Refuse to run more Claude calls than this."),
    repeats: int = typer.Option(1, "--repeats", min=1, help="Run each case this many times to check consistency."),
    baseline: bool = typer.Option(False, "--baseline", help="Use the simple word match. No key, no network calls."),
    out_dir: str = typer.Option("", "--out-dir", help="Where to write the report. Defaults to evals/results."),
):
    """Run the labeled matching cases through the match check, score them and write a dated report."""
    from datetime import date
    from pathlib import Path

    from . import eval_matching as ev

    settings = Settings.from_env()  # STS_MODE is ignored here; only the key, STS_MODEL and STS_FAKE_CLAUDE count.
    try:
        runner = ev.make_runner(settings, baseline)
    except ValueError as exc:
        typer.echo("Not running: " + str(exc), err=True)
        raise typer.Exit(1)
    try:
        world = ev.load_world(settings.demo_dir)
        cases = ev.load_cases(ev.CASES_PATH, world)
    except (DemoDataError, ev.CaseFileError) as exc:
        typer.echo("The case file or demo data has problems:\n" + str(exc), err=True)
        raise typer.Exit(1)

    calls = 0 if runner.kind == "baseline" else len(cases) * repeats
    who = {"claude": f"Claude ({runner.model})", "stand-in": "the stand-in for Claude (testing only)",
           "baseline": "the word match"}[runner.kind]
    typer.echo(f"{len(cases)} cases x {repeats} run(s) against {who}: {calls} Claude call(s).")
    if calls > max_calls:
        typer.echo(f"Not running: that is more than --max-calls {max_calls}. Lower --repeats or raise --max-calls.",
                   err=True)
        raise typer.Exit(1)
    if runner.kind == "claude" and not yes:
        typer.confirm(f"Make {calls} real Claude calls? They are billed to the key's account", abort=True)

    out = Path(out_dir) if out_dir else ev.RESULTS_DIR
    markdown, md, js = ev.evaluate(cases, runner, world, repeats=repeats, out_dir=out,
                                   cases_hash=ev.case_file_hash(ev.CASES_PATH), today=date.today(),
                                   progress=typer.echo)
    typer.echo(f"\nWrote {md} and {js}\n")
    typer.echo(markdown)


if __name__ == "__main__":
    app()
