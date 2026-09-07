"""Local vision-model OCR for House statements with no usable text layer.

A handful of `raw/house` PDFs are scans (handwritten or otherwise) that
pdfplumber cannot read. This module renders those pages to images, runs them
through a local, open-source OCR/vision model (Chandra, via the HuggingFace
transformers backend), and turns the model's markdown output into a draft
`overrides.Override` with `extraction.method = OCR`. A reviewer checks the
draft against the scan and flips the method to `MANUAL` once confirmed --
`draft_override` never claims more confidence than that.

The model itself is a heavy, optional dependency (the `ocr` group): nothing
in this module imports `chandra` or `torch` at module scope, so `pollie ocr`
is the only command that pays for it.

Chandra's HTML/markdown output for these forms is very regular once you've
seen a few pages:

* Item headings are a bold or heading-level line ending "N. <title>", e.g.
  `**9. The nature of any other assets ...**` or `#### 6. Liabilities ...`.
* Item 2 (trusts) has two sub-tables under roman-numeral sub-headings "i."
  (beneficial interest) and "ii." (trustee); `Interest.fields["role"]`
  records which.
* Each item's table has one row per holder (Self / Spouse/partner /
  Dependent children); a holder with more than one line item either repeats
  the label with `rowspan`, or leaves the first cell blank on continuation
  rows -- both are handled by carrying the last-seen holder forward.
* "Notification of alteration(s)" pages have one or two tables headed
  ADDITION / DELETION. Two layouts are in use: a 3-column one with the same
  Self/Spouse/Dependent holder rows as the statement tables (item and
  details in one cell each), and a 2-column one with no holder row at all
  (item, details) -- alterations from the 2-column layout default to
  `Holder.SELF` unless the details text names the spouse or a dependent
  child.
* "Submitted Date:" / "Date:" and "Processed by Registrar ...:" /
  "PROCESSED <date>" carry the alteration's `date_submitted` and
  `date_processed`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pdfplumber
import pypdfium2 as pdfium
from bs4 import BeautifulSoup
from loguru import logger

from pollie_watch.overrides import Override
from pollie_watch.schema import (
    HOUSE_COLUMNS,
    HOUSE_ITEMS,
    Alteration,
    AlterationKind,
    Category,
    Extraction,
    ExtractionMethod,
    Holder,
    Interest,
    is_nil,
)

if TYPE_CHECKING:
    from chandra.model import InferenceManager

# Below this average characters/page, a PDF is treated as having no usable
# text layer (a blank page, a scan with no OCR pass, or a garbled one -- see
# module docstring on Katter, whose existing layer is well above this
# threshold but unusable; the threshold catches "nothing to read", not
# "nothing worth reading").
TEXT_LAYER_THRESHOLD = 200

HOLDER_LABELS: dict[str, Holder] = {
    "self": Holder.SELF,
    "spouse": Holder.SPOUSE,
    "spouse/partner": Holder.SPOUSE,
    "partner": Holder.SPOUSE,
    "dependent": Holder.DEPENDENT,
    "dependent children": Holder.DEPENDENT,
    "children": Holder.DEPENDENT,
}

# Normalised (lowercased, whitespace-collapsed, singularised) HOUSE_COLUMNS,
# since the model's transcription of a column header can drop trailing
# punctuation or pluralise/singularise a word ("Beneficial interest" for
# "Beneficial interests"). Matched with startswith/substring, longest key
# first.
_NORMALISED_COLUMNS: list[tuple[str, str]] = sorted(
    (
        (re.sub(r"s\b", "", re.sub(r"\s+", " ", k).strip().lower()), v)
        for k, v in HOUSE_COLUMNS.items()
    ),
    key=lambda kv: -len(kv[0]),
)

ITEM_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*|\*{1,2}\s*)?(\d{1,2})\.\s+\S", re.MULTILINE
)
SUBITEM_RE = re.compile(r"^\s*(i{1,3})\.\s+\S", re.MULTILINE | re.IGNORECASE)
SUBMITTED_DATE_RE = re.compile(r"Submitted\s+Date\s*:?\s*([0-9/.\- A-Za-z]+)")
PROCESSED_RE = re.compile(
    r"PROCESSED\s+([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}"
    r"|[A-Za-z]+\s+[0-9]{1,2}\.?,?\s+[0-9]{4})"
)
PROCESSED_BY_REGISTRAR_RE = re.compile(
    r"Processed\s+by\s+Registrar[^:]*:?\s*([0-9/.\- A-Za-z]+)"
)
DATE_LABEL_RE = re.compile(r"^\s*Date\s*:?\s*$", re.MULTILINE)
DATE_INLINE_RE = re.compile(r"Date\s*:\s*([0-9/.\- A-Za-z]+)")
DATE_TOKEN_RE = re.compile(
    r"([0-9]{1,2}[/.\- ][0-9]{1,2}[/.\- ][0-9]{2,4}"
    r"|[0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4}"
    r"|[A-Za-z]{3,9}\s+[0-9]{1,2},?\s+[0-9]{4})"
)


def has_text_layer(path: Path) -> bool:
    """True when pdfplumber can already read this PDF: >= 200 chars/page on
    average. Below that, the parser should route the document through OCR
    instead. This is a cheap proxy, not a quality check -- a bad existing OCR
    layer (garbled cursive read as noise, still hundreds of characters/page)
    passes it just as a clean typed layer does; anyone routing a document
    this flags as `True` should still spot-check a page or two."""
    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            return False
        total_chars = sum(len(page.extract_text() or "") for page in pdf.pages)
        average = total_chars / len(pdf.pages)
        logger.debug("{}: {:.0f} chars/page average", path.name, average)
        return average >= TEXT_LAYER_THRESHOLD


def render_pages(path: Path, out_dir: Path, dpi: int = 200) -> list[Path]:
    """Render every page of `path` to a PNG in `out_dir`, at `dpi`. Returns
    the written paths in page order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest_paths: list[Path] = []
    pdf = pdfium.PdfDocument(path)
    try:
        for i in range(len(pdf)):
            bitmap = pdf[i].render(scale=dpi / 72)
            image = bitmap.to_pil().convert("RGB")
            dest = out_dir / f"page-{i + 1:02d}.png"
            image.save(dest)
            dest_paths.append(dest)
    finally:
        pdf.close()
    return dest_paths


