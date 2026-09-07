"""Tests for the House ingest path. No network access; the `live` tests that
hit aph.gov.au are marked and deselected by default."""

from __future__ import annotations

from pathlib import Path

import pytest

from pollie_watch import fetch, house, paths, store
from pollie_watch.schema import (
    AlterationKind,
    Category,
    Chamber,
    ExtractionMethod,
    Holder,
)

FIXTURES = Path(__file__).parent / "fixtures" / "house"


# --- parse_index -------------------------------------------------------


def test_parse_index_counts_and_kinds() -> None:
    html = (FIXTURES / "index.html").read_text()
    entries = house.parse_index(html)
    assert len(entries) == 151
    assert sum(1 for e in entries if e["kind"] == "static") == 4
    assert all(e["kind"] in ("static", "api") for e in entries)
    assert all((e["aph_id"] is not None) == (e["kind"] == "api") for e in entries)


def test_parse_index_static_entry() -> None:
    entries = house.parse_index((FIXTURES / "index.html").read_text())
    albanese = next(e for e in entries if e["family_name"] == "Albanese")
    assert albanese["kind"] == "static"
    assert albanese["aph_id"] is None
    assert albanese["electorate"] == "Grayndler"
    assert albanese["state"] == "NSW"
    assert albanese["honorific"] == "Hon"
    assert albanese["given_names"] == "Anthony"


def test_parse_index_api_entry() -> None:
    entries = house.parse_index((FIXTURES / "index.html").read_text())
    abdo = next(e for e in entries if e["family_name"] == "Abdo")
    assert abdo["aph_id"] == "316915"
    assert abdo["kind"] == "api"
    assert abdo["last_updated"] == "2025-10-10"
    assert abdo["url"] == (
        "https://interests-register-api-public.aph.gov.au/api/members/316915/statement/48"
    )


def test_parse_index_double_honorific() -> None:
    entries = house.parse_index((FIXTURES / "index.html").read_text())
    aly = next(e for e in entries if e["family_name"] == "Aly")
    assert aly["honorific"] == "Hon Dr"
    assert aly["given_names"] == "Anne"


def test_parse_index_missing_honorific_and_state() -> None:
    """Two rows in the fixture have no honorific and no state suffix at all."""
    entries = house.parse_index((FIXTURES / "index.html").read_text())
    obrien = next(e for e in entries if e["given_names"] == "Llewellyn")
    assert obrien["family_name"] == "O'Brien"
    assert obrien["honorific"] is None
    assert obrien["electorate"] == "Wide Bay"
    assert obrien["state"] is None


# --- parse_pdf: Abdo (statement + one notification page) -----------------


@pytest.fixture(scope="module")
def abdo():
    return house.parse_pdf(FIXTURES / "316915.pdf")


def test_abdo_has_text_layer(abdo) -> None:
    assert abdo.has_text_layer is True


def test_abdo_identity(abdo) -> None:
    assert abdo.family_name == "Abdo"
    assert abdo.given_names == "Basem"


def test_abdo_date_lodged(abdo) -> None:
    assert abdo.date_lodged is not None
    assert abdo.date_lodged.isoformat() == "2025-08-18"


def test_abdo_real_estate(abdo) -> None:
    entries = [i for i in abdo.interests if i.category == Category.REAL_ESTATE]
    assert len(entries) == 1
    assert entries[0].holder == Holder.SELF
    assert entries[0].fields == {"location": "Greenvale, VIC", "purpose": "Residential"}


def test_abdo_liabilities(abdo) -> None:
    entries = [i for i in abdo.interests if i.category == Category.LIABILITIES]
    assert any(
        i.fields.get("nature") == "Credit Card"
        and i.fields.get("creditor") == "Commonwealth Bank of Australia"
        for i in entries
    )


def test_abdo_accounts(abdo) -> None:
    """3 self entries + 4 spouse entries, verified against the raw table."""
    entries = [i for i in abdo.interests if i.category == Category.ACCOUNTS]
    assert len(entries) == 7
    assert sum(1 for i in entries if i.holder == Holder.SELF) == 3
    assert sum(1 for i in entries if i.holder == Holder.SPOUSE) == 4


def test_abdo_other_assets(abdo) -> None:
    """Vehicle plus three superannuation/digital-currency entries, all self."""
    entries = [i for i in abdo.interests if i.category == Category.OTHER_ASSETS]
    assert len(entries) == 4
    natures = {i.fields["nature"] for i in entries}
    assert "Vehicle" in natures


