"""Senate ingest: an undocumented JSON API behind the register's React app.

`queryStatements` lists every senator with an APH person id (`cdapId`) and a
"last updated" stamp; `getSenatorStatement?cdapid=` returns one senator's full
statement, keyed by the same fourteen categories as `schema.SENATE_CATEGORIES`.
Both endpoints 403 without a browser user agent and an APH origin, hence
`fetch.client(Origin=...)`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from bs4 import BeautifulSoup
from loguru import logger

from peculiar_interests import fetch as fetchlib
from peculiar_interests import paths, store
from peculiar_interests.schema import (
    SENATE_CATEGORIES,
    SENATE_FIELDS,
    Alteration,
    AlterationKind,
    Category,
    Chamber,
    Extraction,
    ExtractionMethod,
    Holder,
    Interest,
    Source,
    Statement,
    is_nil,
)

BASE_URL = "https://pbs-apim-aqcdgxhvaug7f8em.z01.azurefd.net/api"
INDEX_URL = (
    f"{BASE_URL}/queryStatements"
    "?currentPage=1&pageSize=500&sortBy=senator&sortDirection=ascending"
)


def _statement_url(cdap_id: str) -> str:
    return f"{BASE_URL}/getSenatorStatement?cdapid={cdap_id}"


def _write_and_track(path: Path, payload: object) -> bool:
    """Write `payload` as JSON and report whether the file's content changed."""
    before = path.read_text() if path.exists() else None
    store.write_json(path, payload)
    return before != path.read_text()


def fetch(parliament: int = 48) -> list[str]:
    """Fetch the Senate index and every senator's statement for `parliament`.

    Writes the index to `paths.raw_index(SENATE, parliament)` and one raw
    statement per senator to `paths.raw_dir(...)/{cdapId}.json`. Returns the
    aph_ids whose statement file content changed (new or edited).
    """
    index_path = paths.raw_index(Chamber.SENATE, parliament)
    previous: dict[str, str] = {}
    if index_path.exists():
        previous = json.loads(index_path.read_text())["fetched_at"]

    with fetchlib.client(Origin="https://www.aph.gov.au") as http:
        response = http.get(INDEX_URL)
        response.raise_for_status()
        payload = response.json()
        entries = sorted(
            payload["statementOfRegisterableInterests"], key=lambda e: e["cdapId"]
        )
        logger.info("senate index: {} senators", len(entries))

        changed: list[str] = []
        for entry in entries:
            cdap_id = entry["cdapId"]
            response = http.get(_statement_url(cdap_id))
            response.raise_for_status()
            statement_payload = response.json()
            dest = paths.raw_dir(Chamber.SENATE, parliament) / f"{cdap_id}.json"
            if _write_and_track(dest, statement_payload):
                changed.append(cdap_id)

        store.write_json(
            index_path,
            {
                "fetched_at": fetchlib.fetched_at_by_id(
                    previous, [e["cdapId"] for e in entries], changed, fetchlib.now()
                ),
                "parliament": parliament,
                "source_url": INDEX_URL,
                "entries": entries,
            },
        )
        logger.info(
            "senate fetch: {} of {} statements changed", len(changed), len(entries)
        )
        return changed


def _parse_us_date(value: str | None) -> date | None:
    """`lodgementDate` on a statement, e.g. "8/19/2025 12:00:00 AM"."""
    if not value:
        return None
    return datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p").replace(tzinfo=UTC).date()


def _parse_iso_date(value: str | None) -> date | None:
    """An ISO timestamp, optionally UTC ("...Z"). Takes the date part as-is,
    with no timezone conversion — the site treats alteration dates as dates,
    not instants."""
    if not value:
        return None
    return datetime.fromisoformat(value).date()


def _split_name(name: str) -> tuple[str, str]:
    """ "Pocock, David" -> ("Pocock", "David")."""
    family, _, given = name.partition(",")
    return family.strip(), given.strip()


def _clean_notes(html: str | None) -> list[str]:
    if not html or not html.strip():
        return []
    text = BeautifulSoup(html, "lxml").get_text(separator=" ")
    collapsed = " ".join(text.split())
    return [collapsed] if collapsed else []


def _alteration_kind(value: str) -> AlterationKind:
    if value == "Addition":
        return AlterationKind.ADDITION
    if value == "Deletion":
        return AlterationKind.DELETION
    raise ValueError(f"unknown senate alterationType {value!r}")


