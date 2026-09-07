"""House of Representatives ingest: the register index page and the
Aspose.Words-generated PDF statements behind it.

The index lists 151 members, one row each: a "last updated" date, a name cell
("Family, Honorific Given, Member for Electorate STATE"), and a link. 147
links are system-generated PDFs (`.../api/members/{aph_id}/statement/{parl}`)
that pdfplumber reads cleanly; a handful are handwritten scans hosted as
static files with no id in the URL, resolved once via `resolve_aph_id` and
cached in the index.

Every generated PDF follows the same template: a one-page identity/notes
header, then items 1-14 (item 2 has two sub-tables: beneficial interest and
trustee, both TRUSTS), then zero or more "Notification of alteration(s)"
sections -- the one immediately after item 14 is part of the original
statement (its Submitted Date is `date_lodged`); any further ones are
separate notifications with their own identity page. Every such section ends
in an ADDITION table, a DELETION table, and a Submitted/Processed date pair,
always on the page carrying the DELETION table.

Interest and alteration cells can hold several entries stacked as lines
(e.g. two real-estate holdings). A wrapped continuation of one entry sits
close to the line above it; a new entry sits further below. See
`_group_entries` for the measured thresholds and `_align_columns` for how
columns that disagree are reconciled.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pdfplumber
from bs4 import BeautifulSoup
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from pollie_watch import fetch as fetchlib
from pollie_watch import overrides, paths, store
from pollie_watch.schema import (
    HOUSE_COLUMNS,
    HOUSE_ITEMS,
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

SOURCE_URL = "https://www.aph.gov.au/Senators_and_Members/Members/Register"
SEARCH_URL = (
    "https://www.aph.gov.au/Senators_and_Members/Parliamentarian_Search_Results"
    "?q={surname}&mem=1&par=-1&gen=0&ps=12"
)
OPENAUSTRALIA_PEOPLE_CSV = (
    "https://raw.githubusercontent.com/openaustralia/openaustralia-parser/"
    "master/data/people.csv"
)

# --- Index parsing ------------------------------------------------------

_STATES = ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT")
_HONORIFICS = ("Hon Dr", "Hon", "Dr", "Mrs", "Ms", "Mr", "Miss")
_NAME_RE = re.compile(r"^(?P<namepart>.+?),\s*Member for\s+(?P<rest>.+)$")
_STATE_RE = re.compile(
    r"^(?P<electorate>.+?),?\s+(?P<state>" + "|".join(_STATES) + r")$"
)
_API_HREF_RE = re.compile(r"/api/members/([^/]+)/statement/")


def _parse_name(text: str) -> tuple[str, str | None, str, str, str | None]:
    """Split an index name cell into (family, honorific, given, electorate,
    state). Two known rows omit the honorific and the state entirely."""
    m = _NAME_RE.match(text)
    if not m:
        raise ValueError(f"unrecognised index name format: {text!r}")
    family, _, honorific_given = m.group("namepart").partition(",")
    family = family.strip()
    honorific_given = honorific_given.strip()
    honorific = None
    given = honorific_given
    for h in _HONORIFICS:
        if honorific_given == h or honorific_given.startswith(h + " "):
            honorific = h
            given = honorific_given[len(h) :].strip()
            break
    rest = m.group("rest").strip()
    sm = _STATE_RE.match(rest)
    if sm:
        electorate, state = sm.group("electorate").strip(), sm.group("state")
    else:
        electorate, state = rest, None
    return family, honorific, given, electorate, state


def parse_index(html: str) -> list[dict[str, Any]]:
    """Parse the register index page into one dict per member. Pure."""
    soup = BeautifulSoup(html, "lxml")
    entries: list[dict[str, Any]] = []
    for tr in soup.select("table.members-interests__table tr"):
        date_td = tr.find("td", class_="date")
        if date_td is None:
            continue
        link = tr.select_one("td.format a")
        name_td = date_td.find_next_sibling("td")
        if link is None or name_td is None:
            raise ValueError(f"unrecognised index row: {tr}")
        last_updated = (
            datetime.strptime(date_td.get_text(strip=True), "%d %B %Y")
            .replace(tzinfo=UTC)
            .date()
        )
        family, honorific, given, electorate, state = _parse_name(
            name_td.get_text(strip=True)
        )
        href = str(link["href"]).strip()
        kind = "static" if "static.aph.gov.au" in href else "api"
        aph_id = None
        if kind == "api":
            m = _API_HREF_RE.search(href)
            if not m:
                raise ValueError(f"unrecognised API href: {href}")
            aph_id = m.group(1)
        entries.append(
            {
                "aph_id": aph_id,
                "display_name": f"{family}, {given}",
                "family_name": family,
                "given_names": given,
                "honorific": honorific,
                "electorate": electorate,
                "state": state,
                "last_updated": last_updated.isoformat(),
                "url": href,
                "kind": kind,
            }
        )
    return entries


# --- aph_id resolution for the static-PDF members ------------------------

_MPID_RE = re.compile(r'Parliamentarian\?MPID=(\w+)"[^>]*>([^<]*)<')


def _resolve_from_search(
    http: httpx.Client, family_name: str, given_names: str
) -> str | None:
    response = http.get(SEARCH_URL.format(surname=family_name))
    response.raise_for_status()
    matches = {mpid: label.strip() for mpid, label in _MPID_RE.findall(response.text)}
    candidates = {mpid for mpid, label in matches.items() if family_name in label}
    if len(candidates) == 1:
        return candidates.pop()
    given_first = given_names.split()[0]
    narrowed = {mpid for mpid in candidates if given_first in matches[mpid]}
    return narrowed.pop() if len(narrowed) == 1 else None


def _resolve_from_openaustralia(
    http: httpx.Client, family_name: str, given_names: str
) -> str | None:
    response = http.get(OPENAUSTRALIA_PEOPLE_CSV)
    response.raise_for_status()
    given_first = given_names.split()[0].lower()
    for row in csv.DictReader(io.StringIO(response.text)):
        aph_id = (row.get("aph id") or "").strip()
        if not aph_id:
            continue
        haystack = f"{row.get('name', '')} {row.get('alt name', '')}".lower()
        if family_name.lower() in haystack and given_first in haystack:
            return aph_id
    return None


def resolve_aph_id(http: httpx.Client, family_name: str, given_names: str) -> str:
    """Resolve a static-PDF member's aph_id via the APH search page, falling
    back to OpenAustralia's people list (nicknames like "Bob" for "Robert"
    defeat the search page's exact-name matching more often than the CSV's
    alt-name column does)."""
    aph_id = _resolve_from_search(http, family_name, given_names)
    if aph_id is None:
        aph_id = _resolve_from_openaustralia(http, family_name, given_names)
    if aph_id is None:
        raise ValueError(f"could not resolve aph_id for {family_name}, {given_names}")
    return aph_id


# --- Fetching --------------------------------------------------------------


def _pdf_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _download_stable(http: httpx.Client, url: str, dest: Path) -> tuple[str, bool]:
    """Like `fetchlib.download`, but tolerant of an API that re-renders the same
    PDF with different bytes on every request: if the bytes changed but the
    extracted text didn't, keep the committed file so a nightly run doesn't
    churn the repo over nothing."""
    if not dest.exists():
        return fetchlib.download(http, url, dest)
    old_bytes = dest.read_bytes()
    response = http.get(url)
    response.raise_for_status()
    new_bytes = response.content
    if new_bytes == old_bytes:
        return hashlib.sha256(old_bytes).hexdigest(), False
    if _pdf_text(new_bytes) == _pdf_text(old_bytes):
        logger.debug(
            "{} bytes changed but text is identical, keeping committed copy", dest.name
        )
        return hashlib.sha256(old_bytes).hexdigest(), False
    dest.write_bytes(new_bytes)
    logger.info("wrote {} ({} bytes, content changed)", dest, len(new_bytes))
    return hashlib.sha256(new_bytes).hexdigest(), True


def fetch(parliament: int = 48) -> list[str]:
    """Fetch the index and every statement PDF for `parliament`. Writes
    `paths.raw_index` and one PDF per member under `paths.raw_dir`. Returns
    the aph_ids whose PDF content actually changed."""
    index_path = paths.raw_index(Chamber.HOUSE, parliament)
    cached_ids: dict[str, str] = {}
    if index_path.exists():
        old = json.loads(index_path.read_text())
        cached_ids = {
            e["display_name"]: e["aph_id"]
            for e in old.get("entries", [])
            if e.get("aph_id")
        }

    with fetchlib.client() as http:
        response = http.get(SOURCE_URL)
        response.raise_for_status()
        entries = parse_index(response.text)

        for entry in entries:
            if entry["aph_id"] is not None:
                continue
            cached = cached_ids.get(entry["display_name"])
            if cached:
                entry["aph_id"] = cached
                continue
            entry["aph_id"] = resolve_aph_id(
                http, entry["family_name"], entry["given_names"]
            )
            logger.info(
                "resolved aph_id {} for static-PDF member {}",
                entry["aph_id"],
                entry["display_name"],
            )

        store.write_json(
            index_path,
            {
                "fetched_at": fetchlib.now().isoformat(),
                "parliament": parliament,
                "source_url": SOURCE_URL,
                "entries": entries,
            },
        )

        raw_dir = paths.raw_dir(Chamber.HOUSE, parliament)
        changed: list[str] = []
        for entry in entries:
            dest = raw_dir / f"{entry['aph_id']}.pdf"
            _digest, wrote = _download_stable(http, entry["url"], dest)
            if wrote:
                changed.append(entry["aph_id"])
    return changed


# --- PDF parsing -------------------------------------------------------

# Wrapped-line leading measures ~12.0-12.1pt; distinct new entries measure
# ~15.0-16.1pt (single-line rows, e.g. two real-estate holdings) or
# ~30.1-30.2pt (rows where an earlier entry itself wrapped). 13.5pt sits with
# clear margin above the wrap cluster and below both entry clusters.
_WRAP_GAP_PT = 13.5

_HOLDER_LABELS = {
    "Self": Holder.SELF,
    "Spouse/ Partner": Holder.SPOUSE,
    "Dependent Children": Holder.DEPENDENT,
}

_SUBMITTED_RE = re.compile(r"Submitted Date:\s*(\d{2}/\d{2}/\d{4})")
_PROCESSED_RE = re.compile(
    r"Processed by Registrar of Members. Interests:\s*(\d{2}/\d{2}/\d{4})"
)
_ITEM_NUMBER_RE = re.compile(r"^(\d{1,2})\.")
# Every genuine Aspose-generated statement's first page carries this literal
# header. A scanned PDF may still carry a garbled OCR text layer of its own
# (stray characters, misread words) with plenty of characters but never this
# exact phrase, so a raw character-count threshold isn't reliable here.
_STATEMENT_MARKER = "Statement of Registrable Interests"

# Statement item tables appear in this fixed order on every generated PDF;
# item 2's two sub-tables both map to TRUSTS, distinguished by role.
_STATEMENT_TABLE_SEQUENCE: list[tuple[Category, str | None]] = [
    (Category.SHAREHOLDINGS, None),
    (Category.TRUSTS, "beneficiary"),
    (Category.TRUSTS, "trustee"),
    (Category.REAL_ESTATE, None),
    (Category.DIRECTORSHIPS, None),
    (Category.PARTNERSHIPS, None),
    (Category.LIABILITIES, None),
    (Category.INVESTMENTS, None),
    (Category.ACCOUNTS, None),
    (Category.OTHER_ASSETS, None),
    (Category.OTHER_INCOME, None),
    (Category.GIFTS, None),
    (Category.TRAVEL_HOSPITALITY, None),
    (Category.MEMBERSHIPS, None),
    (Category.OTHER_INTERESTS, None),
]


class ParsedForm(BaseModel):
    """What `parse_pdf` extracts from one statement PDF."""

    model_config = ConfigDict(frozen=True)

    has_text_layer: bool
    family_name: str | None = None
    given_names: str | None = None
    date_lodged: date | None = None
    interests: list[Interest] = Field(default_factory=list)
    alterations: list[Alteration] = Field(default_factory=list)
    # Anything a reader of the JSON should know about how this file was read
    # (a merged cell, a page-spanning row); surfaced as Extraction.notes.
    notes: list[str] = Field(default_factory=list)


class _RowState:
    """Carry-over between tables of one document: the holder of the row that
    was open when a page broke, and the last alteration item seen per holder,
    so a continuation table with blank leading cells can be attributed."""

    def __init__(self) -> None:
        self.last_holder: Holder | None = None
        self.last_item: dict[Holder, Category] = {}
        self.notes: list[str] = []


def _normalise(text: str | None) -> str:
    return " ".join((text or "").split())


def _row_holder(label: str, path: Path, page_index: int) -> Holder:
    normalised = _normalise(label)
    if normalised not in _HOLDER_LABELS:
        raise ValueError(
            f"{path.name} page {page_index + 1}: unrecognised holder label {label!r}"
        )
    return _HOLDER_LABELS[normalised]


def _cell_lines(
    page: Any, bbox: tuple[float, float, float, float] | None
) -> list[tuple[float, str]]:
    """Every line of text in one table cell, as (top, text), top to bottom."""
    if bbox is None:
        return []
    x0, top, x1, bottom = bbox
    words = page.crop((x0, top, x1, bottom)).extract_words()
    if not words:
        return []
    lines: list[tuple[float, list[str]]] = []
    for word in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        w_top = round(word["top"], 1)
        if lines and abs(w_top - lines[-1][0]) <= 3:
            lines[-1][1].append(word["text"])
        else:
            lines.append((w_top, [word["text"]]))
    return [(top_, " ".join(words_)) for top_, words_ in lines]


_LOWERCASE_WORD_RE = re.compile(r"^[a-z]+(?:[\s,.;:)]|$)")


def _reads_as_continuation(text: str) -> bool:
    """A line whose first word is all lowercase ("grandmother and my late") is
    the middle of a sentence, whatever the spacing says: some members' cells
    are set with wider leading than the form's own. Brand names with an inner
    capital (iShares, eToro) are not caught."""
    return bool(_LOWERCASE_WORD_RE.match(text))


def _group_entries(lines: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Merge wrapped continuation lines into entries by vertical spacing (see
    module-level threshold comment). Returns (top of the entry's first line,
    merged text), so a caller can align entries across sibling cells by
    position rather than assuming equal counts."""
    if not lines:
        return []
    entries: list[tuple[float, str]] = []
    entry_top, entry_text = lines[0]
    prev_top = entry_top
    for top_, text in lines[1:]:
        if top_ - prev_top > _WRAP_GAP_PT and not _reads_as_continuation(text):
            entries.append((entry_top, entry_text))
            entry_top, entry_text = top_, text
        else:
            entry_text += " " + text
        prev_top = top_
    entries.append((entry_top, entry_text))
    return entries


