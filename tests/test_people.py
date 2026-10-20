from pathlib import Path

import pytest

from peculiar_interests import people


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
