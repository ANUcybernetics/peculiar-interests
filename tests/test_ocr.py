"""ocr.py tests: deterministic heuristics only, no GPU/model. `draft_override`
is exercised against hand-written OCR-style markdown (Chandra's actual output
shape, captured while building this module) rather than real model output."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pollie_watch import overrides
from pollie_watch.ocr import draft_override, has_text_layer, write_draft
from pollie_watch.schema import AlterationKind, Category, ExtractionMethod, Holder

FIXTURES = Path(__file__).parent / "fixtures" / "house"

STATEMENT_PAGE = """\
**1. List shareholdings in public and private companies (including holding companies) and indicate the name of the company or companies**

<table border="1">
<thead>
<tr>
<th colspan="2">Name of company (including holding and subsidiary companies if applicable)</th>
</tr>
</thead>
<tbody>
<tr>
<td>Self</td>
<td>Woolworths Group shares</td>
</tr>
<tr>
<td>Spouse/<br/>partner</td>
<td>Not Applicable</td>
</tr>
<tr>
<td>Dependent<br/>children</td>
<td>Not Applicable</td>
</tr>
</tbody>
</table>

**3. Real estate, including the location (suburb or area only) and the purpose for which it is owned**

<table border="1">
<thead>
<tr>
<th></th>
<th>Location</th>
<th>Purpose for which owned</th>
</tr>
</thead>
<tbody>
<tr>
<td>Self</td>
<td>Not Applicable</td>
<td></td>
</tr>
<tr>
<td>Spouse/<br/>partner</td>
<td>Not Applicable</td>
<td></td>
</tr>
<tr>
<td>Dependent<br/>children</td>
<td>Not Applicable</td>
<td></td>
</tr>
</tbody>
</table>
"""

NOTIFICATION_PAGE = """\
## Notification of alteration(s) of interests since dissolution or date of election

I wish to notify an alteration of interests as follows:

<table border="1">
<thead>
<tr>
<th style="text-align: left;"><b>ADDITION</b><br/><b>Item</b></th>
<th style="text-align: left;"><b>Details</b></th>
</tr>
</thead>
<tbody>
<tr>
<td>11. Gifts</td>
<td>Bottle of wine from the ACT Wine Show</td>
</tr>
</tbody>
</table>

<table border="1">
<thead>
<tr>
<th style="text-align: left;"><b>DELETION</b><br/><b>Item</b></th>
<th style="text-align: left;"><b>Details</b></th>
</tr>
</thead>
<tbody>
<tr>
<td>3. Real Estate</td>
<td>Sold investment property in Marrickville, NSW</td>
</tr>
</tbody>
</table>

Submitted Date: 14/08/2025

Processed by Registrar of Members' Interests: 15/08/2025
"""

UNPLACEABLE_PAGE = """\
Handwritten note in the margin that doesn't fit the printed form at all.

<table border="1">
<tbody>
<tr>
<td>Mystery cell content the heuristics can't place</td>
</tr>
</tbody>
</table>
"""


def test_has_text_layer_true_for_typed_pdf():
    assert has_text_layer(FIXTURES / "316915.pdf") is True


def test_draft_override_statement_page_fills_and_skips_nil():
    override = draft_override([STATEMENT_PAGE], model_name="chandra-ocr 0.2.0")

    assert len(override.interests) == 1
    interest = override.interests[0]
    assert interest.category == Category.SHAREHOLDINGS
    assert interest.holder == Holder.SELF
    assert interest.fields == {"company": "Woolworths Group shares"}

    # Item 3 is all "Not Applicable" -- nothing generated for it.
    assert not any(i.category == Category.REAL_ESTATE for i in override.interests)

    assert override.extraction.method == ExtractionMethod.OCR
    assert override.extraction.notes[0].startswith("chandra-ocr 0.2.0")


def test_draft_override_notification_page_addition_and_deletion():
    override = draft_override([NOTIFICATION_PAGE], model_name="chandra-ocr 0.2.0")

    assert len(override.alterations) == 2
    addition, deletion = override.alterations

    assert addition.kind == AlterationKind.ADDITION
    assert addition.category == Category.GIFTS
    assert addition.holder == Holder.SELF
    assert addition.details == "Bottle of wine from the ACT Wine Show"
    assert addition.date_submitted == date(2025, 8, 14)
    assert addition.date_processed == date(2025, 8, 15)
    assert addition.sequence == 1

    assert deletion.kind == AlterationKind.DELETION
    assert deletion.category == Category.REAL_ESTATE
    assert deletion.details == "Sold investment property in Marrickville, NSW"
    assert deletion.sequence == 2


def test_draft_override_unplaceable_fragment_lands_in_notes():
    override = draft_override([UNPLACEABLE_PAGE], model_name="chandra-ocr 0.2.0")

    assert override.interests == []
    assert override.alterations == []
    joined_notes = " ".join(override.extraction.notes)
    assert "Mystery cell content" in joined_notes


def test_write_draft_round_trips_through_overrides_load(tmp_path):
    override = draft_override(
        [STATEMENT_PAGE, NOTIFICATION_PAGE], model_name="chandra-ocr 0.2.0"
    )
    dest = tmp_path / "draft.toml"

    write_draft(override, dest)
    loaded = overrides.load(dest)

    assert loaded == override
