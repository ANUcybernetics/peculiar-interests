# Product

## Register

brand

## Users

Journalists, researchers, integrity and governance people, and curious
Australians who want to know what a federal MP or senator has declared: the
investment properties, the trusts, the football tickets, the Chairman's Lounge.
They arrive with a name or a question ("who has declared shares in X?", "what
did Y add last month?", "which MPs own the most property?") and they need an
answer they can cite and trace back to the lodged document.

## Product purpose

A complete, open, versioned record of both federal registers of interests,
extracted into one consistent schema and published as a browsable site with
downloadable data and a static JSON API. Every line item links back to the
official document it came from. Success is a reader finding the fact in under a
minute, seeing when it was declared, and trusting it enough to quote.

## Brand personality

Peculiar Interests: dry, precise, a little amused. It takes the register
seriously and the pollies lightly. The wit is in the framing and the headlines,
never in the data, which is presented plainly and faithfully. Authority comes
from showing the working: source links, dates, the raw document, the parser
version. A public-interest project from a cybernetics studio, not a campaign and
not a vendor.

## Anti-references

Corporate dashboard templates (KPI tiles, gradient charts). The stock gov.au
look. Gotcha journalism styling (red circles, "EXPOSED"). Arty editorial
pastiche with drop caps and display serifs. Paywall-shaped landing pages.

## Design principles

- **On the record.** Every figure traces to a document and a date. Show the
  source, the lodgement date, and how the text was extracted.
- **One register, two houses.** Present the fourteen categories the same way for
  a senator and a member; the chamber is a detail, not a fork in the site.
- **Peculiar is a feature.** The odd entries (a plaque, a signed guernsey, a
  book advance) are what people remember; surface them without sneering.
- **Cross-link everything.** A company, a creditor, a sponsor, an electorate:
  each is a page that lists everyone who declared it. Discovery happens by
  following links, not by knowing what to search.
- **Legible first.** Dense tabular data at AA contrast, readable at phone width,
  usable without JavaScript. Search and filters are enhancements on top of pages
  that already work.

## Accessibility and inclusion

WCAG 2.2 AA. Semantic HTML, visible focus, a skip link, tables with real
headers, colour never the only signal, `prefers-reduced-motion` honoured. Spouse
and dependent-child interests are public record and are shown, but as the rules
frame them: a holder column, not a headline.