_model_cache: InferenceManager | None = None


def _load_model() -> InferenceManager:
    """Load Chandra's HF-backend model once per process and cache it."""
    global _model_cache
    if _model_cache is None:
        from chandra.model import InferenceManager

        logger.info("loading OCR model (chandra, hf backend)...")
        _model_cache = InferenceManager(method="hf")
        logger.info("OCR model loaded")
    return _model_cache


def ocr_pdf(path: Path, work_dir: Path) -> list[str]:
    """Render every page of `path` and OCR it with the local vision model,
    page by page. Each page's markdown is saved to
    `work_dir/{path.stem}/page-NN.md`; the same texts are returned in page
    order. Loads the model once per process (cached at module scope), so
    calling this repeatedly for several documents in one run only pays the
    load cost once."""
    from chandra.model.schema import BatchInputItem
    from PIL import Image

    manager = _load_model()
    page_dir = work_dir / path.stem
    page_paths = render_pages(path, page_dir)

    texts: list[str] = []
    for i, page_path in enumerate(page_paths, start=1):
        image = Image.open(page_path)
        result = manager.generate(
            [BatchInputItem(image=image, prompt_type="ocr_layout")]
        )[0]
        text = result.markdown
        texts.append(text)
        dest = page_dir / f"page-{i:02d}.md"
        dest.write_text(text)
        logger.info(
            "{}: page {}/{} OCR'd ({} chars, {} tokens)",
            path.stem,
            i,
            len(page_paths),
            len(text),
            result.token_count,
        )
    return texts


# --- draft_override and its helpers -----------------------------------------


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _holder_of(label: str) -> Holder | None:
    # BeautifulSoup's get_text(" ") inserts the separator either side of a
    # <br/> tag, so "Spouse/<br/>partner" comes out as "Spouse/ partner" --
    # collapse the spacing around "/" back down before the label lookup.
    key = re.sub(r"\s*/\s*", "/", _normalise(label).lower())
    return HOLDER_LABELS.get(key)


def _stem(text: str) -> str:
    """Strip a trailing plural 's' from each word, so "Details of gifts"
    lines up with the printed "Detail of gifts" and Chandra's own singular
    "Beneficial interest" lines up with the printed "Beneficial interests".
    Heuristic, not real stemming -- fine since it's applied identically to
    both sides of the comparison."""
    return re.sub(r"s\b", "", text)


def _column_field(header: str) -> str | None:
    key = _stem(_normalise(header).lower().rstrip(":"))
    for norm_key, field in _NORMALISED_COLUMNS:
        if key == norm_key or key in norm_key or norm_key in key:
            return field
    return None


