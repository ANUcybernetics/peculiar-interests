"""Transcribing scanned statements with Claude.

A handful of House members lodge handwritten forms, so their PDFs have no
usable text layer. Rather than run a local OCR model for three documents, the
page images are handed to Claude through `claude -p` (the logged-in Claude Code
subscription, as the sibling APS tracker does; `ANTHROPIC_*` is scrubbed from
the child environment so the call can never bill an API key), constrained to
the `Override` JSON schema. The result is written as an override with
`extraction.method = "ocr"`, meaning machine-read and not yet checked by a
person; a reviewer confirms it against the PDF and flips the method to
`"manual"`.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from loguru import logger

from pollie_watch import paths
from pollie_watch.overrides import Override
from pollie_watch.schema import (
    CATEGORY_FIELDS,
    HOUSE_ITEMS,
    Extraction,
    ExtractionMethod,
)

DEFAULT_MODEL = "opus"
_TIMEOUT_SECONDS = 20 * 60
_SCRUB_ENV_PREFIX = "ANTHROPIC_"
# Below this many characters per page, on average, a PDF is treated as a scan.
_TEXT_LAYER_CHARS_PER_PAGE = 200


def has_text_layer(path: Path) -> bool:
    with pdfplumber.open(path) as pdf:
        chars = sum(len(page.extract_text() or "") for page in pdf.pages)
        return chars / max(len(pdf.pages), 1) >= _TEXT_LAYER_CHARS_PER_PAGE


def render_pages(path: Path, out_dir: Path, dpi: int = 200) -> list[Path]:
    """Render every page of `path` to a PNG in `out_dir`, in page order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    pdf = pdfium.PdfDocument(path)
    try:
        for i in range(len(pdf)):
            image = pdf[i].render(scale=dpi / 72).to_pil().convert("RGB")
            dest = out_dir / f"page-{i + 1:02d}.png"
            image.save(dest)
            written.append(dest)
    finally:
        pdf.close()
    return written


def system_prompt() -> str:
    items = "\n".join(
        f"  {number}. {category.value}: fields {list(CATEGORY_FIELDS[category])}"
        for number, category in HOUSE_ITEMS.items()
    )
    return f"""You transcribe Australian House of Representatives "Statement of Registrable
Interests" forms from page images into structured JSON. Be a faithful copyist:
reproduce the member's wording exactly (fix nothing, summarise nothing, invent
nothing), and leave out anything you cannot read rather than guessing; put a
note about any illegible or ambiguous passage in `extraction.notes`, quoting
what you can see.

The form has fourteen numbered items. Each item is a table with rows for Self,
Spouse/Partner and Dependent Children ("holder": self, spouse, dependent). Item
2 has two sub-tables: (i) beneficial interest (fields.role = "beneficiary") and
(ii) trustee (fields.role = "trustee"). One declared line is one `interests`
entry; a cell listing several things (several clubs, several banks) becomes
several entries. "Not Applicable", "Nil", "N/A" and blank cells produce no
entry. Item numbers and their category slugs and field names:
{items}

Pages headed "Notification of alteration(s) of interests" hold ADDITION and
DELETION tables (Item, Details) with the same holder rows. Each detail line is
one `alterations` entry: kind addition or deletion, category from the item
number, holder from the row, `details` verbatim. `date_submitted` is the
signed/dated line on the notification (dd/mm/yyyy, often handwritten);
`date_processed` is the registrar's "PROCESSED <date>" stamp when present.
Number `sequence` from 1 in document order. `date_lodged` is the date on the
original statement's signature line.

Set `extraction.method` to "ocr" and `extraction.version` to 1."""


def user_prompt(pages: list[Path]) -> str:
    listing = "\n".join(str(p.resolve()) for p in pages)
    return (
        "Read every page image below in order with the Read tool, then return the "
        "transcription as JSON matching the schema.\n\n" + listing
    )


