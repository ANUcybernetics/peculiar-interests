"""The `pollie` command. Thin: every subcommand calls one function in the
module that owns the work, so the pipeline is scriptable from Python too.

    pollie fetch [house|senate|roster|all]   pull the register indexes and documents into raw/
    pollie parse [house|senate|all]          regenerate data/ from raw/ (+ overrides/)
    pollie people                            rebuild data/people.json from the roster CSVs + indexes
    pollie schema                            write data/schema.json from the pydantic models
    pollie transcribe PDF                    transcribe a scanned statement with Claude into an override
    pollie status                            what we hold, what is pending
    pollie run                               the nightly sequence: fetch all, parse all, people, schema
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path

import typer
from loguru import logger

from peculiar_interests import paths, store
from peculiar_interests.schema import Chamber, ExtractionMethod, Statement

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)


class Target(StrEnum):
    HOUSE = "house"
    SENATE = "senate"
    ROSTER = "roster"
    ALL = "all"


PARLIAMENT_OPTION = typer.Option(48, "--parliament", "-p", help="Parliament number")
TARGET_ARGUMENT = typer.Argument(Target.ALL, help="house, senate, roster or all")
DEST_OPTION = typer.Option(
    None,
    help="Override TOML to write (default: overrides/<parliament>/house/<stem>.toml)",
)
MODEL_OPTION = typer.Option("opus", "--model", help="Claude model alias for claude -p")


@app.callback()
def _configure(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO")


@app.command()
def fetch(
    target: Target = TARGET_ARGUMENT, parliament: int = PARLIAMENT_OPTION
) -> None:
    """Fetch register indexes and documents into raw/."""
    if target in (Target.ROSTER, Target.ALL):
        from peculiar_interests import people

        people.fetch_roster()
    if target in (Target.SENATE, Target.ALL):
        from peculiar_interests import senate

        changed = senate.fetch(parliament)
        logger.info("senate: {} statements changed", len(changed))
    if target in (Target.HOUSE, Target.ALL):
        from peculiar_interests import house

        changed = house.fetch(parliament)
        logger.info("house: {} statements changed", len(changed))


@app.command()
def parse(
    target: Target = TARGET_ARGUMENT, parliament: int = PARLIAMENT_OPTION
) -> None:
    """Regenerate data/ from the committed raw/ files and overrides/."""
    if target in (Target.SENATE, Target.ALL):
        from peculiar_interests import senate

        senate.parse(parliament)
    if target in (Target.HOUSE, Target.ALL):
        from peculiar_interests import house

        house.parse(parliament)


@app.command()
def people(parliament: int = PARLIAMENT_OPTION) -> None:
    """Rebuild data/people.json."""
    from peculiar_interests import people as roster

    written = roster.write(roster.build(parliament))
    logger.info("wrote {}", paths.relative(written))


@app.command()
def schema() -> None:
    """Write data/schema.json (JSON Schema for a Statement)."""
    store.write_json(paths.DATA / "schema.json", Statement.model_json_schema())


@app.command()
def transcribe(
    pdf: Path,
    dest: Path | None = DEST_OPTION,
    model: str = MODEL_OPTION,
    parliament: int = PARLIAMENT_OPTION,
) -> None:
    """Transcribe a scanned statement (raw/house/<parl>/<aph_id>.pdf) with Claude
    into an override, marked machine-read until a person confirms it."""
    from peculiar_interests import transcribe as transcribe_module

    target = dest or paths.override_path(Chamber.HOUSE, parliament, pdf.stem)
    transcribe_module.transcribe(pdf, target, paths.RAW / "transcribe", model=model)
    logger.info(
        'wrote {}; check it against the PDF, then set method = "manual"', target
    )


@app.command()
def status(parliament: int = PARLIAMENT_OPTION) -> None:
    """Summarise what data/ holds and what still needs a person."""
    for chamber in Chamber:
        statements = store.read_statements(chamber, parliament)
        interests = sum(len(s.interests) for s in statements)
        alterations = sum(len(s.alterations) for s in statements)
        typer.echo(
            f"{chamber.value:6} {len(statements):4} statements  {interests:5} interests  {alterations:5} alterations"
        )
        for s in statements:
            if s.extraction.method in (ExtractionMethod.PENDING, ExtractionMethod.OCR):
                typer.echo(
                    f"       {s.extraction.method.value:8} {s.aph_id:8} {s.display_name}"
                )


@app.command()
def run(parliament: int = PARLIAMENT_OPTION) -> None:
    """The nightly sequence: fetch everything, parse everything, roster, schema."""
    fetch(Target.ALL, parliament)
    parse(Target.ALL, parliament)
    people(parliament)
    schema()
    status(parliament)
