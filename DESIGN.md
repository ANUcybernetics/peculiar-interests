# Design

Visual system for the Peculiar Interests site (`site/`). Strategy lives in
[PRODUCT.md](PRODUCT.md); this captures how it looks. Tokens are defined in
`site/src/styles/tokens.css` and applied in `site/src/styles/global.css`.

## Overview

A public register redrawn as a well-set ledger. The source material is a
government form: numbered items, ruled tables, "Not Applicable", a registrar's
stamp. The site quotes that vernacular (item rubrics, ruled rows, a form-style
identity block) and sets it in a single quirky grotesque so it reads as a
publication with a point of view, not a scan of the form.

**The unifying idea:** the two chamber colours of the Australian Parliament,
House green and Senate red, are the only colour in the system. They mark whose
chamber a person, row or figure belongs to, everywhere and only that. Everything
else is ink on paper, plus one manila wash for the filing-cabinet moments
(pending scans, registrar stamps, "peculiar" callouts).

Light only (`color-scheme: light`), as with the sibling APS tracker: one context
tuned properly.

## Colour

OKLCH throughout. Strategy: **two chamber hues carry all meaning**; no third
accent, no gradients.

| Role                 | Token           | Value                   |
| -------------------- | --------------- | ----------------------- |
| Paper                | `--bg`          | `oklch(98.3% 0.004 95)` |
| Surface              | `--surface`     | `oklch(96.2% 0.006 95)` |
| Ink                  | `--text`        | `oklch(23% 0.012 160)`  |
| Muted                | `--muted`       | `oklch(46% 0.015 160)`  |
| Rule                 | `--rule`        | `oklch(86% 0.008 120)`  |
| Rule strong          | `--rule-strong` | `oklch(70% 0.012 120)`  |
| House green          | `--house`       | `oklch(46% 0.11 155)`   |
| House wash           | `--house-wash`  | `oklch(95% 0.03 155)`   |
| Senate red           | `--senate`      | `oklch(48% 0.16 25)`    |
| Senate wash          | `--senate-wash` | `oklch(95.5% 0.03 25)`  |
| Manila (stamp, file) | `--manila`      | `oklch(93% 0.06 85)`    |
| Manila ink           | `--manila-ink`  | `oklch(45% 0.09 75)`    |

Both chamber colours clear AA on paper as text (≥5.5:1) and as 3px rules. Links
are ink with a chamber-coloured underline when they point at a person or chamber
page, and a rule-strong underline otherwise. Colour never carries meaning alone:
every chamber mark pairs with the word "House" or "Senate", and every
additions/deletions ledger pairs its colour with a plus or minus glyph and a
label.

## Typography

One family. **Bricolage Grotesque Variable** (`--font-sans`) carries display,
body and tables; its optical-size axis makes headlines quirky and small text
plain without a second face. Weight 400 body, 600 for table headers and item
rubrics, 800 for headlines with slight negative tracking and
`text-wrap: balance`. Tabular figures (`font-variant-numeric: tabular-nums`) in
every table and date so the ledger columns line up. **IBM Plex Mono**
(`--font-mono`) appears only for the API examples and the raw-file hashes: code,
not decoration.

Fluid modular scale `--text-xs` … `--display` (clamp()ed, ≈1.25 ratio). Prose
measure 66ch; tables run full width and scroll horizontally inside their own
container at narrow widths.

## Layout

Left-aligned throughout. Page max 76rem with fluid gutters. Sections are
separated by rules, not boxes; there are no cards. The person page is a
two-column grid on wide screens (a narrow rubric column for the item number and
name, a wide column for the declared rows) that stacks below 48rem via a
container query. Tables use sticky headers.

The identity block at the top of a person page is the one place that quotes the
form literally: small-caps labels (family name, given names, electorate or
state) over the values, ruled above and below, with the chamber colour as the
top rule.

## Components

- **Masthead** (`Nav.astro`): the wordmark "Peculiar Interests" at weight 800, a
  one-line description, and a short row of section links with the current
  section underlined in ink. No sticky behaviour; the page is the thing.
- **Ledger** (`Ledger.astro`): the memorable element. Dated alteration rows:
  date (tabular), person with chamber underline, the item rubric ("12. Sponsored
  travel"), then the details verbatim. Additions carry a "+" and deletions a "−"
  in the rubric column. Used on the home page (recent changes) and on each
  person page.
- **Item block** (`ItemBlock.astro`): one of the fourteen items on a person
  page. Rubric column with the number and short name; rows with a holder column
  (Self / Spouse or partner / Dependent children) and the declared fields. Empty
  items collapse to a single quiet line ("Nothing declared").
- **Chamber mark** (`ChamberMark.astro`): the word "House" or "Senate" with its
  coloured underline; used inline after names in lists and tables.
- **Roster table** (`RosterTable.astro` + `RosterFilter.svelte`): people with
  chamber, party, state or electorate, last updated, and a count of declared
  items. Sortable by column; the Svelte island adds a text filter and party or
  chamber facets on top of a table that already works.
- **Mention lists**: every company, creditor, institution and sponsor string is
  a page listing who declared it. Rendered as ruled rows, never chips.
- **Source box** (`SourceBox.astro`): at the foot of every person page: link to
  the official document, when we fetched it, how it was read (API, text-layer
  PDF, OCR under review, hand-confirmed), and the parser version. Pending scans
  get a manila notice rather than an empty page.

## Motion

Cross-document view transitions on internal navigation, gated on
`prefers-reduced-motion: no-preference`; no scroll-triggered entrances. Hover
and focus states are colour and underline changes only.

## Accessibility

WCAG 2.2 AA. Semantic tables with `<th scope>`, a skip link, visible
`:focus-visible` rings (2px ink, offset), reduced-motion fallbacks, and every
colour-coded state paired with text.