def call_claude(pages: list[Path], *, model: str = DEFAULT_MODEL) -> Override:
    cmd = [
        "claude",
        "-p",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--model",
        model,
        "--effort",
        "high",
        "--tools",
        "Read",
        "--system-prompt",
        system_prompt(),
        "--json-schema",
        json.dumps(Override.model_json_schema()),
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith(_SCRUB_ENV_PREFIX)}
    result = subprocess.run(
        cmd,
        input=user_prompt(pages),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_TIMEOUT_SECONDS,
        check=False,
        cwd=paths.ROOT,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude -p exited {result.returncode}: {result.stderr.strip()[:500]}"
        )
    payload = json.loads(result.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"claude -p error: {str(payload.get('result'))[:500]}")
    structured = payload.get("structured_output")
    if structured is None:
        raise RuntimeError("claude -p returned no structured_output")
    return Override.model_validate(structured)


def stamp(override: Override, *, model: str, pages: int) -> Override:
    """Replace whatever the model wrote in `extraction` with the record of how
    this file was produced, keeping its notes about illegible passages."""
    note = (
        f"Transcribed from {pages} page images by Claude ({model}) via claude -p on "
        f"{datetime.now(UTC):%Y-%m-%d}; not yet checked by a person"
    )
    return override.model_copy(
        update={
            "extraction": Extraction(
                method=ExtractionMethod.OCR,
                version=1,
                notes=[note, *override.extraction.notes],
            )
        }
    )


def _toml_escape(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_inline_table(fields: dict[str, str]) -> str:
    return (
        "{ " + ", ".join(f"{k} = {_toml_escape(v)}" for k, v in fields.items()) + " }"
    )


def write_override(override: Override, dest: Path) -> Path:
    """Serialise to the TOML format documented in overrides.py; round-trips
    through `overrides.load`."""
    # Top-level keys first: anything after a [table] header belongs to it.
    lines: list[str] = []
    if override.date_lodged is not None:
        lines.append(f"date_lodged = {override.date_lodged.isoformat()}")
    if override.notes:
        lines.append(f"notes = [{', '.join(_toml_escape(n) for n in override.notes)}]")
    if lines:
        lines.append("")
    lines += ["[extraction]", f'method = "{override.extraction.method.value}"']
    lines.append(f"version = {override.extraction.version}")
    if override.extraction.notes:
        lines.append(
            f"notes = [{', '.join(_toml_escape(n) for n in override.extraction.notes)}]"
        )
    lines.append("")
    for interest in override.interests:
        lines.append("[[interests]]")
        lines.append(f'category = "{interest.category.value}"')
        lines.append(f'holder = "{interest.holder.value}"')
        lines.append(f"fields = {_toml_inline_table(interest.fields)}")
        lines.append("")
    for alteration in override.alterations:
        lines.append("[[alterations]]")
        lines.append(f'kind = "{alteration.kind.value}"')
        if alteration.category is not None:
            lines.append(f'category = "{alteration.category.value}"')
        lines.append(f'holder = "{alteration.holder.value}"')
        lines.append(f"details = {_toml_escape(alteration.details)}")
        if alteration.fields:
            lines.append(f"fields = {_toml_inline_table(alteration.fields)}")
        if alteration.date_submitted is not None:
            lines.append(f"date_submitted = {alteration.date_submitted.isoformat()}")
        if alteration.date_processed is not None:
            lines.append(f"date_processed = {alteration.date_processed.isoformat()}")
        lines.append(f"sequence = {alteration.sequence}")
        lines.append("")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines).rstrip() + "\n")
    logger.info("wrote {}", dest)
    return dest


def transcribe(
    pdf: Path, dest: Path, work_dir: Path, *, model: str = DEFAULT_MODEL
) -> Path:
    """Render, transcribe, stamp, write. `work_dir` receives the page images
    (gitignored under raw/transcribe)."""
    pages = render_pages(pdf, work_dir / pdf.stem)
    logger.info(
        "{}: {} pages rendered; asking Claude ({})", pdf.name, len(pages), model
    )
    override = stamp(call_claude(pages, model=model), model=model, pages=len(pages))
    logger.info(
        "{}: {} interests, {} alterations",
        pdf.name,
        len(override.interests),
        len(override.alterations),
    )
    return write_override(override, dest)