def _iter_table_blocks(page_text: str) -> list[tuple[str, str]]:
    """Split a page's markdown into (preceding_text, table_html) pairs, one
    per <table>...</table> block, in document order. Text after the final
    table is returned as a trailing pair with an empty table string."""
    blocks: list[tuple[str, str]] = []
    pos = 0
    for match in re.finditer(r"<table\b.*?</table>", page_text, re.DOTALL):
        blocks.append((page_text[pos : match.start()], match.group(0)))
        pos = match.end()
    blocks.append((page_text[pos:], ""))
    return blocks


def _last_item_number(text: str) -> int | None:
    numbers = [
        int(m.group(1))
        for m in ITEM_HEADING_RE.finditer(text)
        if int(m.group(1)) in HOUSE_ITEMS
    ]
    return numbers[-1] if numbers else None


def _last_subitem(text: str) -> str | None:
    roman = [m.group(1).lower() for m in SUBITEM_RE.finditer(text)]
    return roman[-1] if roman else None


def _parse_statement_table(
    table_html: str, category: Category, role: str | None
) -> list[Interest]:
    soup = BeautifulSoup(table_html, "html.parser")
    header_cells = soup.select("thead th")
    body_rows = soup.select("tbody tr") or soup.select("tr")

    # Two layouts are in use: one with a leading blank <th> for the holder
    # column, one without. Rather than guess from the header count, measure
    # the real data-column count from the first row whose first cell is a
    # recognised holder label, then take that many headers off the *end* of
    # the header row -- which lines up correctly either way.
    data_col_count = None
    for row in body_rows:
        cells = row.find_all(["td", "th"])
        if cells and _holder_of(cells[0].get_text(" ", strip=True)) is not None:
            data_col_count = len(cells) - 1
            break
    if data_col_count is None:
        data_col_count = max(
            (len(row.find_all(["td", "th"])) for row in body_rows),
            default=len(header_cells),
        )

    header_texts = [h.get_text(" ", strip=True) for h in header_cells]
    data_headers = header_texts[-data_col_count:] if data_col_count else header_texts
    fields_for_columns = [_column_field(h) for h in data_headers]

    interests: list[Interest] = []
    current_holder: Holder | None = None
    for row in body_rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        label_text = cells[0].get_text(" ", strip=True)
        holder = _holder_of(label_text)
        if holder is not None:
            current_holder = holder
            data_cells = cells[1:]
        else:
            # Blank first cell: either a continuation row of the same
            # holder with its own blank placeholder in the holder column
            # (row width == data_col_count, keep every cell), or one with
            # the placeholder cell already stripped by the model (row width
            # > data_col_count, drop the extra leading cell).
            if current_holder is None:
                continue
            data_cells = cells[1:] if len(cells) > data_col_count else cells

        if current_holder is None:
            continue

        values: dict[str, str] = {}
        for cell, field in zip(data_cells, fields_for_columns, strict=False):
            if field is None:
                continue
            value = cell.get_text(" ", strip=True)
            if value and not is_nil(value):
                values[field] = value
        if not values:
            continue
        fields = dict(values)
        if category == Category.TRUSTS and role:
            fields["role"] = "beneficial-interest" if role == "i" else "trustee"
        interests.append(
            Interest(category=category, holder=current_holder, fields=fields)
        )
    return interests


_SPOUSE_HINT_RE = re.compile(r"^\s*spouse\b", re.IGNORECASE)
_DEPENDENT_HINT_RE = re.compile(r"^\s*(dependent|child)\b", re.IGNORECASE)


def _infer_holder_from_details(details: str) -> Holder:
    if _SPOUSE_HINT_RE.search(details):
        return Holder.SPOUSE
    if _DEPENDENT_HINT_RE.search(details):
        return Holder.DEPENDENT
    return Holder.SELF


