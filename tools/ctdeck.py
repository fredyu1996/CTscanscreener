#!/usr/bin/env python3
"""ctdeck — manage the CT scan information deck.

A case is one JSON file in cases/, conforming to schema/case.schema.json.
This tool indexes them, validates them, compares two studies, finds similar
cases in the base, and renders the whole thing as a browsable HTML deck.

Standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
# CTDECK_CASES points the tool at a different set of records — used to exercise
# the synthetic examples/ without touching the real base.
CASES_DIR = Path(os.environ.get("CTDECK_CASES", ROOT / "cases")).resolve()
IMAGES_DIR = ROOT / "images"
SCHEMA_PATH = ROOT / "schema" / "case.schema.json"
INDEX_PATH = CASES_DIR / "index.json"

CASE_RE = re.compile(r"^CASE-\d{4}$")

# Per-lesion interval-change thresholds. Descriptive, RECIST-flavoured, not a
# formal RECIST 1.1 implementation (that needs target-lesion selection rules,
# nodal short-axis handling, and full-volume review).
GROWTH_PCT = 20.0
GROWTH_ABS_MM = 5.0
SHRINK_PCT = 30.0


# --------------------------------------------------------------------------
# Minimal JSON Schema (draft-07 subset) validator
# --------------------------------------------------------------------------

def _type_ok(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def validate_against(value: Any, schema: dict, root: dict, path: str = "") -> list[str]:
    """Validate `value`, returning a list of human-readable error strings."""
    errors: list[str] = []
    where = path or "<root>"

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return [f"{where}: unsupported $ref {ref!r}"]
        target: Any = root
        for part in ref[2:].split("/"):
            target = target[part]
        return validate_against(value, target, root, path)

    if "type" in schema:
        expected = schema["type"]
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, t) for t in allowed):
            return [f"{where}: expected type {'/'.join(allowed)}, got {type(value).__name__}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} not one of {schema['enum']}")

    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{where}: {value!r} does not match /{schema['pattern']}/")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{where}: shorter than minLength {schema['minLength']}")
        if schema.get("format") == "date" and not _is_date(value):
            errors.append(f"{where}: {value!r} is not a YYYY-MM-DD date")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{where}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{where}: {value} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{where}: {value} must be > {schema['exclusiveMinimum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{where}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{where}: allows at most {schema['maxItems']} item(s)")
        if "items" in schema:
            for i, item in enumerate(value):
                errors += validate_against(item, schema["items"], root, f"{where}[{i}]")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing required field {key!r}")
        props = schema.get("properties", {})
        for key, sub in value.items():
            if key in props:
                child = f"{where}.{key}" if path else key
                errors += validate_against(sub, props[key], root, child)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{where}: unexpected field {key!r}")

    return errors


def rel(path: Path) -> str:
    """Path relative to the repo root when it lives inside it, else absolute."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def case_paths() -> list[Path]:
    return sorted(p for p in CASES_DIR.glob("CASE-*.json"))


def load_case(case_id: str) -> dict:
    path = CASES_DIR / f"{case_id}.json"
    if not path.exists():
        raise SystemExit(f"No such case: {case_id} (expected {path})")
    return json.loads(path.read_text())


def load_all() -> list[dict]:
    return [json.loads(p.read_text()) for p in case_paths()]


def next_case_id() -> str:
    used = {int(p.stem.split("-")[1]) for p in case_paths()}
    n = 1
    while n in used:
        n += 1
    return f"CASE-{n:04d}"


# --------------------------------------------------------------------------
# Finding helpers
# --------------------------------------------------------------------------

def longest_axis(finding: dict) -> float | None:
    sizes = finding.get("size_mm")
    return max(sizes) if sizes else None


def finding_key(finding: dict) -> str:
    """Fallback identity when finding ids differ between studies."""
    parts = [
        (finding.get("organ") or "").lower(),
        (finding.get("laterality") or "").lower(),
        (finding.get("location") or "").lower(),
    ]
    return "|".join(re.sub(r"[^a-z0-9]+", "", p) for p in parts)


