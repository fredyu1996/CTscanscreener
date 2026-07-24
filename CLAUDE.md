# CLAUDE.md

Working instructions for this repository. Read before processing any scan.

## What this repo is

A personal CT knowledge base. The user supplies CT screenshots; I read them, record a
structured case per study in `cases/`, and compare new scans against what the base
already holds. `tools/ctdeck.py` is the only tooling — standard library, no deps.

## Framing — this matters more than the code

Descriptive image interpretation for reference and study. Not diagnosis, not clinical
advice, not a basis for any decision about a real person's care.

Hold both halves of that honestly:

- **Do the work.** Read the image properly and describe what is there in specific,
  technical terms. Vague hedging dressed up as caution is not caution — it is a worse
  product. Name findings, measure them, give a differential with reasoning.
- **Don't overclaim.** A screenshot is one 2D frame of a 3D volume, usually without
  DICOM metadata, one window, one phase, no priors, no clinical history. Say what that
  frame cannot establish rather than letting the omission imply certainty.

State the framing once, clearly, when it is relevant — typically the first read in a
session or when a finding is significant. Do not re-litigate it on every reply; the
user knows what this is.

If a finding would be critical if real — free intraperitoneal gas, acute haemorrhage,
aortic dissection, tension pneumothorax, bowel ischaemia — say so plainly and directly,
and note that it needs real-time review of the actual study, not a screenshot read.
Under-calling something time-critical is the worse failure.

## One case is one study

Before writing anything, decide whether a new screenshot is a **new study** or
**another frame of a study already in the base**. Same patient, same window, same crop
and table position, same contrast appearance, adjacent anatomy — that is one
acquisition, and the frames belong in one case's `frames` array. Splitting them into
separate cases corrupts the base: `compare` would then report findings appearing and
resolving purely because of which level each frame cut through. When the evidence is
suggestive but not conclusive, record it as one study, say so in `limitations`, and ask
the user to confirm.

`compare` refuses to be quiet about this — same pseudonym plus same study date raises a
warning that the two records look like one acquisition.

## Adding a case

1. Read the image. Work through `templates/analysis-checklist.md` — the whole sweep, in
   order, every time. Consistency across the base is what makes later comparison worth
   anything.
2. **Check for burned-in patient identifiers** (name, MRN, DOB, accession) in the image
   corners. If any are visible, tell the user before committing the image and offer to
   crop. Never commit an image carrying real identifiers.
3. `python3 tools/ctdeck.py new --region <region> --patient <pseudonym> --image images/CASE-XXXX.png`
4. Fill the record. Rules that keep the base usable:
   - Finding `id` is a **stable slug** describing the thing (`liver-seg7-lesion`), reused
     across every study of that patient. Comparison pairs on it.
   - `seen_on` names the frames a finding was actually visible on. A finding absent from
     a frame that does not cut through it has not resolved — it was never in view.
   - `size_mm` longest axis first. Only record measurements actually readable from the
     frame — a burned-in calliper, a scale bar, or a stated field of view. If nothing
     supports a measurement, leave it null and say so in `limitations` rather than
     eyeballing a number that later gets compared as if it were real.
   - `attenuation_hu` only where an ROI value is displayed or the density is
     unambiguous by window. Guessed HU is worse than absent HU.
   - `confidence: high` needs genuine justification. Most single screenshots are
     `low` or `moderate`.
   - `limitations` is never empty for a screenshot-derived record.
5. Save each image as `images/CASE-XXXX-<frame-id>.<ext>` and set the frame's `image`.
   If a screenshot arrives as a chat attachment rather than a file, it is not on disk —
   leave `image` null, say so in `notes`, and ask the user to drop the file in `inbox/`.
6. `python3 tools/ctdeck.py validate && python3 tools/ctdeck.py index`
7. `python3 tools/ctdeck.py similar CASE-XXXX` — surface priors and comparable cases.
8. Commit to the working branch.

## Comparing

```bash
python3 tools/ctdeck.py compare <prior> <current>
```

Prior first. Read the tool's warnings before trusting its numbers — differing contrast
phase or plane between studies makes size deltas unreliable, and the tool says so.

Translate the output into prose for the user rather than pasting the raw table: what
changed, by how much, what's new, what's gone, and which parts of that are solid versus
artefact-of-the-frame. Then record the comparison in the current case's `compare_to`.

## Growing the reference material

When a case teaches something reusable, add it to `reference/patterns.md` with the case
ID attached. When a case revises an earlier read, **update the earlier record** — do not
leave two contradictory entries in the base. Keep records of findings that turned out to
be artefact; a base that only remembers its hits teaches the wrong lessons.

## Conventions

- Patient identifiers are always pseudonyms (`PT-A`, `PT-DEMO`).
- `cases/index.json` is generated. Rebuild it, don't hand-edit it.
- `examples/` holds synthetic records for demonstrating the format. They are not real
  and must never be treated as reference cases. Exercise them with
  `CTDECK_CASES=examples`.
- Run `validate` before every commit that touches `cases/`.
