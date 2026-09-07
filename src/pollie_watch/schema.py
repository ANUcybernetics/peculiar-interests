"""Canonical data model shared by every ingest path and by the site.

Both houses' registers descend from the same 1984 resolutions, so they ask the
same fourteen questions in the same order. The House numbers them 1--14 on its
form; the Senate API names them. `Category` is the neutral vocabulary, and the
two mapping tables at the bottom translate each source into it.

Everything downstream (site, static API, tests) consumes `Statement` JSON
written by `Statement.model_dump_json()`, one file per person per parliament.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Chamber(StrEnum):
    HOUSE = "house"
    SENATE = "senate"


class Category(StrEnum):
    """The fourteen registrable-interest categories, in form order."""

    SHAREHOLDINGS = "shareholdings"
    TRUSTS = "trusts"
    REAL_ESTATE = "real-estate"
    DIRECTORSHIPS = "directorships"
    PARTNERSHIPS = "partnerships"
    LIABILITIES = "liabilities"
    INVESTMENTS = "investments"
    ACCOUNTS = "accounts"
    OTHER_ASSETS = "other-assets"
    OTHER_INCOME = "other-income"
    GIFTS = "gifts"
    TRAVEL_HOSPITALITY = "travel-hospitality"
    MEMBERSHIPS = "memberships"
    OTHER_INTERESTS = "other-interests"


class Holder(StrEnum):
    """Whose interest it is. The House form has a row for each; the Senate API
    does not record it, so Senate interests are `unspecified` unless the text
    says otherwise."""

    SELF = "self"
    SPOUSE = "spouse"
    DEPENDENT = "dependent"
    UNSPECIFIED = "unspecified"


class AlterationKind(StrEnum):
    ADDITION = "addition"
    DELETION = "deletion"


class ExtractionMethod(StrEnum):
    SENATE_API = "senate-api"  # structured JSON, mapped field for field
    PDF_TEXT = "pdf-text"  # text-layer PDF, tables read with pdfplumber
    OCR = "ocr"  # scanned PDF read by a local vision model, unreviewed
    MANUAL = "manual"  # a person confirmed or wrote the override file
    PENDING = "pending"  # a scan with no override yet: metadata only, no interests


# Canonical field names per category. Every `Interest.fields` dict uses only
# these keys (a subset, when a source leaves a column blank). Keep the
# per-source mapping tables below and the site's labels in step with this.
CATEGORY_FIELDS: dict[Category, tuple[str, ...]] = {
    Category.SHAREHOLDINGS: ("company",),
    Category.TRUSTS: ("name", "nature", "beneficial_interest", "role"),
    Category.REAL_ESTATE: ("location", "purpose"),
    Category.DIRECTORSHIPS: ("company", "activities"),
    Category.PARTNERSHIPS: ("name", "nature", "activities"),
    Category.LIABILITIES: ("nature", "creditor"),
    Category.INVESTMENTS: ("type", "body"),
    Category.ACCOUNTS: ("nature", "institution"),
    Category.OTHER_ASSETS: ("nature",),
    Category.OTHER_INCOME: ("nature",),
    Category.GIFTS: ("details",),
    Category.TRAVEL_HOSPITALITY: ("details",),
    Category.MEMBERSHIPS: ("organisation",),
    Category.OTHER_INTERESTS: ("nature",),
}

# Values a member writes to mean "nothing to declare". Normalised away at
# parse time so an empty category is an empty list, not a row of placeholders.
NIL_VALUES = frozenset(
    {"not applicable", "n/a", "na", "nil", "none", "nothing to declare", "-", ""}
)


def is_nil(value: str | None) -> bool:
    return value is None or value.strip().lower().rstrip(".") in NIL_VALUES


class Interest(BaseModel):
    """One declared line item, as it stands in the lodged statement."""

    model_config = ConfigDict(frozen=True)

    category: Category
    holder: Holder = Holder.UNSPECIFIED
    fields: dict[str, str] = Field(default_factory=dict)
    # Source-side identifier when there is one (Senate row GUID); lets a later
    # fetch tell an edited row from a new one.
    source_id: str | None = None

    @property
    def text(self) -> str:
        """The item flattened to one string, for search and display fallbacks."""
        return " / ".join(v for v in self.fields.values() if v)


class Alteration(BaseModel):
    """A dated addition or deletion notified after the statement was lodged.

    Both houses record these as free text against a category, so `details` is
    the record and `fields` is filled only when a parser can do so reliably.
    """

    model_config = ConfigDict(frozen=True)

    kind: AlterationKind
    category: Category | None  # None when the notification names no item
    holder: Holder = Holder.UNSPECIFIED
    details: str
    fields: dict[str, str] = Field(default_factory=dict)
    # House: the "Submitted Date" on the notification. Senate: `createdOn`.
    date_submitted: date | None = None
    # House only: "Processed by Registrar" date. The public record date.
    date_processed: date | None = None
    # Order within the source document, so a ledger can be rebuilt faithfully
    # even when two alterations share a date.
    sequence: int
    source_id: str | None = None

    @property
    def effective_date(self) -> date | None:
        """The date the public record shows: processed where the House stamps
        one, otherwise the submission date."""
        return self.date_processed or self.date_submitted


class Source(BaseModel):
    """Where a statement came from and what we fetched."""

    model_config = ConfigDict(frozen=True)

    url: str
    kind: Literal["senate-api", "house-api-pdf", "house-static-pdf"]
    sha256: str
    fetched_at: datetime
    # Path of the committed raw file, relative to the repo root.
    raw_path: str


class Extraction(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: ExtractionMethod
    # Bump a parser's version when its output for the same input changes, so a
    # diff in data/ can be told apart from a change in the register.
    version: int = 1
    # Free text for anything a reader of the JSON should know: OCR model used,
    # what a reviewer corrected, a registrar's note carried over.
    notes: list[str] = Field(default_factory=list)


class Statement(BaseModel):
    """One parliamentarian's register entry for one parliament: the lodged
    statement plus every notified alteration."""

    model_config = ConfigDict(frozen=True)

    aph_id: str  # APH person ID, shared across both houses (e.g. "HWK", "316915")
    chamber: Chamber
    parliament: int
    family_name: str
    given_names: str
    display_name: str  # "Aldred, Mary" as the register lists them
    honorific: str | None = None  # "Hon", "Dr", "Senator the Hon."
    party: str | None = None
    state: str | None = None
    electorate: str | None = None  # House only
    date_lodged: date | None = None
    # The register index's own "last updated" stamp for this person.
    last_updated: date | None = None
    interests: list[Interest] = Field(default_factory=list)
    alterations: list[Alteration] = Field(default_factory=list)
    # Registrar or member notes attached to the whole statement.
    notes: list[str] = Field(default_factory=list)
    source: Source
    extraction: Extraction

    def interests_in(self, category: Category) -> list[Interest]:
        return [i for i in self.interests if i.category == category]

    def alterations_in(self, category: Category) -> list[Alteration]:
        return [a for a in self.alterations if a.category == category]


class Person(BaseModel):
    """The roster row: who someone is, independent of any one statement."""

    model_config = ConfigDict(frozen=True)

    aph_id: str
    family_name: str
    given_names: str
    preferred_name: str | None = None
    honorific: str | None = None
    post_nominals: str | None = None
    gender: str | None = None
    chamber: Chamber
    party: str | None = None
    party_code: str | None = None
    state: str | None = None
    electorate: str | None = None
    # Which parliaments we hold a statement for, in either chamber.
    parliaments: list[int] = Field(default_factory=list)
    aph_url: str | None = None


# --- Source vocabularies -----------------------------------------------------

# House form item number -> category. Item 2 has two sub-tables (beneficial
# interest, trustee) that both map to TRUSTS with `role` distinguishing them.
HOUSE_ITEMS: dict[int, Category] = {
    1: Category.SHAREHOLDINGS,
    2: Category.TRUSTS,
    3: Category.REAL_ESTATE,
    4: Category.DIRECTORSHIPS,
    5: Category.PARTNERSHIPS,
    6: Category.LIABILITIES,
    7: Category.INVESTMENTS,
    8: Category.ACCOUNTS,
    9: Category.OTHER_ASSETS,
    10: Category.OTHER_INCOME,
    11: Category.GIFTS,
    12: Category.TRAVEL_HOSPITALITY,
    13: Category.MEMBERSHIPS,
    14: Category.OTHER_INTERESTS,
}

# House table column header (as printed on the form) -> canonical field.
HOUSE_COLUMNS: dict[str, str] = {
    "Name of company": "company",
    "Name of trust/nominee company": "name",
    "Nature of its operation": "nature",
    "Nature of operation": "nature",
    "Beneficial interests": "beneficial_interest",
    "Beneficiary of the trust": "beneficial_interest",
    "Location": "location",
    "Purpose for which owned": "purpose",
    "Activities of company": "activities",
    "Name": "name",
    "Nature of interest": "nature",
    "Activities of partnership": "activities",
    "Nature of liability": "nature",
    "Creditor": "creditor",
    "Type of investment": "type",
    "Body in which investment is held": "body",
    "Nature of account": "nature",
    "Name of bank/institution": "institution",
    "Nature of any other assets": "nature",
    "Nature of income": "nature",
    "Detail of gifts": "details",
    "Details of travel/hospitality": "details",
    "Name of organisation": "organisation",
}

# Senate API top-level key -> category.
SENATE_CATEGORIES: dict[str, Category] = {
    "shareHoldings": Category.SHAREHOLDINGS,
    "trusts": Category.TRUSTS,
    "realEstate": Category.REAL_ESTATE,
    "registeredDirectorshipsOfCompanies": Category.DIRECTORSHIPS,
    "partnerships": Category.PARTNERSHIPS,
    "liabilities": Category.LIABILITIES,
    "investments": Category.INVESTMENTS,
    "savingsOrInvestmentAccounts": Category.ACCOUNTS,
    "otherAssets": Category.OTHER_ASSETS,
    "otherIncome": Category.OTHER_INCOME,
    "gifts": Category.GIFTS,
    "sponsoredTravelOrHospitality": Category.TRAVEL_HOSPITALITY,
    "officeHolderDonating": Category.MEMBERSHIPS,
    "otherInterest": Category.OTHER_INTERESTS,
}

# Senate API interest field -> canonical field.
SENATE_FIELDS: dict[str, str] = {
    "nameOfCompany": "company",  # shareholdings, directorships; trusts remaps to "name"
    "activitiesOfCompany": "activities",
    "nature": "nature",
    "interest": "beneficial_interest",
    "type": "role",
    "location": "location",
    "purposeForWhichOwned": "purpose",
    "nameOfPartnership": "name",
    "natureOfInterest": "nature",
    "activitiesOfPartnership": "activities",
    "natureOfLiability": "nature",
    "creditor": "creditor",
    "typeOfInvestment": "type",
    "bodyOfWhichInvestmentIsHeld": "body",
    "natureOfAccount": "nature",
    "nameOfBankInstitution": "institution",
    "nameOfOtherAsset": "nature",
    "nameOfIncome": "nature",
    "detailOfGifts": "details",
    "detailOfTravelHospitality": "details",
    "nameOfOrganisation": "organisation",
}
