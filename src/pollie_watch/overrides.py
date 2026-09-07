"""Hand-confirmed statements for documents no parser can read.

An override is a TOML file at `paths.override_path(...)` holding the parts of a
Statement that come from reading the document: `interests`, `alterations`,
`notes`, `date_lodged`, and an `extraction` block. The parser supplies the
identity and source fields from the register index and applies the override on
top. `pollie transcribe` writes one with `extraction.method = "ocr"` (machine-read);
a reviewer corrects it against the PDF and flips the method to `"manual"`, the
only signal the site presents as confirmed. Top-level keys must come before the
`[extraction]` table or TOML assigns them to it.

    date_lodged = 2025-08-19
    notes = ["Registrar note carried over from page 1"]

    date_lodged = 2025-08-19
    notes = ["Registrar note carried over from page 1"]

    [extraction]
    method = "ocr"
    notes = ["Transcribed from 17 page images by Claude (opus) via claude -p on 2026-09-07"]

    [[interests]]
    category = "real-estate"
    holder = "self"
    fields = { location = "Marrickville, NSW", purpose = "Residential" }

    [[alterations]]
    kind = "addition"
    category = "gifts"
    holder = "self"
    details = "Appreciation plaque from ..."
    date_submitted = 2026-03-04
    date_processed = 2026-03-06
    sequence = 1
"""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pollie_watch import paths
from pollie_watch.schema import Alteration, Chamber, Extraction, Interest, Statement


class Override(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    extraction: Extraction
    date_lodged: date | None = None
    notes: list[str] = Field(default_factory=list)
    interests: list[Interest] = Field(default_factory=list)
    alterations: list[Alteration] = Field(default_factory=list)


def load(path: Path) -> Override:
    with path.open("rb") as f:
        return Override.model_validate(tomllib.load(f))


def find(chamber: Chamber, parliament: int, aph_id: str) -> Override | None:
    path = paths.override_path(chamber, parliament, aph_id)
    return load(path) if path.exists() else None


def apply(stub: Statement, override: Override) -> Statement:
    """Combine a parser's identity/source stub with a reviewed override."""
    return stub.model_copy(
        update={
            "extraction": override.extraction,
            "date_lodged": override.date_lodged or stub.date_lodged,
            "notes": [*stub.notes, *override.notes],
            "interests": override.interests,
            "alterations": override.alterations,
        }
    )