def match_findings(prior: dict, current: dict) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Pair findings across two studies.

    Returns (matched pairs, resolved-in-current, new-in-current). Matching is by
    finding id first, then by organ/laterality/location key.
    """
    prior_findings = list(prior.get("findings", []))
    current_findings = list(current.get("findings", []))

    matched: list[tuple[dict, dict]] = []
    unmatched_prior = list(prior_findings)
    unmatched_current = list(current_findings)

    for keyfn in (lambda f: f.get("id"), finding_key):
        remaining_prior: list[dict] = []
        for pf in unmatched_prior:
            hit = next((cf for cf in unmatched_current if keyfn(cf) == keyfn(pf)), None)
            if hit is not None:
                matched.append((pf, hit))
                unmatched_current.remove(hit)
            else:
                remaining_prior.append(pf)
        unmatched_prior = remaining_prior

    return matched, unmatched_prior, unmatched_current


def classify_change(prior_mm: float | None, current_mm: float | None) -> tuple[str, float | None, float | None]:
    """Classify one lesion's interval change. Returns (label, delta_mm, pct)."""
    if prior_mm is None or current_mm is None:
        return "not_measurable", None, None
    delta = current_mm - prior_mm
    pct = (delta / prior_mm) * 100 if prior_mm else None
    if pct is None:
        return "not_measurable", delta, None
    if pct >= GROWTH_PCT and delta >= GROWTH_ABS_MM:
        return "larger", delta, pct
    if pct <= -SHRINK_PCT:
        return "smaller", delta, pct
    return "stable", delta, pct