def _align_columns(
    column_entries: list[list[tuple[float, str]]],
) -> tuple[list[list[str]], bool]:
    """Give every column the same number of entries.

    Columns of one row normally agree, but a member who typed a line break
    inside a cell produces a column with one entry more than its neighbours,
    and by spacing alone that is indistinguishable from a genuine new row. The
    non-empty column with the fewest entries is taken as the spine (it can
    never invent a row), and every other column's entries are bucketed onto
    the spine entry whose top is nearest above them, joined with a space.
    Returns the aligned text columns and whether any merging happened.
    """
    non_empty = [c for c in column_entries if c]
    if not non_empty:
        return [[] for _ in column_entries], False
    counts = {len(c) for c in non_empty}
    if len(counts) == 1:
        return [[text for _t, text in c] for c in column_entries], False
    spine = min(non_empty, key=len)
    spine_tops = [top for top, _t in spine]
    aligned: list[list[str]] = []
    for column in column_entries:
        buckets = ["" for _ in spine]
        for top, text in column:
            index = max(0, sum(1 for st in spine_tops if st <= top + 2) - 1)
            buckets[index] = f"{buckets[index]} {text}".strip()
        aligned.append(buckets)
    return aligned, True


def _column_field_names(
    header_row: list[str | None], path: Path, page_index: int
) -> list[str]:
    field_names = []
    for raw in header_row[1:]:
        key = _normalise(raw)
        if key not in HOUSE_COLUMNS:
            raise ValueError(
                f"{path.name} page {page_index + 1}: unrecognised column header {key!r}"
            )
        field_names.append(HOUSE_COLUMNS[key])
    return field_names