def test_abdo_memberships(abdo) -> None:
    entries = [i for i in abdo.interests if i.category == Category.MEMBERSHIPS]
    organisations = {i.fields["organisation"] for i in entries}
    assert "Community and Public Sector Union" in organisations


def test_abdo_alterations_inline_notification(abdo) -> None:
    """The notification immediately after item 14 shares the statement's own
    Submitted/Processed dates (2025-08-18)."""
    same_day = [
        a
        for a in abdo.alterations
        if a.date_submitted and a.date_submitted.isoformat() == "2025-08-18"
    ]
    additions = [a for a in same_day if a.kind == AlterationKind.ADDITION]
    deletions = [a for a in same_day if a.kind == AlterationKind.DELETION]

    th_additions = {
        a.details for a in additions if a.category == Category.TRAVEL_HOSPITALITY
    }
    assert th_additions == {
        "Qantas Chairmans Lounge membership",
        "Virgin Australia Beyond membership",
    }

    gift_additions = [a for a in additions if a.category == Category.GIFTS]
    assert len(gift_additions) == 1
    assert "ETU" in gift_additions[0].details
    assert "$620.40" in gift_additions[0].details

    oa_deletions = [a for a in deletions if a.category == Category.OTHER_ASSETS]
    assert len(oa_deletions) == 3
    for a in same_day:
        assert a.date_processed is not None
        assert a.date_processed.isoformat() == "2025-08-18"


def test_abdo_alterations_later_notification(abdo) -> None:
    later = [
        a
        for a in abdo.alterations
        if a.date_submitted and a.date_submitted.isoformat() == "2025-10-10"
    ]
    assert len(later) == 1
    assert later[0].kind == AlterationKind.ADDITION
    assert later[0].category == Category.OTHER_INTERESTS
    assert later[0].holder == Holder.SPOUSE
    assert later[0].date_processed.isoformat() == "2025-10-12"


def test_abdo_alteration_sequence_is_gapless(abdo) -> None:
    sequences = [a.sequence for a in abdo.alterations]
    assert sequences == list(range(1, len(sequences) + 1))


# --- parse_pdf: Aldred (4 notifications) ----------------------------------


@pytest.fixture(scope="module")
def aldred():
    return house.parse_pdf(FIXTURES / "11788.pdf")


def test_aldred_real_estate(aldred) -> None:
    entries = [i for i in aldred.interests if i.category == Category.REAL_ESTATE]
    assert len(entries) == 2
    assert all(i.holder == Holder.SELF for i in entries)
    assert entries[0].fields == {"location": "Warragul", "purpose": "Residential home."}
    assert entries[1].fields == {
        "location": "Port Melbourne",
        "purpose": "Investment property.",
    }


def test_aldred_notification_dates(aldred) -> None:
    """4 notifications: the inline one (empty, 2025-08-12) plus three more."""
    processed_dates = sorted(
        {a.date_processed.isoformat() for a in aldred.alterations if a.date_processed}
    )
    assert processed_dates == ["2026-01-13", "2026-02-12", "2026-08-17"]
    assert aldred.date_lodged.isoformat() == "2025-08-12"


def test_aldred_last_alteration_is_gifts_national_press_club(aldred) -> None:
    last = max(aldred.alterations, key=lambda a: a.sequence)
    assert last.category == Category.GIFTS
    assert last.kind == AlterationKind.ADDITION
    assert "National Press Club" in last.details
    assert last.date_processed.isoformat() == "2026-08-17"


# --- parse_pdf: Butler / HWK (20 pages, spouse rows, 6 notifications) -----


@pytest.fixture(scope="module")
def butler():
    return house.parse_pdf(FIXTURES / "HWK.pdf")


def test_butler_identity(butler) -> None:
    assert butler.family_name == "Butler"
    assert butler.given_names == "Mark"


def test_butler_spouse_real_estate(butler) -> None:
    entries = [
        i
        for i in butler.interests
        if i.category == Category.REAL_ESTATE and i.holder == Holder.SPOUSE
    ]
    assert len(entries) == 1
    assert entries[0].fields == {
        "location": "Grange, South Australia",
        "purpose": "Residential",
    }


def test_butler_spouse_accounts(butler) -> None:
    entries = [
        i
        for i in butler.interests
        if i.category == Category.ACCOUNTS and i.holder == Holder.SPOUSE
    ]
    assert len(entries) == 1
    assert entries[0].fields["institution"] == "ING, Beyond Bank"