def overall_change(matched, resolved, new_findings) -> tuple[str, str]:
    """Summarise the study-level interval change. Returns (label, rationale)."""
    if new_findings:
        return "progression", f"{len(new_findings)} new finding(s) not present on the prior study"

    if not matched:
        if resolved:
            return "resolved", (f"none of the {len(resolved)} prior finding(s) identified "
                                f"on the current study")
        return "indeterminate", "no findings recorded on either study"

    measurable = [(p, c) for p, c in matched if longest_axis(p) and longest_axis(c)]
    prior_sld = sum(longest_axis(p) for p, _ in measurable)
    current_sld = sum(longest_axis(c) for _, c in measurable)

    if not measurable:
        if resolved:
            return "partial_response", f"{len(resolved)} finding(s) no longer identified, remainder not measurable"
        return "indeterminate", "no measurable lesion pairs to compare"

    delta = current_sld - prior_sld
    pct = (delta / prior_sld) * 100 if prior_sld else 0.0

    if pct >= GROWTH_PCT and delta >= GROWTH_ABS_MM:
        return "progression", f"summed longest diameters {pct:+.0f}% ({delta:+.1f} mm)"
    if pct <= -SHRINK_PCT:
        return "partial_response", f"summed longest diameters {pct:+.0f}% ({delta:+.1f} mm)"
    if resolved:
        return "mixed", f"{len(resolved)} finding(s) resolved, remainder {pct:+.0f}%"
    return "stable", f"summed longest diameters {pct:+.0f}% ({delta:+.1f} mm)"


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    cases = load_all()
    if args.region:
        cases = [c for c in cases if c["study"].get("region") == args.region]
    if args.patient:
        cases = [c for c in cases if (c.get("patient") or {}).get("id") == args.patient]
    if args.tag:
        cases = [c for c in cases if args.tag in c.get("tags", [])]

    if not cases:
        print("No cases in the base yet." if not any((args.region, args.patient, args.tag))
              else "No cases match that filter.")
        return 0

    print(f"{'ID':<11} {'PATIENT':<9} {'DATE':<11} {'REGION':<16} {'FIND':>4}  IMPRESSION")
    print("-" * 100)
    for case in cases:
        patient = (case.get("patient") or {}).get("id") or "-"
        date = case["study"].get("study_date") or case.get("added") or "-"
        impression = case["impression"].replace("\n", " ")
        if len(impression) > 44:
            impression = impression[:41] + "..."
        print(f"{case['case_id']:<11} {patient:<9} {date:<11} "
              f"{case['study'].get('region', '-'):<16} {len(case.get('findings', [])):>4}  {impression}")
    print(f"\n{len(cases)} case(s).")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    case = load_case(args.case_id)
    if args.json:
        print(json.dumps(case, indent=2))
        return 0

    study = case["study"]
    patient = case.get("patient") or {}
    print(f"\n{case['case_id']}  ({case['study'].get('region', '?')})")
    print("=" * 72)
    if patient.get("id"):
        bits = [f"patient {patient['id']}"]
        if patient.get("age") is not None:
            bits.append(f"{patient['age']}y")
        if patient.get("sex"):
            bits.append(patient["sex"])
        print("  " + ", ".join(bits))
    if patient.get("clinical_context"):
        print(f"  context: {patient['clinical_context']}")
    print(f"  study:   {study.get('study_date') or 'date unknown'}"
          f"  |  {study.get('contrast') or 'contrast unknown'}")

    frames = case.get("frames", [])
    if frames:
        print(f"\nFRAMES ({len(frames)})")
        for fr in frames:
            tech = ", ".join(str(fr.get(k)) for k in ("plane", "window") if fr.get(k))
            print(f"  [{fr['id']}]{'  ' + tech if tech else ''}")
            if fr.get("slice_level"):
                print(f"      level: {fr['slice_level']}")
            if fr.get("image"):
                print(f"      image: {fr['image']}")

    findings = case.get("findings", [])
    print(f"\nFINDINGS ({len(findings)})")
    print("-" * 72)
    if not findings:
        print("  none recorded — unremarkable read")
    for f in findings:
        print(f"  [{f['id']}] {f['organ']}"
              f"{' ' + f['laterality'] if f.get('laterality') and f['laterality'] != 'n/a' else ''}"
              f"{' — ' + f['location'] if f.get('location') else ''}")
        print(f"      {f['description']}")
        detail = []
        if f.get("size_mm"):
            detail.append(" x ".join(f"{s:g}" for s in f["size_mm"]) + " mm")
        hu = f.get("attenuation_hu") or {}
        if hu.get("value") is not None:
            detail.append(f"{hu['value']:g} HU")
        elif hu.get("min") is not None or hu.get("max") is not None:
            detail.append(f"{hu.get('min', '?')}–{hu.get('max', '?')} HU")
        if hu.get("qualitative"):
            detail.append(hu["qualitative"])
        for key in ("margins", "enhancement", "significance", "certainty"):
            if f.get(key):
                detail.append(f"{key}: {f[key]}")
        if f.get("morphology"):
            detail.append("/".join(f["morphology"]))
        if detail:
            print(f"      {' | '.join(detail)}")

    print(f"\nIMPRESSION\n{'-' * 72}\n  {case['impression']}")

    if case.get("differential"):
        print(f"\nDIFFERENTIAL\n{'-' * 72}")
        for d in case["differential"]:
            print(f"  {d['entity']}"
                  f"{' (' + d['likelihood'] + ')' if d.get('likelihood') else ''}")
            for s in d.get("supporting", []):
                print(f"      + {s}")
            for a in d.get("against", []):
                print(f"      - {a}")

    print(f"\nCONFIDENCE: {case['confidence']}")
    for lim in case.get("limitations", []):
        print(f"  ! {lim}")
    if case.get("compare_to"):
        print(f"\nCompared against: {', '.join(case['compare_to'])}")
    print()
    return 0


def looks_like_one_study(prior: dict, current: dict) -> bool:
    """True when two records appear to describe a single acquisition.

    Same pseudonym on the same study date means these are almost certainly two
    reads of one scan. Interval change across them is meaningless — findings
    differ by which level each frame cuts through, not by anything biological.
    """
    p_patient = (prior.get("patient") or {}).get("id")
    c_patient = (current.get("patient") or {}).get("id")
    p_date = prior.get("study", {}).get("study_date")
    c_date = current.get("study", {}).get("study_date")
    return (p_patient is not None and p_patient == c_patient
            and p_date is not None and p_date == c_date)


def _frame_values(case: dict, key: str) -> set:
    return {f.get(key) for f in case.get("frames", []) if f.get(key)}


