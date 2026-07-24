# Analysis checklist

The pass I work through on every screenshot before writing the case record. Keeps
reads consistent across the base, so comparisons later are comparing like with like.

## 1. Establish what the image even is

Before describing anything, settle the frame's identity — a misread window or phase
poisons everything downstream.

- **Plane** — axial, coronal, sagittal, or a reconstruction.
- **Window** — soft tissue, lung, bone, brain. Read it off the appearance: black lung
  fields with sharp vessels means lung window; grey uniform parenchyma means soft tissue.
- **Contrast phase** — non-contrast, arterial (bright aorta, unopacified portal vein),
  portal venous (bright liver parenchyma and portal vein), delayed/excretory (contrast
  in the collecting system). If uncertain, record `unknown` rather than guessing.
- **Level** — name the anatomic landmark in frame (carina, porta hepatis, iliac crests).
- **Burned-in annotations** — measurement callipers, HU ROI values, scale bar, slice
  thickness. These are free data; capture them.
- **Patient identifiers** — if any name/MRN/DOB is visible, flag it so it gets cropped
  before the image is committed.

## 2. Systematic survey

Region-specific sweeps, run in the same order every time so nothing is skipped:

**Chest** — lungs (each lobe, both windows if available), pleura, airways, mediastinum,
hila, heart and great vessels, oesophagus, chest wall, visible upper abdomen, bones.

**Abdomen/pelvis** — liver, biliary tree and gallbladder, pancreas, spleen, adrenals,
kidneys and collecting systems, bowel (calibre, wall, gas pattern), mesentery and
peritoneum, vasculature, retroperitoneum, pelvic organs, bones, body wall.

**Head** — grey–white differentiation, ventricles and cisterns, midline shift,
extra-axial spaces, vascular densities, sinuses and mastoids, calvarium.

**Spine/MSK** — alignment, vertebral body height, disc spaces, canal and foramina,
cortical integrity, marrow density, soft tissues.

## 3. Characterise each finding

For every abnormality, capture what makes it comparable across studies:

| Attribute | Why it matters |
|---|---|
| Organ + laterality + location | The identity key — comparison matches on this |
| Size (longest axis first, up to 3) | Interval change is computed off this |
| Attenuation in HU | Separates cyst from solid, fat from soft tissue, haemorrhage from fluid |
| Margins | Well-defined vs spiculated/infiltrative carries weight |
| Enhancement pattern | Rim, washout, avid, hypovascular — only meaningful with known phase |
| Morphology | Cystic, solid, ground-glass, cavitary, calcified, necrotic |
| Significance + certainty | Keeps the confident and the speculative visibly separate |

Give each finding a **stable slug** (`liver-seg7-lesion`, not `finding-1`) and reuse
the same slug on follow-up studies of that patient. That slug is what pairs findings
across studies during comparison.

## 4. Synthesise

- **Impression** — plain language, what the frame shows overall.
- **Differential** — candidates with what supports and what argues against each.
- **Confidence** — honest. A single unlabelled frame rarely supports `high`.
- **Limitations** — write these down rather than leaving them implied. Single frame,
  unknown phase, no priors, motion artefact, partial volume averaging, beam hardening.

## 5. Position against the base

- Run `ctdeck.py similar <case>` — does the base already hold a prior for this patient,
  or a comparable pattern?
- If a prior exists, run `ctdeck.py compare <prior> <current>` and record the result in
  `compare_to`.
- If the read revises something recorded earlier, update the older case rather than
  letting two contradictory records sit in the base.