def _row_holder_or_carry(
    label: str | None, state: _RowState, path: Path, page_index: int
) -> Holder:
    """The row's holder, or the carried one for a row whose label stayed on
    the previous page (a continuation table's leading cells are blank)."""
    if label is None or _normalise(label) == "":
        if state.last_holder is None:
            raise ValueError(
                f"{path.name} page {page_index + 1}: row with no holder and nothing to carry"
            )
        return state.last_holder
    holder = _row_holder(label, path, page_index)
    state.last_holder = holder
    return holder


def _interests_from_rows(
    page: Any,
    rows: list[tuple[Any, list[str | None]]],
    field_names: list[str],
    category: Category,
    role: str | None,
    path: Path,
    page_index: int,
    state: _RowState,
) -> list[Interest]:
    interests: list[Interest] = []
    for row_obj, row_text in rows:
        holder = _row_holder_or_carry(row_text[0], state, path, page_index)
        column_entries, merged = _align_columns(
            [_group_entries(_cell_lines(page, cell)) for cell in row_obj.cells[1:]]
        )
        if merged:
            state.notes.append(
                f"item {category.value} ({holder.value}): columns listed different "
                f"numbers of lines on page {page_index + 1}; lines were merged onto "
                "the shortest column rather than split into separate entries"
            )
        count = max((len(e) for e in column_entries), default=0)
        for i in range(count):
            fields = {}
            for field_name, entries in zip(field_names, column_entries, strict=True):
                value = entries[i] if i < len(entries) else ""
                if not is_nil(value):
                    fields[field_name] = value
            if not fields:
                continue
            if role is not None:
                fields["role"] = role
            interests.append(Interest(category=category, holder=holder, fields=fields))
    return interests


