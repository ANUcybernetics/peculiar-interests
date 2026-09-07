"""Senate ingest tests against the committed fixtures (no network)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from pollie_watch import fetch, paths, senate, store
from pollie_watch.schema import AlterationKind, Category

FIXTURES = Path(__file__).parent / "fixtures" / "senate"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _entry(index: dict, cdap_id: str) -> dict:
    return next(
        e for e in index["statementOfRegisterableInterests"] if e["cdapId"] == cdap_id
    )


def _parse(cdap_id: str):
    index = _load("index.json")
    raw = _load(f"{cdap_id}.json")
    return senate.parse_statement(
        _entry(index, cdap_id),
        raw,
        parliament=48,
        raw_path=f"raw/senate/48/{cdap_id}.json",
        sha256="0" * 64,
        fetched_at=datetime(2026, 9, 7, tzinfo=UTC),
    )


def test_parse_pocock():
    stmt = _parse("256136")

    assert stmt.aph_id == "256136"
    assert stmt.chamber.value == "senate"
    assert stmt.family_name == "Pocock"
    assert stmt.given_names == "David"
    assert stmt.display_name == "Pocock, David"
    assert stmt.honorific == "Senator"
    assert stmt.party == "Independent"
    assert stmt.state == "Australian Capital Territory"
    assert stmt.date_lodged == date(2025, 8, 19)
    assert stmt.last_updated == date(2026, 7, 24)

    real_estate = stmt.interests_in(Category.REAL_ESTATE)
    assert len(real_estate) == 2
    assert {i.fields["location"] for i in real_estate} == {
        "Canberra, ACT",
        "Marmion, WA",
    }
    canberra = next(i for i in real_estate if i.fields["location"] == "Canberra, ACT")
    assert canberra.fields["purpose"] == "Residential"

    deletions = [
        a
        for a in stmt.alterations_in(Category.REAL_ESTATE)
        if a.kind == AlterationKind.DELETION
    ]
    assert len(deletions) == 1
    assert deletions[0].details == "Sold house in Canberra, ACT"
    assert deletions[0].date_submitted == date(2026, 7, 23)

    assert len(stmt.notes) == 1
    assert "trust" in stmt.notes[0].lower()
    assert "<" not in stmt.notes[0]

    trusts = stmt.interests_in(Category.TRUSTS)
    assert len(trusts) == 1
    assert trusts[0].fields == {
        "name": "David Pocock Pty Ltd",
        "nature": "Share investment",
        "beneficial_interest": "Spouse",
        "role": "trustee",
    }

    # partnerships/investments/otherInterest are empty for Pocock.
    assert stmt.interests_in(Category.PARTNERSHIPS) == []
    assert stmt.interests_in(Category.INVESTMENTS) == []


def test_parse_wong():
    stmt = _parse("00AOU")

    assert stmt.aph_id == "00AOU"
    assert stmt.family_name == "Wong"
    assert stmt.given_names == "Penny"
    assert stmt.honorific == "Senator the Hon."
    assert stmt.party == "Australian Labor Party"
    assert stmt.state == "South Australia"
    assert stmt.date_lodged == date(2025, 8, 18)
    assert stmt.notes == []

    real_estate = stmt.interests_in(Category.REAL_ESTATE)
    assert len(real_estate) == 3

    accounts = stmt.interests_in(Category.ACCOUNTS)
    assert len(accounts) == 3
    assert all(i.fields["institution"] == "ANZ" for i in accounts)

    memberships = stmt.alterations_in(Category.OTHER_INTERESTS)
    additions = [a for a in memberships if a.kind == AlterationKind.ADDITION]
    deletions = [a for a in memberships if a.kind == AlterationKind.DELETION]
    assert len(additions) == 6
    assert len(deletions) == 2

    # sequence is a single counter across the whole statement, starting at 1.
    all_sequences = [a.sequence for a in stmt.alterations]
    assert all_sequences == sorted(all_sequences)
    assert all_sequences[0] == 1


def test_round_trip(tmp_path, monkeypatch):
    # `paths.relative` (used for logging) resolves against `paths.ROOT`, so it
    # has to move with `DATA` for a tmp_path outside the repo to work.
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path)
    stmt = _parse("00AOU")
    path = store.write_statement(stmt)
    assert store.read_statement(path) == stmt


@pytest.mark.live
def test_live_index_fetch():
    with fetch.client(Origin="https://www.aph.gov.au") as http:
        response = http.get(senate.INDEX_URL)
        response.raise_for_status()
        payload = response.json()
    assert payload["wasSuccessful"] is True
    assert payload["rowCount"] > 60
