# CT Scan Screener

A personal **CT scan information deck** — a structured, growing knowledge base built
from CT screenshots you supply. Each scan you share gets read, described in a
consistent structured format, and filed into the base. Once the base has cases in
it, any new scan can be compared against it: against the same patient's prior
studies (interval change) and against the reference patterns accumulated so far.

> **Not a diagnostic tool.** Everything here is descriptive image interpretation for
> study, reference, and organisation. A screenshot is a single 2D frame of a 3D volume
> with unknown windowing and no DICOM metadata — that is not enough to diagnose
> anyone. Nothing in this repository should drive a clinical decision. Always defer to
> the reporting radiologist and the full study.

---

## How it works

```
  you drop a screenshot          Claude reads it              case JSON written
  into inbox/                →   & fills the schema      →    into cases/
                                                                    │
  new scan arrives           ←   compare against         ←─────────┘
                                 base + priors
```

1. **Add a scan.** Drop the image anywhere in the repo (`inbox/` is the default
   landing spot) and tell me about it. Minimum useful context: body region, and if
   you have it, patient ID/pseudonym, study date, contrast phase. Say whether a new
   frame belongs to a study already in the base — that decides whether it joins an
   existing case or starts a new one.
2. **I analyse it.** I read the image, describe what's visible, and write a case
   record — one JSON file per study in `cases/`, validated against
   [`schema/case.schema.json`](schema/case.schema.json).
3. **The base grows.** `ctdeck.py index` keeps `cases/index.json` current — a
   fast-lookup table of every case, region, and finding.
4. **Compare.** When a new scan arrives, `ctdeck.py compare` puts it against a prior
   study and reports matched findings with size deltas, new findings, resolved
   findings, and an overall interval-change category. `ctdeck.py similar` searches
   the whole base for comparable cases.

## Quick start

```bash
# list everything in the base
python3 tools/ctdeck.py list

# show one case in full
python3 tools/ctdeck.py show CASE-0001

# compare two studies of the same patient
python3 tools/ctdeck.py compare CASE-0001 CASE-0004

# find cases in the base resembling a new one
python3 tools/ctdeck.py similar CASE-0004

# validate every record against the schema
python3 tools/ctdeck.py validate

# rebuild the index after editing cases by hand
python3 tools/ctdeck.py index

# render the whole base as a browsable HTML deck
python3 tools/ctdeck.py deck --out deck.html
```

No dependencies beyond the Python 3.9+ standard library.

## Layout

| Path | What it holds |
|---|---|
| `cases/` | One `CASE-XXXX.json` per study — the knowledge base itself |
| `cases/index.json` | Generated lookup table; rebuild with `ctdeck.py index` |
| `images/` | Source screenshots, named to match their case and frame |
| `inbox/` | Drop zone for scans not yet processed |
| `schema/case.schema.json` | The record format every case conforms to |
| `templates/` | Blank case template + the analysis checklist I work through |
| `reference/` | Accumulated cross-case knowledge: HU values, patterns, terminology |
| `tools/ctdeck.py` | CLI for indexing, validating, comparing, and rendering |

## What a case record captures

**One case is one study, not one screenshot.** A single acquisition can supply many
frames — different levels, different windows — and they all live in that case's
`frames` array. This matters: if two slices of one scan became two cases, comparing
them would report findings appearing and vanishing purely because of which level each
frame cut through. Findings can name the frames they were `seen_on`, so absence is
never confused with resolution.

Beyond that: study context (region, contrast phase, slice thickness), per-finding
detail (organ, laterality, location, size in up to 3 axes, attenuation in HU, margins,
enhancement, morphology), an overall impression, and an explicit `confidence` +
`limitations` block so the weak parts of a screenshot-only read stay visible rather
than getting laundered into false certainty.

See [`templates/case-template.json`](templates/case-template.json) for the blank
form and [`docs/WORKFLOW.md`](docs/WORKFLOW.md) for the full ingest and
comparison procedure.

## Privacy

CT screenshots often carry a patient name, MRN, and date of birth burned into the
image corners. **Crop or black those out before adding them here.** Use a pseudonym
in `patient.id`. `.gitignore` deliberately does *not* exclude `images/` — if you would
rather keep pixels out of git entirely, uncomment the `images/` line there and the
case records will still work, just without their source frames.