def comparison_warnings(prior: dict, current: dict) -> list[str]:
    """Everything that makes a comparison between these two records unsafe."""
    warnings: list[str] = []

    if looks_like_one_study(prior, current):
        warnings.append(
            "SAME PATIENT AND SAME STUDY DATE — these look like two reads of one "
            "acquisition, not two studies. Interval change is meaningless here; "
            "findings will differ purely by which level each frame cuts through. "
            "Frames of one acquisition belong in one case, under 'frames'."
        )

    p_patient = (prior.get("patient") or {}).get("id")
    c_patient = (current.get("patient") or {}).get("id")
    if p_patient != c_patient:
        warnings.append(f"different patient ids ({p_patient} vs {c_patient}) — this is a "
                        f"pattern comparison, not an interval-change study")
    if prior["study"].get("region") != current["study"].get("region"):
        warnings.append("different body regions")
    if prior["study"].get("contrast") != current["study"].get("contrast"):
        warnings.append("different contrast phases — size and enhancement are not directly comparable")

    p_planes, c_planes = _frame_values(prior, "plane"), _frame_values(current, "plane")
    if p_planes and c_planes and not (p_planes & c_planes):
        warnings.append(f"no shared imaging plane ({'/'.join(sorted(p_planes))} vs "
                        f"{'/'.join(sorted(c_planes))})")

    p_windows, c_windows = _frame_values(prior, "window"), _frame_values(current, "window")
    if p_windows and c_windows and not (p_windows & c_windows):
        warnings.append(f"no shared window ({'/'.join(sorted(p_windows))} vs "
                        f"{'/'.join(sorted(c_windows))}) — a finding invisible on one window "
                        f"is not a finding that resolved")

    return warnings


def cmd_compare(args: argparse.Namespace) -> int:
    prior = load_case(args.prior)
    current = load_case(args.current)

    print(f"\nCOMPARISON  {prior['case_id']} (prior) -> {current['case_id']} (current)")
    print("=" * 72)
    print(f"  prior:   {prior['study'].get('study_date') or 'date unknown'}  "
          f"{prior['study'].get('region')}  {prior['study'].get('contrast') or 'contrast unknown'}"
          f"  ({len(prior.get('frames', []))} frame(s))")
    print(f"  current: {current['study'].get('study_date') or 'date unknown'}  "
          f"{current['study'].get('region')}  {current['study'].get('contrast') or 'contrast unknown'}"
          f"  ({len(current.get('frames', []))} frame(s))")

    warnings = comparison_warnings(prior, current)
    for w in warnings:
        print(f"  ! {w}")

    matched, resolved, new_findings = match_findings(prior, current)

    print(f"\nMATCHED FINDINGS ({len(matched)})")
    print("-" * 72)
    if not matched:
        print("  none")
    for pf, cf in matched:
        label, delta, pct = classify_change(longest_axis(pf), longest_axis(cf))
        head = f"  [{cf['id']}] {cf['organ']}"
        if cf.get("location"):
            head += f" — {cf['location']}"
        print(head)
        p_size = longest_axis(pf)
        c_size = longest_axis(cf)
        if p_size is not None and c_size is not None:
            print(f"      size {p_size:g} -> {c_size:g} mm "
                  f"({delta:+.1f} mm, {pct:+.0f}%)  => {label.upper()}")
        else:
            print(f"      size not measurable on both studies  => {label.upper()}")
        p_hu = (pf.get("attenuation_hu") or {}).get("value")
        c_hu = (cf.get("attenuation_hu") or {}).get("value")
        if p_hu is not None and c_hu is not None:
            print(f"      density {p_hu:g} -> {c_hu:g} HU ({c_hu - p_hu:+g})")
        if pf.get("enhancement") != cf.get("enhancement"):
            print(f"      enhancement {pf.get('enhancement')} -> {cf.get('enhancement')}")
        if pf.get("margins") != cf.get("margins"):
            print(f"      margins {pf.get('margins')} -> {cf.get('margins')}")
        if pf["description"] != cf["description"]:
            print(f"      prior:   {pf['description']}")
            print(f"      current: {cf['description']}")

    print(f"\nNEW ON CURRENT STUDY ({len(new_findings)})")
    print("-" * 72)
    if not new_findings:
        print("  none")
    for f in new_findings:
        size = longest_axis(f)
        print(f"  [{f['id']}] {f['organ']}"
              f"{' — ' + f['location'] if f.get('location') else ''}"
              f"{f'  {size:g} mm' if size else ''}"
              f"{'  (' + f['significance'] + ')' if f.get('significance') else ''}")
        print(f"      {f['description']}")

    print(f"\nNO LONGER IDENTIFIED ({len(resolved)})")
    print("-" * 72)
    if not resolved:
        print("  none")
    for f in resolved:
        size = longest_axis(f)
        print(f"  [{f['id']}] {f['organ']}"
              f"{' — ' + f['location'] if f.get('location') else ''}"
              f"{f'  was {size:g} mm' if size else ''}")
    if resolved:
        print("\n  'No longer identified' is not the same as resolved. Check whether the")
        print("  current study's frames actually cut through the level and window where")
        print("  each of these was originally seen.")

    label, rationale = overall_change(matched, resolved, new_findings)
    print("\n" + "=" * 72)
    print(f"OVERALL: {label.replace('_', ' ').upper()}")
    print(f"  {rationale}")
    print(f"\n  Thresholds: grew if >= +{GROWTH_PCT:g}% and >= +{GROWTH_ABS_MM:g} mm; "
          f"shrank if <= -{SHRINK_PCT:g}%.")
    print("  Descriptive comparison of recorded findings only — not a formal RECIST")
    print("  assessment and not a clinical determination.")
    if warnings:
        print("\n  Read the caveats above before drawing anything from this.")
    print()
    return 0