def _parse_alteration_table(
    table_html: str, kind: AlterationKind, sequence_start: int, notes: list[str]
) -> tuple[list[Alteration], int]:
    soup = BeautifulSoup(table_html, "html.parser")
    header_cells = soup.select("thead th") or soup.select("tr")[:1]
    n_headers = len(header_cells)

    alterations: list[Alteration] = []
    sequence = sequence_start
    current_holder: Holder | None = None
    body_rows = soup.select("tbody tr")
    if not body_rows:
        all_rows = soup.select("tr")
        body_rows = all_rows[1:] if len(all_rows) > 1 else all_rows

    for row in body_rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        if n_headers >= 3:
            # 3-column layout: holder, item, details.
            label_text = cells[0].get_text(" ", strip=True)
            holder = _holder_of(label_text)
            if holder is not None:
                current_holder = holder
                rest = cells[1:]
            else:
                rest = cells if current_holder is None else cells[1:]
            item_cell, details_cell = (rest + [None, None])[:2]
            holder_for_row = current_holder or Holder.SELF
        else:
            # 2-column layout: item, details. No holder row at all.
            item_cell, details_cell = (cells + [None, None])[:2]
            holder_for_row = None  # inferred from details text below

        if item_cell is None or details_cell is None:
            continue
        item_text = item_cell.get_text(" ", strip=True)
        details_text = details_cell.get_text("\n", strip=True)
        if is_nil(item_text) or is_nil(details_text):
            continue

        item_match = re.match(r"(\d{1,2})\.\s*(.*)", item_text)
        if not item_match:
            notes.append(
                f"unrecognised alteration item {item_text!r} (details: {details_text!r})"
            )
            continue
        item_number = int(item_match.group(1))
        category = HOUSE_ITEMS.get(item_number)
        if category is None:
            notes.append(
                f"unrecognised item number {item_number} in alteration "
                f"(details: {details_text!r})"
            )
            continue

        holder = holder_for_row or _infer_holder_from_details(details_text)
        alterations.append(
            Alteration(
                kind=kind,
                category=category,
                holder=holder,
                details=details_text,
                sequence=sequence,
            )
        )
        sequence += 1
    return alterations, sequence


