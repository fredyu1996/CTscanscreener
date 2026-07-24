# Hounsfield reference

Attenuation values used when filling `attenuation_hu` on a finding. HU is the single
most transferable number in the base — it survives across scanners and studies in a way
that "looks bright" does not.

## Typical values

| Tissue / material | HU (approx) |
|---|---|
| Air | −1000 |
| Lung parenchyma | −900 to −400 |
| Fat | −120 to −60 |
| Water / simple fluid | −10 to +10 |
| Simple cyst | ≤ 20 |
| Renal cyst, indeterminate band | 20 to 70 |
| Soft tissue / muscle | +30 to +60 |
| Unenhanced liver | +50 to +70 |
| Fresh clotted blood | +45 to +75 |
| Acute haemorrhage (intracranial) | +50 to +100 |
| Contrast-enhanced vessel | +150 to +400+ |
| Calcification | +150 to +1000 |
| Cortical bone | +500 to +2000 |
| Metal / hardware | > +2000 (streak artefact) |

## Rules of thumb

- **< 20 HU on a non-contrast study** with a thin wall and no septations → simple cyst.
- **Enhancement** is a *change* of ≥ 20 HU between pre- and post-contrast at the same
  site. A single post-contrast frame cannot establish enhancement — record
  `not_assessable` rather than inferring it.
- **Macroscopic fat** (any voxel < −30 HU) inside a lesion is a strong pointer:
  angiomyolipoma in kidney, lipoma, teratoma, adrenal myelolipoma.
- **Adrenal adenoma**: ≤ 10 HU unenhanced is the classic threshold.
- **Fatty liver**: liver at least 10 HU below spleen on non-contrast.
- **Hyperdense on non-contrast** in a fluid collection → blood, protein, or contrast,
  not simple fluid.

## Windowing

A window is a display choice, not data. The same voxels look completely different
between windows, so record which window the frame was shown in.

| Window | Level / Width (approx) | Shows |
|---|---|---|
| Soft tissue | 50 / 400 | Solid organs, fluid, fat planes |
| Lung | −600 / 1500 | Parenchyma, nodules, ground-glass, emphysema |
| Bone | 400 / 1800 | Cortex, trabeculae, fractures |
| Brain | 40 / 80 | Grey–white differentiation |
| Stroke | 32 / 8 | Early ischaemic change |
| Liver | 60 / 150 | Subtle hepatic lesion conspicuity |
| Mediastinal | 50 / 350 | Nodes, vessels, fat planes |

A nodule that is obvious on lung window can be invisible on soft tissue window. If the
screenshot shows only one window, that is a `limitation` worth recording.

## Artefacts that mimic findings

- **Beam hardening / streak** — dark and bright bands off dense material (metal,
  contrast, shoulders). Reads as a pseudo-lesion in adjacent tissue.
- **Partial volume averaging** — a structure only partly within the slice averages with
  its neighbours, blurring margins and skewing HU. Worst on thick slices.
- **Motion** — doubled or smeared edges, most often diaphragm, heart, bowel.
- **Photon starvation** — noisy streaks through the shoulders and pelvis in larger
  patients.
- **Ring artefact** — concentric rings from a miscalibrated detector element.
