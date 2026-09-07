from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from peculiar_interests import overrides, transcribe
from peculiar_interests.schema import (
    Alteration,
    AlterationKind,
    Category,
    Extraction,
    ExtractionMethod,
    Holder,
    Interest,
)

FIXTURES = Path(__file__).parent / "fixtures" / "house"


def test_generated_pdf_has_a_text_layer() -> None:
    assert transcribe.has_text_layer(FIXTURES / "316915.pdf")


def test_render_pages_writes_one_png_per_page(tmp_path: Path) -> None:
    pages = transcribe.render_pages(FIXTURES / "316915.pdf", tmp_path, dpi=40)
    assert len(pages) == 11
    assert all(p.suffix == ".png" and p.stat().st_size > 0 for p in pages)


def test_prompts_name_every_item_and_page(tmp_path: Path) -> None:
    system = transcribe.system_prompt()
    assert "14. other-interests" in system and "role" in system
    pages = [tmp_path / "page-01.png", tmp_path / "page-02.png"]
    user = transcribe.user_prompt(pages)
    assert str(pages[0].resolve()) in user and str(pages[1].resolve()) in user


def test_schema_is_the_override_schema() -> None:
    schema = overrides.Override.model_json_schema()
    assert "interests" in schema["properties"] and "alterations" in schema["properties"]
    json.dumps(schema)  # serialisable for --json-schema


def test_stamp_records_the_model_and_keeps_its_notes() -> None:
    raw = overrides.Override(
        extraction=Extraction(
            method=ExtractionMethod.MANUAL, notes=["page 3 partly illegible"]
        ),
    )
    stamped = transcribe.stamp(raw, model="opus", pages=7)
    assert stamped.extraction.method is ExtractionMethod.OCR
    assert stamped.extraction.notes[0].startswith(
        "Transcribed from 7 page images by Claude (opus)"
    )
    assert stamped.extraction.notes[1] == "page 3 partly illegible"


def test_write_override_round_trips(tmp_path: Path) -> None:
    override = overrides.Override(
        extraction=Extraction(method=ExtractionMethod.OCR, notes=['a "quoted" note']),
        date_lodged=date(2025, 8, 12),
        notes=["registrar note"],
        interests=[
            Interest(
                category=Category.REAL_ESTATE,
                holder=Holder.SELF,
                fields={"location": "Marrickville, NSW", "purpose": "Residential"},
            ),
            Interest(
                category=Category.TRUSTS,
                holder=Holder.SPOUSE,
                fields={"name": "A Trust", "role": "beneficiary"},
            ),
        ],
        alterations=[
            Alteration(
                kind=AlterationKind.ADDITION,
                category=Category.GIFTS,
                holder=Holder.SELF,
                details="Plaque from the Assyrian National Council",
                date_submitted=date(2026, 3, 4),
                date_processed=date(2026, 3, 6),
                sequence=1,
            ),
        ],
    )
    dest = transcribe.write_override(override, tmp_path / "x.toml")
    assert overrides.load(dest) == override
