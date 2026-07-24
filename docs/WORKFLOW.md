# Workflow

How a screenshot becomes a case, and how a new scan gets compared against the base.

---

## A0. First question: new study, or another frame?

**One case is one study.** One acquisition can supply many screenshots — several levels,
several windows — and every one of them belongs in that case's `frames` array, not in a
case of its own.

This is the structural decision that everything else rests on. If two slices of a single
scan get filed as two cases, `compare` will dutifully report that findings appeared and
resolved between them, when all that changed was which level the frame cut through. The
tool guards against the obvious version of this — same pseudonym plus same study date
raises a warning that the two records look like one acquisition — but the guard only
works if study dates are recorded.

Signals that two screenshots are one study: same patient, same window, same crop and
table position, same body contour, same contrast appearance, anatomy that is
continuous between them. When it is suggestive but not certain, file them as one study,
note the assumption in `limitations`, and confirm.

## A. Adding a scan

**You:** drop the image into `inbox/` (or paste/attach it) and say what you know —
body region at minimum; patient pseudonym, study date, contrast phase, and clinical
context if you have them. Anything you don't know, leave out; a guess recorded as fact
is worse than a blank.

**Me:**

1. Read the image and work through
   [`templates/analysis-checklist.md`](../templates/analysis-checklist.md).
2. Flag any burned-in patient identifiers *before* the image is committed, so they get
   cropped first.
3. Scaffold the record: `python3 tools/ctdeck.py new --region <r> --patient <id> --image images/CASE-XXXX-frame-1.png`
   — or, if this frame belongs to a study already in the base, append it to that case's
   `frames` array instead of making a new case.
4. Fill in `frames`, `findings`, `impression`, `differential`, `confidence`,
   `limitations`. Point each finding's `seen_on` at the frames it was visible on.
5. Move each image to `images/CASE-XXXX-<frame-id>.<ext>`.
6. `python3 tools/ctdeck.py validate && python3 tools/ctdeck.py index`
7. `python3 tools/ctdeck.py similar CASE-XXXX` — if a prior for the same patient turns
   up, go straight to comparison.
8. Commit.

## B. Comparing a new scan

```bash
python3 tools/ctdeck.py compare CASE-0001 CASE-0004
```

Prior first, current second. The output has four blocks:

- **Matched findings** — paired by finding `id`, falling back to
  organ + laterality + location. Each pair shows the size delta in mm and percent, HU
  change, and any shift in enhancement or margins.
- **New on current study** — present now, absent before.
- **No longer identified** — present before, absent now. Worth reading literally: a
  finding can disappear because it resolved, or because no frame in the current study
  cuts through it, or because the current study's window cannot show it. Check the
  `seen_on` frames of the original finding against the frames of the current study
  before reading anything into a disappearance.
- **Overall** — one of `stable`, `progression`, `partial_response`, `mixed`,
  `resolved`, `indeterminate`.

### How the change categories are decided

Per lesion, on the longest recorded axis:

| Label | Rule |
|---|---|
| `larger` | grew ≥ 20% **and** ≥ 5 mm |
| `smaller` | shrank ≥ 30% |
| `stable` | anything between |
| `not_measurable` | size missing on either study |

Study level, on the sum of longest diameters (SLD) across matched findings:

| Label | Rule |
|---|---|
| `progression` | any new finding, **or** SLD up ≥ 20% and ≥ 5 mm |
| `partial_response` | SLD down ≥ 30% |
| `resolved` | nothing measurable remains |
| `mixed` | some findings resolved while the rest sit within stable bounds |
| `stable` | SLD change inside the thresholds |
| `indeterminate` | no measurable pairs to work from |

The thresholds are borrowed from RECIST 1.1 because they're the conventional line
between noise and real change. This is **not** a RECIST assessment — that requires
target-lesion selection, short-axis measurement for nodes, and review of the whole
volume, none of which a screenshot supports.

### Comparison caveats the tool raises

`compare` prints a warning when the two records look like one acquisition (same
pseudonym, same study date), or differ in patient id, body region, contrast phase,
imaging plane, or window.

Contrast phase is the one that bites most often: a lesion measured on portal venous and
again on non-contrast can shift 20% in apparent size without anything having changed
biologically. When you see that warning, treat the size deltas as unreliable rather than
as findings.

The window warning matters just as much. A lung nodule that is invisible on a
soft-tissue window is not a nodule that resolved — it is a nodule nobody looked for.

## C. Querying the base

```bash
python3 tools/ctdeck.py list --region chest        # everything chest
python3 tools/ctdeck.py list --patient PT-A        # one patient's studies
python3 tools/ctdeck.py list --tag follow-up
python3 tools/ctdeck.py similar CASE-0004          # pattern neighbours
python3 tools/ctdeck.py show CASE-0004 --json      # raw record
python3 tools/ctdeck.py deck --out deck.html       # browsable page
```

`cases/index.json` is generated — treat it as a build artefact and rebuild it with
`ctdeck.py index` rather than editing it.

## D. Trying it without touching your base

The `examples/` directory holds two **synthetic** records (no real patient, no real
image) that exist purely to demonstrate the format and the comparison output:

```bash
CTDECK_CASES=examples python3 tools/ctdeck.py compare CASE-9001 CASE-9002
```

## E. Keeping the base honest

- Correct old records when a later study revises them; don't leave contradictions.
- Don't upgrade `confidence` retroactively because a later scan agreed — the record
  should reflect what that frame supported at the time.
- When a finding turns out to have been artefact, keep the record and note it. A base
  that only remembers its hits teaches the wrong lessons.