def _parse_date(text: str) -> date | None:
    match = DATE_TOKEN_RE.search(text)
    if not match:
        return None
    token = match.group(1).strip()
    formats = (
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%d.%m.%Y",
        "%d.%m.%y",
        "%d %m %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%B %d %Y",
        "%b %d, %Y",
        "%b %d %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(token, fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    return None


def draft_override(pages: list[str], *, model_name: str) -> Override:
    """Deterministically turn a document's OCR'd page texts into a draft
    Override: regex/heuristics only, no model calls. Identity fields are
    left to the House parser; this fills `interests`, `alterations`,
    `date_lodged` and `extraction`.

    Anything the heuristics can place goes into `interests`/`alterations`;
    anything they can't (an unrecognised item number, a table with no
    holder/item structure the parser understands, text outside any item
    that doesn't look like page furniture) is quoted verbatim in
    `extraction.notes` so a reviewer sees it rather than silently losing
    it."""
    interests: list[Interest] = []
    alterations: list[Alteration] = []
    notes: list[str] = [f"{model_name}, drafted {datetime.now(UTC):%Y-%m-%d}"]
    date_lodged: date | None = None
    sequence = 1
    # Items are printed in ascending order 1-14 across the whole statement.
    # Guards against a stray "N. ..." in body text (the explanatory notes on
    # page 1 are themselves a numbered list) being read as a new item and
    # regressing the tracker on a later page.
    max_item_seen = 0

    for page_text in pages:
        if not page_text.strip():
            continue

        is_alteration_page = bool(
            re.search(r"notification of alteration", page_text, re.IGNORECASE)
        )

        if is_alteration_page:
            page_submitted = None
            page_processed = None
            sub_match = SUBMITTED_DATE_RE.search(page_text)
            if sub_match:
                page_submitted = _parse_date(sub_match.group(1))
            proc_match = PROCESSED_RE.search(
                page_text
            ) or PROCESSED_BY_REGISTRAR_RE.search(page_text)
            if proc_match:
                page_processed = _parse_date(proc_match.group(1))
            if page_processed is None:
                # "Date:" on its own line, value on the line(s) after it --
                # the member's signed date, not the registrar's processed
                # date.
                label = DATE_LABEL_RE.search(page_text)
                if label:
                    tail = page_text[label.end() :]
                    page_submitted = page_submitted or _parse_date(tail[:80])
                else:
                    inline = DATE_INLINE_RE.search(page_text)
                    if inline:
                        page_submitted = page_submitted or _parse_date(inline.group(1))

            for _block_text, table_html in _iter_table_blocks(page_text):
                if not table_html:
                    continue
                table_soup = BeautifulSoup(table_html, "html.parser")
                if "family name" in table_soup.get_text(" ", strip=True).lower():
                    # The identity block repeated at the top of the
                    # notification page (FAMILY NAME / GIVEN NAMES / ...),
                    # not an ADDITION/DELETION table -- and often has no
                    # <thead> at all, which would otherwise make
                    # _parse_alteration_table misread its rows as items.
                    continue
                header_words = " ".join(
                    th.get_text(" ", strip=True) for th in table_soup.select("thead th")
                ).upper()
                kind = (
                    AlterationKind.DELETION
                    if "DELETION" in header_words
                    else AlterationKind.ADDITION
                )
                new_alterations, sequence = _parse_alteration_table(
                    table_html, kind, sequence, notes
                )
                for alteration in new_alterations:
                    alterations.append(
                        alteration.model_copy(
                            update={
                                "date_submitted": page_submitted,
                                "date_processed": page_processed,
                            }
                        )
                    )
            continue

        # Statement page: walk items in order, tracking the most recent
        # "N." heading and, for item 2, the most recent "i."/"ii." marker.
        current_item: int | None = None
        current_subitem: str | None = None
        for block_text, table_html in _iter_table_blocks(page_text):
            item_number = _last_item_number(block_text)
            if item_number is not None and item_number >= max_item_seen:
                current_item = item_number
                max_item_seen = item_number
                current_subitem = None
            subitem = _last_subitem(block_text)
            if subitem is not None:
                current_subitem = subitem

            if not table_html:
                continue
            if current_item is None:
                stripped = _normalise(
                    BeautifulSoup(table_html, "html.parser").get_text(" ")
                )
                if stripped and "family name" not in stripped.lower():
                    notes.append(
                        f"table with no recognised item heading: {stripped[:200]!r}"
                    )
                continue

            category = HOUSE_ITEMS[current_item]
            interests.extend(
                _parse_statement_table(table_html, category, current_subitem)
            )

        if date_lodged is None:
            lodged_match = re.search(
                r"(?:date\s+of\s+election|dissolution)[^0-9]{0,20}"
                + DATE_TOKEN_RE.pattern,
                page_text,
                re.IGNORECASE,
            )
            if lodged_match:
                date_lodged = _parse_date(lodged_match.group(0))

    return Override(
        extraction=Extraction(method=ExtractionMethod.OCR, notes=notes),
        date_lodged=date_lodged,
        interests=interests,
        alterations=alterations,
    )


# --- writing the draft -------------------------------------------------------


def _toml_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
    return f'"{escaped}"'


def _toml_inline_table(fields: dict[str, str]) -> str:
    parts = [f"{key} = {_toml_escape(value)}" for key, value in fields.items()]
    return "{ " + ", ".join(parts) + " }" if parts else "{ }"


def write_draft(override: Override, dest: Path) -> Path:
    """Serialise `override` to the TOML format documented in overrides.py.
    Round-trips through `overrides.load`."""
    lines: list[str] = []

    lines.append("[extraction]")
    lines.append(f'method = "{override.extraction.method.value}"')
    lines.append(f"version = {override.extraction.version}")
    if override.extraction.notes:
        notes = ", ".join(_toml_escape(n) for n in override.extraction.notes)
        lines.append(f"notes = [{notes}]")
    lines.append("")

    if override.date_lodged is not None:
        lines.append(f"date_lodged = {override.date_lodged.isoformat()}")
    if override.notes:
        notes = ", ".join(_toml_escape(n) for n in override.notes)
        lines.append(f"notes = [{notes}]")
    if override.date_lodged is not None or override.notes:
        lines.append("")

    for interest in override.interests:
        lines.append("[[interests]]")
        lines.append(f'category = "{interest.category.value}"')
        lines.append(f'holder = "{interest.holder.value}"')
        lines.append(f"fields = {_toml_inline_table(interest.fields)}")
        if interest.source_id is not None:
            lines.append(f"source_id = {_toml_escape(interest.source_id)}")
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
        if alteration.source_id is not None:
            lines.append(f"source_id = {_toml_escape(alteration.source_id)}")
        lines.append("")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines).rstrip() + "\n")
    logger.info("wrote {}", dest)
    return dest


def run(
    pdf: Path, dest: Path, work_dir: Path, *, model_name: str = "chandra-ocr"
) -> Path:
    """The whole pipeline for one document: render, OCR page by page, draft
    an override, write it to `dest`."""
    logger.info("OCR pipeline: {} -> {}", pdf.name, dest)
    pages = ocr_pdf(pdf, work_dir)
    override = draft_override(pages, model_name=model_name)
    return write_draft(override, dest)
