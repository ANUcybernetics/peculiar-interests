"""Repository layout. Every module resolves files through these so the tree is
defined once.

    raw/{chamber}/{parliament}/index.json   what the register index listed
    raw/house/{parliament}/{aph_id}.pdf     the fetched PDF, byte for byte
    raw/senate/{parliament}/{aph_id}.json   the API response, byte for byte
    raw/roster/*.csv                        APH's own member/senator lists
    data/{parliament}/{chamber}/{aph_id}.json   one Statement per person
    data/people.json                        the Person roster
    overrides/{parliament}/{chamber}/{aph_id}.toml  hand-confirmed statements
"""

from __future__ import annotations

from pathlib import Path

from pollie_watch.schema import Chamber

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "raw"
DATA = ROOT / "data"
OVERRIDES = ROOT / "overrides"
ROSTER = RAW / "roster"


def raw_dir(chamber: Chamber, parliament: int) -> Path:
    return RAW / chamber.value / str(parliament)


def raw_index(chamber: Chamber, parliament: int) -> Path:
    return raw_dir(chamber, parliament) / "index.json"


def data_dir(chamber: Chamber, parliament: int) -> Path:
    return DATA / str(parliament) / chamber.value


def statement_path(chamber: Chamber, parliament: int, aph_id: str) -> Path:
    return data_dir(chamber, parliament) / f"{aph_id}.json"


def override_path(chamber: Chamber, parliament: int, aph_id: str) -> Path:
    return OVERRIDES / str(parliament) / chamber.value / f"{aph_id}.toml"


def relative(path: Path) -> str:
    """Repo-relative POSIX path, for `Source.raw_path`."""
    return path.resolve().relative_to(ROOT).as_posix()