def _category_for_item(item_text: str, path: Path, page_index: int) -> Category:
    m = _ITEM_NUMBER_RE.match(item_text.strip())
    if not m:
        raise ValueError(
            f"{path.name} page {page_index + 1}: unrecognised alteration item {item_text!r}"
        )
    number = int(m.group(1))
    if number not in HOUSE_ITEMS:
        raise ValueError(
            f"{path.name} page {page_index + 1}: unknown item number {number} in {item_text!r}"
        )
    return HOUSE_ITEMS[number]


def _alteration_entries_from_rows(
    page: Any,
    rows: list[tuple[Any, list[str | None]]],
    path: Path,
    page_index: int,
    state: _RowState,
) -> list[tuple[Holder, Category, str]]:
    results: list[tuple[Holder, Category, str]] = []
    for row_obj, row_text in rows:
        holder = _row_holder_or_carry(row_text[0], state, path, page_index)
        item_entries = _group_entries(_cell_lines(page, row_obj.cells[1]))
        detail_entries = _group_entries(_cell_lines(page, row_obj.cells[2]))
        if not detail_entries:
            continue
        if not item_entries:
            # Details that ran onto a new page keep the item their label named
            # on the page before.
            carried = state.last_item.get(holder)
            if carried is None:
                raise ValueError(
                    f"{path.name} page {page_index + 1}: alteration details with no "
                    f"item for {holder.value}: {[t for _top, t in detail_entries]!r}"
                )
            item_entries = [(detail_entries[0][0], f"{_item_number(carried)}. carried")]
        # Consecutive entries under the same category sometimes share a
        # single "N. Category" line rather than repeating it per entry (e.g.
        # five gift entries under one "11. Gifts"), so an item applies to
        # every detail entry from its own top down to the next item's top.
        item_index = 0
        for detail_top, detail_text in detail_entries:
            while (
                item_index + 1 < len(item_entries)
                and item_entries[item_index + 1][0] <= detail_top + 2
            ):
                item_index += 1
            if is_nil(detail_text):
                continue
            category = _category_for_item(item_entries[item_index][1], path, page_index)
            state.last_item[holder] = category
            results.append((holder, category, detail_text.strip()))
    return results