def cmd_similar(args: argparse.Namespace) -> int:
    target = load_case(args.case_id)
    scored: list[tuple[float, dict, list[str]]] = []

    t_organs = {f["organ"].lower() for f in target.get("findings", [])}
    t_morph = {m.lower() for f in target.get("findings", []) for m in f.get("morphology", [])}
    t_tags = {t.lower() for t in target.get("tags", [])}
    t_patient = (target.get("patient") or {}).get("id")

    for case in load_all():
        if case["case_id"] == target["case_id"]:
            continue
        score = 0.0
        why: list[str] = []

        if case["study"].get("region") == target["study"].get("region"):
            score += 2.0
            why.append(f"same region ({case['study']['region']})")

        c_patient = (case.get("patient") or {}).get("id")
        if t_patient and c_patient == t_patient:
            score += 5.0
            why.append("same patient — candidate prior study")

        organs = {f["organ"].lower() for f in case.get("findings", [])} & t_organs
        if organs:
            score += 1.5 * len(organs)
            why.append("shared organ(s): " + ", ".join(sorted(organs)))

        morph = {m.lower() for f in case.get("findings", []) for m in f.get("morphology", [])} & t_morph
        if morph:
            score += 1.0 * len(morph)
            why.append("shared morphology: " + ", ".join(sorted(morph)))

        tags = {t.lower() for t in case.get("tags", [])} & t_tags
        if tags:
            score += 0.5 * len(tags)
            why.append("shared tags: " + ", ".join(sorted(tags)))

        if score > 0:
            scored.append((score, case, why))

    scored.sort(key=lambda row: -row[0])
    print(f"\nCases in the base resembling {target['case_id']}:\n")
    if not scored:
        print("  Nothing comparable yet — the base needs more cases.\n")
        return 0
    for score, case, why in scored[: args.limit]:
        print(f"  {case['case_id']}  (score {score:g})  {case['impression'][:50]}")
        for reason in why:
            print(f"      · {reason}")
    same_patient = [c for _, c, _ in scored if (c.get("patient") or {}).get("id") == t_patient and t_patient]
    if same_patient:
        print(f"\n  Prior study available — run: "
              f"python3 tools/ctdeck.py compare {same_patient[0]['case_id']} {target['case_id']}")
    print()
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    schema = load_schema()
    paths = case_paths()
    if not paths:
        print("No cases to validate.")
        return 0

    failed = 0
    seen_ids: dict[str, Path] = {}
    for path in paths:
        try:
            case = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"FAIL {path.name}: invalid JSON — {exc}")
            failed += 1
            continue

        errors = validate_against(case, schema, schema)

        if case.get("case_id") != path.stem:
            errors.append(f"case_id {case.get('case_id')!r} does not match filename {path.stem!r}")
        if case.get("case_id") in seen_ids:
            errors.append(f"duplicate case_id, also in {seen_ids[case['case_id']].name}")
        seen_ids[case.get("case_id", path.stem)] = path

        frame_ids = [fr.get("id") for fr in case.get("frames", [])]
        for dup in {i for i in frame_ids if frame_ids.count(i) > 1}:
            errors.append(f"duplicate frame id {dup!r}")
        for fr in case.get("frames", []):
            img = fr.get("image")
            if img and not (ROOT / img).exists():
                errors.append(f"frame {fr.get('id')!r}: image not found: {img}")

        ids = [f.get("id") for f in case.get("findings", [])]
        for dup in {i for i in ids if ids.count(i) > 1}:
            errors.append(f"duplicate finding id {dup!r}")
        for f in case.get("findings", []):
            for ref in f.get("seen_on", []):
                if ref not in frame_ids:
                    errors.append(f"finding {f.get('id')!r}: seen_on references "
                                  f"unknown frame {ref!r}")

        for ref in case.get("compare_to", []):
            if not (CASES_DIR / f"{ref}.json").exists():
                errors.append(f"compare_to references missing case {ref}")

        if errors:
            failed += 1
            print(f"FAIL {path.name}")
            for e in errors:
                print(f"     {e}")
        elif args.verbose:
            print(f"ok   {path.name}")

    print(f"\n{len(paths) - failed}/{len(paths)} case(s) valid.")
    return 1 if failed else 0


