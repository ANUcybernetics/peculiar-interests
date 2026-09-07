"""Reading and writing `data/`: one Statement JSON per person per parliament.

Files are written with sorted keys and a trailing newline so that a re-run
over unchanged input is byte-identical and `git diff` shows only real change.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from pollie_watch import paths
from pollie_watch.schema import Chamber, Statement


def write_statement(statement: Statement) -> Path:
    dest = paths.statement_path(
        statement.chamber, statement.parliament, statement.aph_id
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = (
        json.dumps(
            statement.model_dump(mode="json"),
            indent=1,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
    if dest.exists() and dest.read_text() == body:
        return dest
    dest.write_text(body)
    logger.info("wrote {}", paths.relative(dest))
    return dest


def read_statement(path: Path) -> Statement:
    return Statement.model_validate_json(path.read_text())


def read_statements(chamber: Chamber, parliament: int) -> list[Statement]:
    directory = paths.data_dir(chamber, parliament)
    if not directory.exists():
        return []
    return [read_statement(p) for p in sorted(directory.glob("*.json"))]


def write_json(path: Path, payload: object) -> Path:
    """Stable JSON for index files and the roster."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if not (path.exists() and path.read_text() == body):
        path.write_text(body)
        logger.info("wrote {}", paths.relative(path))
    return path