def _map_interest(category: Category, item: dict) -> Interest | None:
    fields: dict[str, str] = {}
    for api_field, value in item.items():
        if api_field == "id":
            continue
        canonical = SENATE_FIELDS.get(api_field)
        if canonical is None:
            raise ValueError(
                f"unknown senate interest field {api_field!r} in {category}"
            )
        if canonical == "company" and category is Category.TRUSTS:
            canonical = "name"
        if is_nil(value):
            continue
        fields[canonical] = value.strip() if isinstance(value, str) else value
    if not fields:
        return None
    return Interest(
        category=category,
        holder=Holder.UNSPECIFIED,
        fields=fields,
        source_id=item.get("id"),
    )


def parse_statement(
    index_entry: dict,
    raw: dict,
    *,
    parliament: int,
    raw_path: str,
    sha256: str,
    fetched_at: datetime,
) -> Statement:
    """Map one `getSenatorStatement` response to a `Statement`.

    `index_entry` is this senator's row from the committed index (for
    `cdapId`, `name`, `title`, `lastDateUpdated`, falling back to
    `lodgmentDate`); everything else comes from `raw`.
    """
    stmt = raw["senatorInterestStatement"]
    aph_id = index_entry["cdapId"]
    family_name, given_names = _split_name(index_entry["name"])
    title = index_entry.get("title") or ""
    honorific = title if title.strip() else None

    interests: list[Interest] = []
    # Alterations are ordered by the date they were made, then by the form's
    # item order, so the sequence is canonical whatever key order the raw JSON
    # happens to have.
    pending: list[tuple[date | None, int, dict, Category]] = []
    for form_index, (api_key, category) in enumerate(SENATE_CATEGORIES.items()):
        block = raw.get(api_key) or {}
        for item in block.get("interests", []):
            interest = _map_interest(category, item)
            if interest is not None:
                interests.append(interest)
        for alteration in block.get("alterations", []):
            pending.append(
                (
                    _parse_iso_date(alteration.get("createdOn")),
                    form_index,
                    alteration,
                    category,
                )
            )
    pending.sort(key=lambda t: (t[0] or date.min, t[1], t[2].get("id") or ""))
    alterations = [
        Alteration(
            kind=_alteration_kind(alteration["alterationType"]),
            category=category,
            holder=Holder.UNSPECIFIED,
            details=alteration["details"],
            date_submitted=made,
            sequence=sequence,
            source_id=alteration.get("id"),
        )
        for sequence, (made, _, alteration, category) in enumerate(pending, start=1)
    ]

    return Statement(
        aph_id=aph_id,
        chamber=Chamber.SENATE,
        parliament=parliament,
        family_name=family_name,
        given_names=given_names,
        display_name=index_entry["name"],
        honorific=honorific,
        party=stmt.get("senatorParty") or None,
        state=stmt.get("electorateState") or None,
        date_lodged=_parse_us_date(stmt.get("lodgementDate"))
        or _parse_iso_date(index_entry.get("lodgmentDate")),
        last_updated=_parse_iso_date(index_entry.get("lastDateUpdated")),
        interests=interests,
        alterations=alterations,
        notes=_clean_notes(stmt.get("statementNotes")),
        source=Source(
            kind="senate-api",
            url=_statement_url(aph_id),
            sha256=sha256,
            fetched_at=fetched_at,
            raw_path=raw_path,
        ),
        extraction=Extraction(method=ExtractionMethod.SENATE_API, version=1),
    )


def parse(parliament: int = 48) -> list[Statement]:
    """Parse every committed Senate statement for `parliament` from `raw/`,
    write each to `data/`, and return them."""
    index_payload = json.loads(paths.raw_index(Chamber.SENATE, parliament).read_text())
    fetched_at = index_payload["fetched_at"]
    statements: list[Statement] = []
    for entry in index_payload["entries"]:
        aph_id = entry["cdapId"]
        raw_file = paths.raw_dir(Chamber.SENATE, parliament) / f"{aph_id}.json"
        raw = json.loads(raw_file.read_text())
        statement = parse_statement(
            entry,
            raw,
            parliament=parliament,
            raw_path=paths.relative(raw_file),
            sha256=fetchlib.sha256_of(raw_file),
            fetched_at=datetime.fromisoformat(fetched_at[aph_id]),
        )
        store.write_statement(statement)
        statements.append(statement)
    logger.info("senate parse: {} statements", len(statements))
    return statements