def _item_number(category: Category) -> int:
    return next(n for n, c in HOUSE_ITEMS.items() if c is category)


_HEADING_RE = re.compile(
    r"(?m)^\s*(\d{1,2}\.|\(i{1,2}\)|ADDITION|DELETION|Notification of|NOTIFICATION OF)"
)


def _has_heading_above(page: Any, table: Any, tables: list[Any]) -> bool:
    """Whether an item heading ("6. Indicate ...", ADDITION, ...) sits between
    this table and the previous one on the page (or the page top)."""
    top = table.bbox[1]
    above = [t.bbox[3] for t in tables if t.bbox[3] <= top + 1 and t is not table]
    floor = max(above, default=0.0)
    band = page.crop((0, floor, page.width, top))
    return bool(_HEADING_RE.search(band.extract_text() or ""))


def _parse_identity(
    grid: list[list[str | None]], path: Path, page_index: int
) -> tuple[str, str]:
    row0 = _normalise(grid[0][0])
    row1 = _normalise(grid[1][0]) if len(grid) > 1 else ""
    m_family = re.match(r"^FAMILY\s+NAME\s+(?P<v>.+?)(?:\s*\(please print\))?$", row0)
    if not m_family:
        raise ValueError(
            f"{path.name} page {page_index + 1}: unrecognised identity row {row0!r}"
        )
    m_given = re.match(r"^GIVEN\s+NAMES\s+(?P<v>.+)$", row1) or re.match(
        r"^GIVEN\s+(?P<v>.+?)\s+NAMES$", row1
    )
    if not m_given:
        raise ValueError(
            f"{path.name} page {page_index + 1}: unrecognised given-names row {row1!r}"
        )
    return m_family.group("v").strip(), m_given.group("v").strip()