def test_butler_six_notifications(butler) -> None:
    """The inline notification after item 14 is empty; six further
    NOTIFICATION OF ALTERATION(S) pages each contribute at least one
    alteration."""
    processed_dates = {
        a.date_processed.isoformat() for a in butler.alterations if a.date_processed
    }
    assert len(processed_dates) == 6


# --- parse_pdf: unrecognised layout raises --------------------------------


def test_parse_pdf_raises_on_table_count_mismatch(monkeypatch) -> None:
    """A real fixture, but with the expected item-table count tampered with,
    exercises the same guard a genuine layout change would trip."""
    monkeypatch.setattr(
        house,
        "_STATEMENT_TABLE_SEQUENCE",
        [*house._STATEMENT_TABLE_SEQUENCE, (Category.OTHER_INTERESTS, None)],
    )
    with pytest.raises(ValueError, match="expected 16"):
        house.parse_pdf(FIXTURES / "316915.pdf")


def test_parse_pdf_raises_on_unrecognised_column_header(monkeypatch) -> None:
    monkeypatch.setattr(house, "HOUSE_COLUMNS", {})
    with pytest.raises(ValueError, match="unrecognised column header"):
        house.parse_pdf(FIXTURES / "316915.pdf")


# --- overrides -------------------------------------------------------------


def test_override_applied(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "OVERRIDES", tmp_path / "overrides")

    raw_dir = paths.raw_dir(Chamber.HOUSE, 48)
    raw_dir.mkdir(parents=True)
    (raw_dir / "TEST1.pdf").write_bytes(b"%PDF-1.4 not a real statement")

    store.write_json(
        paths.raw_index(Chamber.HOUSE, 48),
        {
            "fetched_at": fetch.now().isoformat(),
            "parliament": 48,
            "source_url": house.SOURCE_URL,
            "entries": [
                {
                    "aph_id": "TEST1",
                    "display_name": "Testperson, Sam",
                    "family_name": "Testperson",
                    "given_names": "Sam",
                    "honorific": "Mr",
                    "electorate": "Testland",
                    "state": "ACT",
                    "last_updated": "2026-01-01",
                    "url": "https://example.org/TEST1.pdf",
                    "kind": "api",
                }
            ],
        },
    )

    override_path = paths.override_path(Chamber.HOUSE, 48, "TEST1")
    override_path.parent.mkdir(parents=True)
    # `date_lodged` must precede the `[extraction]` table header: TOML keys
    # after a table header belong to that table regardless of blank lines.
    override_path.write_text(
        """
date_lodged = 2026-01-05

[extraction]
method = "manual"
notes = ["confirmed by hand"]

[[interests]]
category = "gifts"
holder = "self"
fields = { details = "A pen." }
"""
    )

    statements = house.parse(48)
    assert len(statements) == 1
    statement = statements[0]
    assert statement.aph_id == "TEST1"
    assert statement.extraction.method == ExtractionMethod.MANUAL
    assert statement.date_lodged is not None
    assert statement.date_lodged.isoformat() == "2026-01-05"
    assert len(statement.interests) == 1
    assert statement.interests[0].fields["details"] == "A pen."
    # identity/source fields still come from the stub, not the override
    assert statement.family_name == "Testperson"
    assert statement.electorate == "Testland"

    assert paths.statement_path(Chamber.HOUSE, 48, "TEST1").exists()


# --- parse_pdf: cells that disagree, tables that spill over a page ----------


def test_line_break_inside_a_cell_is_merged_not_split() -> None:
    """Freelander typed a line break inside a trust name; the neighbouring
    columns have one entry, so the name is merged rather than split into a
    phantom second trust, and the statement says so."""
    parsed = house.parse_pdf(FIXTURES / "265979.pdf")
    trusts = [i for i in parsed.interests if i.category is Category.TRUSTS]
    assert {t.fields["name"] for t in trusts} == {"Pebema P/L Superannuation Fund"}
    assert any("merged onto the shortest column" in n for n in parsed.notes)


def test_table_spilling_onto_the_next_page_continues_the_row() -> None:
    """King's alteration tables run over page breaks, leaving header-less
    fragments with blank leading cells; they extend the open row instead of
    aborting the parse."""
    parsed = house.parse_pdf(FIXTURES / "102376.pdf")
    assert parsed.has_text_layer
    assert len(parsed.alterations) > 150
    assert any("continued onto page" in n for n in parsed.notes)
    details = " ".join(a.details for a in parsed.alterations)
    assert "Seven West Media" in details
