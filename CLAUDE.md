# Agent guidelines

Peculiar Interests: an open, versioned dataset and static site of the registers
of interests of Australian federal MPs and senators. Sibling of
`~/projects/aps-ai-tracker` (same shape: Python fetch/parse committed to git,
Astro site on GitHub Pages, nightly cron on weddle).

## Commands

Project has its own `mise.toml`: prefix commands with `mise exec --`.

- `uv run pollie --help` for the CLI: `fetch`/`parse` take a target
  (`house`, `senate`, `roster`, `all`); `people`, `schema`, `status`, `ocr PDF`;
  `run` is the nightly sequence. `pollie ocr` needs `uv run --group ocr`.
- `uv run python -m pytest` (parallel; `-m live` adds tests that hit aph.gov.au)
- `uv run ruff check . && uv run ruff format --check .`
- `uvx ty check`
- Site: `cd site && pnpm run {dev,build,lint,lint:css,typecheck,test,format}`

## Sources

- **Senate**: undocumented JSON API behind the register's React app,
  `https://pbs-apim-aqcdgxhvaug7f8em.z01.azurefd.net/api` (`queryStatements`,
  `getSenatorStatement?cdapid=`, `GetParties`). Send an
  `Origin: https://www.aph.gov.au` header. Structured interests per category;
  alterations are free text with a date. Current parliament only.
- **House**: index table at `/Senators_and_Members/Members/Register` (name,
  "Last updated", link). Most links are
  `https://interests-register-api-public.aph.gov.au/api/members/{aph_id}/statement/{parl}`,
  a system-generated PDF whose tables pdfplumber reads cleanly. A few are
  handwritten scans on `static.aph.gov.au`; those go through `pollie ocr` and a
  reviewed override. The parser merges lines onto the shortest column when a
  member's cell has more lines than its neighbours (a typed line break is
  indistinguishable from a new row by spacing alone) and records that in
  `extraction.notes`; it also joins header-less table fragments that spilled
  onto a new page. Anything else unrecognised raises.
- `raw/ocr-drafts/` holds unreviewed `pollie ocr` output for the pending scans.
  Reviewing one means correcting it against the PDF, setting
  `extraction.method = "manual"`, and moving it to `overrides/48/house/`.
- aph.gov.au 403s non-browser user agents; `fetch.client()` handles it.
- Both chambers use the same APH person ID (`aph_id`), which is also the
  `aph id` in OpenAustralia's people.csv. Never invent another identifier.

## Data model and layout

`schema.py` is the single vocabulary (14 categories, canonical field names,
source mapping tables); `paths.py` is the single layout. Read both before
touching any ingest code. Raw fetches are committed as evidence; `data/` holds
one `Statement` JSON per person per parliament and is regenerated from `raw/` by
the parsers, so never hand-edit `data/`. Hand corrections go in `overrides/`,
which the parser applies last.

aph.gov.au content is CC BY-NC-ND 3.0 AU: keep the PDFs in the repo as evidence
and link to APH as the canonical copy, don't serve them from the site. The
extracted dataset itself is CC BY 4.0.

## Nightly run and deploy

`cron-run.sh` (systemd units in `ops/systemd/`, 04:00 on weddle) fetches,
parses, commits `raw/` + `data/` and pushes; the Pages workflow rebuilds the site
from the committed data and refuses to deploy if `data/` is not in step with
`raw/` and the parsers. No model, no secrets, anywhere in that path.

## Code patterns

Pydantic models at the boundary, pure functions over them inside. Loguru, not
print. Exceptions bubble; a parser that meets a layout it doesn't recognise
raises rather than guessing, so a form change is loud.