def _parse_ddmmyyyy(text: str) -> date:
    return datetime.strptime(text, "%d/%m/%Y").replace(tzinfo=UTC).date()


def parse_pdf(path: Path) -> ParsedForm:
    """Parse one House statement PDF. Raises `ValueError` naming the file and
    page on any table or header it doesn't recognise, rather than guessing."""
    with pdfplumber.open(path) as pdf:
        page_texts = [p.extract_text() or "" for p in pdf.pages]
        if not any(_STATEMENT_MARKER in t for t in page_texts):
            return ParsedForm(has_text_layer=False)

        family_name: str | None = None
        given_names: str | None = None
        date_lodged: date | None = None
        interests: list[Interest] = []
        alterations: list[Alteration] = []

        sequence_index = 0
        pending_additions: list[tuple[Holder, Category, str]] = []
        pending_deletions: list[tuple[Holder, Category, str]] = []
        alteration_sequence = 0

        # A table whose content overruns a page continues on the next page as
        # a *separate* pdfplumber table with no header row of its own -- its
        # first cell is a holder label (Self/Spouse/Dependent), not "". Such a
        # continuation belongs to whichever table was open when the page
        # broke, tracked here so its rows extend rather than restart it.
        open_item: tuple[Category, str | None, list[str]] | None = None
        open_alteration: str | None = None  # "addition" | "deletion" | None
        state = _RowState()

        for page_index, page in enumerate(pdf.pages):
            tables = sorted(page.find_tables(), key=lambda t: t.bbox[1])
            for table in tables:
                grid = table.extract()
                if not grid or not grid[0]:
                    continue
                first_cell = _normalise(grid[0][0])
                if first_cell.startswith("FAMILY"):
                    if family_name is None:
                        family_name, given_names = _parse_identity(
                            grid, path, page_index
                        )
                    continue
                if first_cell == "Notes":
                    continue

                second_cell = _normalise(grid[0][1]) if len(grid[0]) > 1 else ""
                # A table that spilled onto this page has no header row and no
                # item heading above it: its first row either starts with a
                # holder label or, when the split fell inside a row, with blank
                # leading cells. A table that does sit under a heading is a
                # real one, so an unknown header there still raises below.
                is_continuation = first_cell in _HOLDER_LABELS or (
                    first_cell == ""
                    and not second_cell.startswith(("ADDITION", "DELETION"))
                    and not any(_normalise(c) in HOUSE_COLUMNS for c in grid[0][1:])
                    and not _has_heading_above(page, table, tables)
                )
                if is_continuation:
                    rows = list(zip(table.rows, grid, strict=True))
                    state.notes.append(
                        f"a table continued onto page {page_index + 1}; its rows were "
                        "joined to the one before"
                    )
                    if open_alteration == "addition":
                        pending_additions.extend(
                            _alteration_entries_from_rows(
                                page, rows, path, page_index, state
                            )
                        )
                    elif open_alteration == "deletion":
                        pending_deletions.extend(
                            _alteration_entries_from_rows(
                                page, rows, path, page_index, state
                            )
                        )
                    elif open_item is not None:
                        category, role, field_names = open_item
                        interests.extend(
                            _interests_from_rows(
                                page,
                                rows,
                                field_names,
                                category,
                                role,
                                path,
                                page_index,
                                state,
                            )
                        )
                    else:
                        raise ValueError(
                            f"{path.name} page {page_index + 1}: continuation row "
                            f"with no table open: {grid[0]!r}"
                        )
                    continue

                if first_cell != "":
                    raise ValueError(
                        f"{path.name} page {page_index + 1}: unrecognised table "
                        f"{grid[0]!r}"
                    )

                rows = list(zip(table.rows[1:], grid[1:], strict=True))
                if second_cell.startswith("ADDITION"):
                    open_item = None
                    open_alteration = "addition"
                    pending_additions = _alteration_entries_from_rows(
                        page, rows, path, page_index, state
                    )
                    pending_deletions = []
                    continue
                if second_cell.startswith("DELETION"):
                    open_alteration = "deletion"
                    pending_deletions = _alteration_entries_from_rows(
                        page, rows, path, page_index, state
                    )
                    continue

                if sequence_index >= len(_STATEMENT_TABLE_SEQUENCE):
                    raise ValueError(
                        f"{path.name} page {page_index + 1}: unexpected extra table "
                        f"{grid[0]!r}"
                    )
                open_alteration = None
                category, role = _STATEMENT_TABLE_SEQUENCE[sequence_index]
                field_names = _column_field_names(grid[0], path, page_index)
                open_item = (category, role, field_names)
                interests.extend(
                    _interests_from_rows(
                        page, rows, field_names, category, role, path, page_index, state
                    )
                )
                sequence_index += 1

            submitted_m = _SUBMITTED_RE.search(page_texts[page_index])
            processed_m = _PROCESSED_RE.search(page_texts[page_index])
            if not (submitted_m and processed_m):
                continue
            submitted = _parse_ddmmyyyy(submitted_m.group(1))
            processed = _parse_ddmmyyyy(processed_m.group(1))
            if date_lodged is None:
                date_lodged = submitted
            for kind, batch in (
                (AlterationKind.ADDITION, pending_additions),
                (AlterationKind.DELETION, pending_deletions),
            ):
                for holder, category, details in batch:
                    alteration_sequence += 1
                    alterations.append(
                        Alteration(
                            kind=kind,
                            category=category,
                            holder=holder,
                            details=details,
                            date_submitted=submitted,
                            date_processed=processed,
                            sequence=alteration_sequence,
                        )
                    )
            pending_additions = []
            pending_deletions = []

        if sequence_index != len(_STATEMENT_TABLE_SEQUENCE):
            raise ValueError(
                f"{path.name}: found {sequence_index} statement item tables, expected "
                f"{len(_STATEMENT_TABLE_SEQUENCE)}"
            )

        return ParsedForm(
            has_text_layer=True,
            family_name=family_name,
            given_names=given_names,
            date_lodged=date_lodged,
            interests=interests,
            alterations=alterations,
            notes=sorted(set(state.notes)),
        )