def cmd_index(args: argparse.Namespace) -> int:
    cases = load_all()
    entries = []
    for case in cases:
        entries.append({
            "case_id": case["case_id"],
            "added": case.get("added"),
            "patient_id": (case.get("patient") or {}).get("id"),
            "study_date": case["study"].get("study_date"),
            "region": case["study"].get("region"),
            "contrast": case["study"].get("contrast"),
            "frames": [
                {
                    "id": fr["id"],
                    "image": fr.get("image"),
                    "plane": fr.get("plane"),
                    "window": fr.get("window"),
                    "slice_level": fr.get("slice_level"),
                }
                for fr in case.get("frames", [])
            ],
            "impression": case["impression"],
            "confidence": case["confidence"],
            "tags": case.get("tags", []),
            "findings": [
                {
                    "id": f["id"],
                    "organ": f["organ"],
                    "laterality": f.get("laterality"),
                    "location": f.get("location"),
                    "size_mm": f.get("size_mm"),
                    "significance": f.get("significance"),
                }
                for f in case.get("findings", [])
            ],
        })

    by_region: dict[str, list[str]] = {}
    by_organ: dict[str, list[str]] = {}
    by_patient: dict[str, list[str]] = {}
    for case in cases:
        by_region.setdefault(case["study"].get("region", "other"), []).append(case["case_id"])
        for f in case.get("findings", []):
            by_organ.setdefault(f["organ"].lower(), []).append(case["case_id"])
        pid = (case.get("patient") or {}).get("id")
        if pid:
            by_patient.setdefault(pid, []).append(case["case_id"])

    index = {
        "generated": dt.date.today().isoformat(),
        "case_count": len(cases),
        "cases": entries,
        "by_region": {k: sorted(set(v)) for k, v in sorted(by_region.items())},
        "by_organ": {k: sorted(set(v)) for k, v in sorted(by_organ.items())},
        "by_patient": {k: sorted(set(v)) for k, v in sorted(by_patient.items())},
    }
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    print(f"Indexed {len(cases)} case(s) -> {rel(INDEX_PATH)}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    case_id = args.case_id or next_case_id()
    if not CASE_RE.match(case_id):
        raise SystemExit(f"case_id must look like CASE-0001, got {case_id!r}")
    path = CASES_DIR / f"{case_id}.json"
    if path.exists():
        raise SystemExit(f"{rel(path)} already exists")

    template = json.loads((ROOT / "templates" / "case-template.json").read_text())
    template["case_id"] = case_id
    template["added"] = dt.date.today().isoformat()
    if args.region:
        template["study"]["region"] = args.region
    if args.patient:
        template.setdefault("patient", {})["id"] = args.patient
    if args.image:
        template["frames"] = [{
            "id": "frame-1",
            "image": args.image,
            "plane": "axial",
            "window": None,
            "slice_level": None,
            "notes": None,
        }]

    CASES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n")
    print(f"Created {rel(path)} — fill in findings and impression, then run:")
    print(f"  python3 tools/ctdeck.py validate && python3 tools/ctdeck.py index")
    return 0


# --------------------------------------------------------------------------
# HTML deck
# --------------------------------------------------------------------------

DECK_CSS = """
:root { color-scheme: light dark;
  --bg:#fbfbfa; --panel:#fff; --ink:#1d1c1a; --muted:#6b6963; --line:#e4e2dd;
  --accent:#3d5a80; --warn:#8c4a2f; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#16171a; --panel:#1e2024; --ink:#e8e6e1; --muted:#9a978f; --line:#2f3238;
  --accent:#8fb0d4; --warn:#d99b7a; } }
* { box-sizing:border-box; }
body { margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--ink);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.wrap { max-width:920px; margin:0 auto; }
h1 { font-size:1.6rem; margin:0 0 .25rem; letter-spacing:-.01em; }
.sub { color:var(--muted); margin:0 0 2rem; font-size:.9rem; }
.disclaimer { border-left:3px solid var(--warn); padding:.6rem .9rem; margin:0 0 2rem;
  background:color-mix(in srgb, var(--warn) 7%, transparent); font-size:.86rem; color:var(--muted); }
.case { background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:1.25rem 1.4rem; margin-bottom:1.25rem; }
.case h2 { font-size:1.05rem; margin:0 0 .2rem; }
.meta { color:var(--muted); font-size:.82rem; margin-bottom:.9rem; }
.impression { margin:0 0 1rem; }
table { width:100%; border-collapse:collapse; font-size:.85rem; }
.scroll { overflow-x:auto; }
th { text-align:left; font-weight:600; color:var(--muted); font-size:.72rem;
  text-transform:uppercase; letter-spacing:.05em; border-bottom:1px solid var(--line); padding:.35rem .5rem; }
td { padding:.45rem .5rem; border-bottom:1px solid var(--line); vertical-align:top; }
tr:last-child td { border-bottom:none; }
.pill { display:inline-block; font-size:.7rem; padding:.1rem .45rem; border-radius:99px;
  border:1px solid var(--line); color:var(--muted); margin-right:.3rem; }
.pill.critical { color:var(--warn); border-color:var(--warn); }
.limits { font-size:.8rem; color:var(--muted); margin-top:.9rem; }
img { max-width:100%; border-radius:6px; border:1px solid var(--line); display:block; }
.frames { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:.75rem; margin-bottom:1rem; }
figure { margin:0; }
figcaption { font-size:.72rem; color:var(--muted); margin-top:.3rem; }
.empty { color:var(--muted); font-style:italic; }
"""


def _deck_img_src(image: str, out: str) -> str:
    """Path to an image from the rendered deck's own location."""
    try:
        return str((ROOT / image).resolve().relative_to(Path(out).resolve().parent))
    except ValueError:
        return str((ROOT / image).resolve())


def cmd_deck(args: argparse.Namespace) -> int:
    cases = load_all()
    e = html.escape
    parts = [
        "<div class='wrap'>",
        "<h1>CT Scan Information Deck</h1>",
        f"<p class='sub'>{len(cases)} case(s) &middot; generated {dt.date.today().isoformat()}</p>",
        "<p class='disclaimer'>Descriptive image notes for reference and study. Built from "
        "screenshots without DICOM metadata or full-volume review. Not a diagnosis and not a "
        "basis for any clinical decision.</p>",
    ]

    if not cases:
        parts.append("<p class='empty'>The base is empty. Add a case to get started.</p>")

    for case in cases:
        study = case["study"]
        patient = case.get("patient") or {}
        meta = [study.get("region", "?")]
        for key in ("study_date", "contrast"):
            if study.get(key):
                meta.append(str(study[key]))
        frame_count = len(case.get("frames", []))
        if frame_count:
            meta.append(f"{frame_count} frame(s)")
        if patient.get("id"):
            meta.insert(0, f"patient {patient['id']}")

        parts.append("<div class='case'>")
        parts.append(f"<h2>{e(case['case_id'])}</h2>")
        parts.append(f"<div class='meta'>{e(' · '.join(meta))}</div>")

        frames = case.get("frames", [])
        shown = [fr for fr in frames if fr.get("image") and (ROOT / fr["image"]).exists()]
        if shown:
            parts.append("<div class='frames'>")
            for fr in shown:
                src = _deck_img_src(fr["image"], args.out)
                caption = " · ".join(str(fr[k]) for k in ("plane", "window", "slice_level")
                                     if fr.get(k))
                parts.append(
                    f"<figure><img src='{e(src)}' alt='{e(case['case_id'])} frame "
                    f"{e(fr['id'])}'><figcaption>{e(fr['id'])}"
                    f"{' — ' + e(caption) if caption else ''}</figcaption></figure>"
                )
            parts.append("</div>")
        elif frames:
            levels = "; ".join(str(fr.get("slice_level") or fr["id"]) for fr in frames)
            parts.append(f"<p class='empty'>{len(frames)} frame(s) described, pixels not "
                         f"attached — {e(levels)}</p>")

        parts.append(f"<p class='impression'>{e(case['impression'])}</p>")

        findings = case.get("findings", [])
        if findings:
            parts.append("<div class='scroll'><table><thead><tr>"
                         "<th>Finding</th><th>Site</th><th>Description</th>"
                         "<th>Size</th><th>Density</th></tr></thead><tbody>")
            for f in findings:
                site = " ".join(x for x in [f.get("laterality") if f.get("laterality") not in (None, "n/a") else None,
                                            f.get("organ"), f.get("location")] if x)
                size = " &times; ".join(f"{s:g}" for s in f["size_mm"]) + " mm" if f.get("size_mm") else "—"
                hu = f.get("attenuation_hu") or {}
                if hu.get("value") is not None:
                    density = f"{hu['value']:g} HU"
                elif hu.get("qualitative"):
                    density = hu["qualitative"].replace("_", " ")
                else:
                    density = "—"
                sig = f.get("significance")
                pill = (f"<span class='pill {e(sig)}'>{e(sig)}</span>" if sig else "")
                parts.append(
                    f"<tr><td>{pill}{e(f['id'])}</td><td>{e(site)}</td>"
                    f"<td>{e(f['description'])}</td><td>{size}</td><td>{e(density)}</td></tr>"
                )
            parts.append("</tbody></table></div>")
        else:
            parts.append("<p class='empty'>No discrete findings recorded.</p>")

        limits = case.get("limitations", [])
        conf = f"Confidence: {case['confidence']}"
        if limits:
            conf += " &middot; " + "; ".join(e(l) for l in limits)
        parts.append(f"<div class='limits'>{conf}</div>")
        parts.append("</div>")

    parts.append("</div>")

    doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>CT Scan Information Deck</title>"
        f"<style>{DECK_CSS}</style></head><body>{''.join(parts)}</body></html>"
    )
    out = Path(args.out)
    out.write_text(doc)
    print(f"Wrote {out} ({len(cases)} case(s))")
    return 0


# --------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ctdeck", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list cases in the base")
    p.add_argument("--region")
    p.add_argument("--patient")
    p.add_argument("--tag")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="print one case in full")
    p.add_argument("case_id")
    p.add_argument("--json", action="store_true", help="dump the raw record")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("compare", help="compare a prior study against a current one")
    p.add_argument("prior")
    p.add_argument("current")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("similar", help="find cases in the base resembling this one")
    p.add_argument("case_id")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=cmd_similar)

    p = sub.add_parser("validate", help="check every case against the schema")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("index", help="rebuild cases/index.json")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("new", help="scaffold a blank case record")
    p.add_argument("--case-id")
    p.add_argument("--region")
    p.add_argument("--patient")
    p.add_argument("--image")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("deck", help="render the base as a browsable HTML page")
    p.add_argument("--out", default="deck.html")
    p.set_defaults(func=cmd_deck)

    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # Downstream closed the pipe (`| head`). Silence the interpreter's
        # shutdown warning by pointing stdout at devnull before exiting.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)
