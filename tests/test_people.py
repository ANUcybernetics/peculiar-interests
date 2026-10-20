from pathlib import Path

import pytest

from peculiar_interests import paths, people, store
from peculiar_interests.schema import Chamber


def test_read_csv_drops_an_empty_trailing_field(tmp_path: Path) -> None:
    path = tmp_path / "reps.csv"
    path.write_text('Surname,First Name\r\n"Farley","David",\r\n"Ley","Sussan",\r\n')
    assert people.read_csv(path) == [
        {"Surname": "Farley", "First Name": "David"},
        {"Surname": "Ley", "First Name": "Sussan"},
    ]


def test_read_csv_raises_on_data_beyond_the_header(tmp_path: Path) -> None:
    path = tmp_path / "reps.csv"
    path.write_text("Surname,First Name\nFarley,David,Farrer\n")
    with pytest.raises(ValueError, match="unexpected extra fields"):
        people.read_csv(path)


def _house_entry(aph_id: str, family: str, given: str, electorate: str) -> dict:
    return {
        "aph_id": aph_id,
        "family_name": family,
        "given_names": given,
        "electorate": electorate,
        "state": "NSW",
        "honorific": "Mr",
    }


def test_build_marks_a_replaced_member_as_former(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "ROSTER", tmp_path / "raw" / "roster")
    monkeypatch.setattr(paths, "OVERRIDES", tmp_path / "overrides")
    paths.ROSTER.mkdir(parents=True)
    header = "Surname,First Name,Other Name,Electorate,State,Political Party,Gender\n"
    (paths.ROSTER / "reps.csv").write_text(
        header + "Farley,David,,Farrer,NSW,ON,Male\n"
    )
    (paths.ROSTER / "senators.csv").write_text(header)
    store.write_json(
        paths.raw_index(Chamber.HOUSE, 48),
        {
            "entries": [
                _house_entry("62329", "Farley", "David", "Farrer"),
                _house_entry("00AMN", "Ley", "Sussan", "Farrer"),
                _house_entry("GHOST", "Nobody", "Some", "Nowhere"),
            ]
        },
    )
    override = paths.person_override_path("00AMN")
    override.parent.mkdir(parents=True)
    override.write_text('party_code = "LP"\ngender = "Female"\n')

    by_id = {p.aph_id: p for p in people.build(48)}

    assert by_id["62329"].current
    assert not by_id["00AMN"].current
    assert by_id["00AMN"].party == "Liberal Party of Australia"
    assert by_id["00AMN"].gender == "Female"
    # Nobody on the roster holds Nowhere, so this is a mismatch, not a departure.
    assert by_id["GHOST"].current
