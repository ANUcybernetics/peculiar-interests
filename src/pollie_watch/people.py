"""The roster: one `Person` per parliamentarian, joining APH's own member and
senator CSVs (party, gender, electorate) to the register indexes (APH id, which
the CSVs lack). Written to `data/people.json`.

The CSVs are the "address labels and CSV files" APH publishes for contacting
members; they change URL (a `rev`/`hash` query) whenever reissued, so `fetch`
scrapes the listing page for the current links rather than hard-coding them.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from loguru import logger

from pollie_watch import fetch, paths, store
from pollie_watch.schema import Chamber, Person

LISTING_URL = (
    "https://www.aph.gov.au/Senators_and_Members/Contacting_Senators_and_Members/"
    "Address_labels_and_CSV_files"
)
ROSTER_FILES = {
    "reps.csv": re.compile(r"FamilynameRepsCSV\.csv", re.IGNORECASE),
    "senators.csv": re.compile(r"Senators/allsenel\.csv", re.IGNORECASE),
}

PARTY_NAMES: dict[str, str] = {
    "ALP": "Australian Labor Party",
    "LP": "Liberal Party of Australia",
    "LNP": "Liberal National Party of Queensland",
    "NATS": "The Nationals",
    "CLP": "Country Liberal Party",
    "AG": "Australian Greens",
    "IND": "Independent",
    "PHON": "Pauline Hanson's One Nation",
    "ON": "One Nation",
    "KAP": "Katter's Australian Party",
    "CA": "Centre Alliance",
    "UAP": "United Australia Party",
    "JLN": "Jacqui Lambie Network",
    "AV": "Australia's Voice",
}

STATE_CODES: dict[str, str] = {
    "New South Wales": "NSW",
    "Victoria": "VIC",
    "Queensland": "QLD",
    "Western Australia": "WA",
    "South Australia": "SA",
    "Tasmania": "TAS",
    "Australian Capital Territory": "ACT",
    "Northern Territory": "NT",
}


def state_code(value: str | None) -> str | None:
    if not value:
        return None
    return STATE_CODES.get(value, value.upper())


def fold(name: str) -> str:
    """Case- and accent-insensitive key for matching names across sources."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", ascii_name.lower())


def fetch_roster() -> list[Path]:
    """Download the current member and senator CSVs into `raw/roster/`."""
    with fetch.client() as http:
        page = http.get(LISTING_URL)
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "lxml")
        written: list[Path] = []
        for filename, pattern in ROSTER_FILES.items():
            link = next(
                (
                    str(a["href"])
                    for a in soup.find_all("a", href=True)
                    if pattern.search(str(a["href"]))
                ),
                None,
            )
            if link is None:
                raise LookupError(f"{LISTING_URL} no longer links {filename}")
            dest = paths.ROSTER / filename
            fetch.download(http, link, dest)
            written.append(dest)
    return written


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [
            {k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(f)
        ]


def _roster_rows(chamber: Chamber) -> list[dict[str, str]]:
    filename = "reps.csv" if chamber is Chamber.HOUSE else "senators.csv"
    return read_csv(paths.ROSTER / filename)


def _index_entries(chamber: Chamber, parliament: int) -> list[dict]:
    path = paths.raw_index(chamber, parliament)
    if not path.exists():
        return []
    return json.loads(path.read_text())["entries"]


def _register_identity(
    chamber: Chamber, entry: dict
) -> tuple[str, str, str, str | None]:
    """(aph_id, family_name, given_names, electorate-or-state) from an index entry."""
    if chamber is Chamber.HOUSE:
        return (
            entry["aph_id"],
            entry["family_name"],
            entry["given_names"],
            entry["electorate"],
        )
    family, _, given = entry["name"].partition(",")
    return (
        entry["cdapId"],
        family.strip(),
        given.strip(),
        state_code(entry.get("state")),
    )


def _match(row: dict[str, str], chamber: Chamber, entries: list[dict]) -> dict | None:
    """Find the register entry for a roster row: surname plus electorate (House)
    or state (Senate), falling back to surname plus first name."""
    surname = fold(row["Surname"])
    place = row["Electorate"] if chamber is Chamber.HOUSE else row["State"]
    firsts = {
        fold(row["First Name"]),
        fold(row.get("Preferred Name") or row["First Name"]),
    }
    by_place = [
        e
        for e in entries
        if fold(_register_identity(chamber, e)[1]) == surname
        and fold(_register_identity(chamber, e)[3] or "") == fold(place)
    ]
    if len(by_place) == 1:
        return by_place[0]
    by_name = [
        e
        for e in entries
        if fold(_register_identity(chamber, e)[1]) == surname
        and fold(_register_identity(chamber, e)[2].split()[0]) in firsts
    ]
    return by_name[0] if len(by_name) == 1 else None


def build(parliament: int = 48) -> list[Person]:
    people: list[Person] = []
    for chamber in Chamber:
        entries = _index_entries(chamber, parliament)
        matched: set[str] = set()
        for row in _roster_rows(chamber):
            entry = _match(row, chamber, entries)
            aph_id = _register_identity(chamber, entry)[0] if entry else None
            if entry is None:
                logger.warning(
                    "{} {} {} has no register entry; roster only",
                    chamber.value,
                    row["First Name"],
                    row["Surname"],
                )
            else:
                matched.add(aph_id or "")
            party_code = row["Political Party"] or None
            people.append(
                Person(
                    aph_id=aph_id
                    or f"roster:{fold(row['Surname'])}-{fold(row['First Name'])}",
                    family_name=row["Surname"],
                    given_names=" ".join(
                        p for p in (row["First Name"], row["Other Name"]) if p
                    ),
                    preferred_name=row.get("Preferred Name") or None,
                    honorific=(row.get("Honorific") or row.get("Title") or None),
                    post_nominals=row.get("Post Nominals") or None,
                    gender=row.get("Gender") or None,
                    chamber=chamber,
                    party=PARTY_NAMES.get(party_code or "", party_code),
                    party_code=party_code,
                    state=row["State"] or None,
                    electorate=row.get("Electorate") or None,
                    parliaments=[parliament] if entry else [],
                    aph_url=f"https://www.aph.gov.au/Senators_and_Members/Parliamentarian?MPID={aph_id}"
                    if aph_id
                    else None,
                )
            )
        for entry in entries:
            aph_id, family, given, place = _register_identity(chamber, entry)
            if aph_id in matched:
                continue
            logger.warning(
                "{} {} {} is on the register but not the roster",
                chamber.value,
                given,
                family,
            )
            people.append(
                Person(
                    aph_id=aph_id,
                    family_name=family,
                    given_names=given,
                    honorific=entry.get("honorific") or entry.get("title") or None,
                    chamber=chamber,
                    party=entry.get("senatorParty") or None,
                    state=place if chamber is Chamber.SENATE else entry.get("state"),
                    electorate=place if chamber is Chamber.HOUSE else None,
                    parliaments=[parliament],
                    aph_url=f"https://www.aph.gov.au/Senators_and_Members/Parliamentarian?MPID={aph_id}",
                )
            )
    people.sort(key=lambda p: (fold(p.family_name), fold(p.given_names)))
    return people


def write(people: list[Person]) -> Path:
    return store.write_json(
        paths.DATA / "people.json", [p.model_dump(mode="json") for p in people]
    )