# --- Statement assembly --------------------------------------------------


def parse(parliament: int = 48) -> list[Statement]:
    """Build and write a `Statement` for every member in the raw index."""
    index_path = paths.raw_index(Chamber.HOUSE, parliament)
    index_data = json.loads(index_path.read_text())
    fetched_at = datetime.fromisoformat(index_data["fetched_at"])

    statements: list[Statement] = []
    for entry in index_data["entries"]:
        aph_id = entry["aph_id"]
        if aph_id is None:
            logger.warning(
                "skipping entry with unresolved aph_id: {}", entry["display_name"]
            )
            continue

        pdf_path = paths.raw_dir(Chamber.HOUSE, parliament) / f"{aph_id}.pdf"
        source = Source(
            url=entry["url"],
            kind="house-static-pdf" if entry["kind"] == "static" else "house-api-pdf",
            sha256=fetchlib.sha256_of(pdf_path),
            fetched_at=fetched_at,
            raw_path=paths.relative(pdf_path),
        )
        stub = Statement(
            aph_id=aph_id,
            chamber=Chamber.HOUSE,
            parliament=parliament,
            family_name=entry["family_name"],
            given_names=entry["given_names"],
            display_name=entry["display_name"],
            honorific=entry["honorific"],
            party=None,
            state=entry["state"],
            electorate=entry["electorate"],
            date_lodged=None,
            last_updated=date.fromisoformat(entry["last_updated"]),
            interests=[],
            alterations=[],
            notes=[],
            source=source,
            extraction=Extraction(method=ExtractionMethod.PENDING),
        )

        override = overrides.find(Chamber.HOUSE, parliament, aph_id)
        if override is not None:
            statement = overrides.apply(stub, override)
        else:
            try:
                parsed = parse_pdf(pdf_path)
            except ValueError as exc:
                # parse_pdf raises loudly on a layout it doesn't recognise
                # (by design, so a form change is never silently misread),
                # but one member's odd layout shouldn't stop the batch: fall
                # back to a reviewable stub and keep going.
                logger.warning("{}: {}", aph_id, exc)
                statement = stub.model_copy(
                    update={
                        "extraction": Extraction(
                            method=ExtractionMethod.PENDING,
                            notes=[f"parse_pdf failed: {exc}"],
                        ),
                    }
                )
                store.write_statement(statement)
                statements.append(statement)
                continue
            if parsed.has_text_layer:
                family_name = parsed.family_name or stub.family_name
                given_names = parsed.given_names or stub.given_names
                statement = stub.model_copy(
                    update={
                        "family_name": family_name,
                        "given_names": given_names,
                        "display_name": f"{family_name}, {given_names}",
                        "date_lodged": parsed.date_lodged,
                        "interests": parsed.interests,
                        "alterations": parsed.alterations,
                        "extraction": Extraction(
                            method=ExtractionMethod.PDF_TEXT,
                            version=1,
                            notes=parsed.notes,
                        ),
                    }
                )
            else:
                statement = stub.model_copy(
                    update={
                        "extraction": Extraction(
                            method=ExtractionMethod.PENDING,
                            notes=[
                                "scanned PDF; run `pollie ocr` and review the override"
                            ],
                        ),
                    }
                )

        store.write_statement(statement)
        statements.append(statement)
    return statements
