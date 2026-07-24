#!/usr/bin/env python3
"""Tests for ctdeck. Run: python3 -m unittest discover -s tools -t tools"""

import json
import unittest
from pathlib import Path

import ctdeck

ROOT = Path(__file__).resolve().parent.parent


def finding(fid, organ, size=None, **kw):
    f = {"id": fid, "organ": organ, "description": "described"}
    if size:
        f["size_mm"] = size
    f.update(kw)
    return f


def compare(prior_findings, current_findings):
    matched, resolved, new = ctdeck.match_findings(
        {"findings": prior_findings}, {"findings": current_findings}
    )
    return ctdeck.overall_change(matched, resolved, new)


class TestLesionChange(unittest.TestCase):
    def test_growth_needs_both_percent_and_absolute(self):
        self.assertEqual(ctdeck.classify_change(20, 30)[0], "larger")
        # +50% but only +2 mm — below the absolute floor, so noise.
        self.assertEqual(ctdeck.classify_change(4, 6)[0], "stable")
        # +12 mm but only +12% — below the relative floor.
        self.assertEqual(ctdeck.classify_change(100, 112)[0], "stable")

    def test_shrinkage(self):
        self.assertEqual(ctdeck.classify_change(20, 10)[0], "smaller")
        self.assertEqual(ctdeck.classify_change(20, 16)[0], "stable")

    def test_unmeasured(self):
        self.assertEqual(ctdeck.classify_change(None, 10)[0], "not_measurable")
        self.assertEqual(ctdeck.classify_change(10, None)[0], "not_measurable")

    def test_delta_and_percent(self):
        label, delta, pct = ctdeck.classify_change(20, 25)
        self.assertEqual(delta, 5)
        self.assertEqual(pct, 25.0)
        self.assertEqual(label, "larger")


class TestMatching(unittest.TestCase):
    def test_matches_on_id(self):
        matched, resolved, new = ctdeck.match_findings(
            {"findings": [finding("liver-lesion", "liver", [20])]},
            {"findings": [finding("liver-lesion", "liver", [30])]},
        )
        self.assertEqual(len(matched), 1)
        self.assertFalse(resolved)
        self.assertFalse(new)

    def test_falls_back_to_anatomic_key(self):
        matched, resolved, new = ctdeck.match_findings(
            {"findings": [finding("a", "liver", [20], laterality="right", location="segment VII")]},
            {"findings": [finding("b", "liver", [30], laterality="right", location="segment VII")]},
        )
        self.assertEqual(len(matched), 1, "same site with a different slug should still pair")
        self.assertFalse(new)

    def test_different_sites_do_not_pair(self):
        matched, resolved, new = ctdeck.match_findings(
            {"findings": [finding("a", "liver", [20], location="segment VII")]},
            {"findings": [finding("b", "kidney", [30], location="upper pole")]},
        )
        self.assertEqual(matched, [])
        self.assertEqual(len(resolved), 1)
        self.assertEqual(len(new), 1)

    def test_one_prior_does_not_consume_two_current(self):
        matched, _, new = ctdeck.match_findings(
            {"findings": [finding("a", "liver", [20])]},
            {"findings": [finding("a", "liver", [30]), finding("c", "liver", [8])]},
        )
        self.assertEqual(len(matched), 1)
        self.assertEqual(len(new), 1)


class TestOverallChange(unittest.TestCase):
    def test_new_finding_is_progression(self):
        label, _ = compare([finding("a", "liver", [20])],
                           [finding("a", "liver", [20]), finding("b", "lung", [8])])
        self.assertEqual(label, "progression")

    def test_summed_growth(self):
        self.assertEqual(compare([finding("a", "liver", [20])],
                                 [finding("a", "liver", [30])])[0], "progression")

    def test_summed_shrinkage(self):
        self.assertEqual(compare([finding("a", "liver", [20])],
                                 [finding("a", "liver", [10])])[0], "partial_response")

    def test_stable(self):
        self.assertEqual(compare([finding("a", "liver", [20])],
                                 [finding("a", "liver", [22])])[0], "stable")

    def test_all_findings_gone(self):
        self.assertEqual(compare([finding("a", "liver", [20])], [])[0], "resolved")

    def test_some_gone_rest_stable_is_mixed(self):
        label, _ = compare([finding("a", "liver", [20]), finding("b", "lung", [9])],
                           [finding("a", "liver", [21])])
        self.assertEqual(label, "mixed")

    def test_no_measurements_is_indeterminate(self):
        self.assertEqual(compare([finding("a", "liver")], [finding("a", "liver")])[0],
                         "indeterminate")

    def test_empty_studies(self):
        self.assertEqual(compare([], [])[0], "indeterminate")

    def test_unmeasurable_lesions_excluded_from_sld(self):
        # The unmeasured lesion must not drag the summed diameters around.
        label, rationale = compare(
            [finding("a", "liver", [20]), finding("b", "spleen")],
            [finding("a", "liver", [21]), finding("b", "spleen")],
        )
        self.assertEqual(label, "stable")
        self.assertIn("+5%", rationale)


class TestComparisonWarnings(unittest.TestCase):
    def case(self, patient="PT-A", date="2026-01-01", region="chest",
             contrast="non_contrast", frames=None):
        return {
            "patient": {"id": patient},
            "study": {"region": region, "study_date": date, "contrast": contrast},
            "frames": frames if frames is not None else [{"id": "f", "plane": "axial",
                                                          "window": "soft_tissue"}],
        }

    def test_same_patient_same_date_is_flagged_as_one_study(self):
        a, b = self.case(), self.case()
        self.assertTrue(ctdeck.looks_like_one_study(a, b))
        self.assertTrue(any("SAME PATIENT AND SAME STUDY DATE" in w
                            for w in ctdeck.comparison_warnings(a, b)))

    def test_different_dates_are_a_real_interval_comparison(self):
        a, b = self.case(date="2026-01-01"), self.case(date="2026-07-01")
        self.assertFalse(ctdeck.looks_like_one_study(a, b))
        self.assertEqual(ctdeck.comparison_warnings(a, b), [])

    def test_unknown_dates_do_not_trigger_same_study(self):
        # Two undated records could be anything; don't assert they are one scan.
        a, b = self.case(date=None), self.case(date=None)
        self.assertFalse(ctdeck.looks_like_one_study(a, b))

    def test_unknown_patients_do_not_trigger_same_study(self):
        a, b = self.case(patient=None), self.case(patient=None)
        self.assertFalse(ctdeck.looks_like_one_study(a, b))

    def test_different_patient_warns(self):
        warnings = ctdeck.comparison_warnings(self.case(patient="PT-A"),
                                              self.case(patient="PT-B", date="2026-07-01"))
        self.assertTrue(any("different patient ids" in w for w in warnings))

    def test_contrast_phase_mismatch_warns(self):
        warnings = ctdeck.comparison_warnings(
            self.case(contrast="non_contrast"),
            self.case(contrast="portal_venous", date="2026-07-01"))
        self.assertTrue(any("contrast phases" in w for w in warnings))

    def test_window_mismatch_warns(self):
        warnings = ctdeck.comparison_warnings(
            self.case(frames=[{"id": "a", "plane": "axial", "window": "soft_tissue"}]),
            self.case(date="2026-07-01",
                      frames=[{"id": "b", "plane": "axial", "window": "lung"}]))
        self.assertTrue(any("no shared window" in w for w in warnings))

    def test_overlapping_windows_do_not_warn(self):
        warnings = ctdeck.comparison_warnings(
            self.case(frames=[{"id": "a", "window": "soft_tissue"},
                              {"id": "b", "window": "lung"}]),
            self.case(date="2026-07-01", frames=[{"id": "c", "window": "lung"}]))
        self.assertFalse(any("no shared window" in w for w in warnings))

    def test_plane_mismatch_warns(self):
        warnings = ctdeck.comparison_warnings(
            self.case(frames=[{"id": "a", "plane": "axial"}]),
            self.case(date="2026-07-01", frames=[{"id": "b", "plane": "coronal"}]))
        self.assertTrue(any("no shared imaging plane" in w for w in warnings))

    def test_missing_frame_metadata_does_not_warn(self):
        warnings = ctdeck.comparison_warnings(
            self.case(frames=[]), self.case(date="2026-07-01", frames=[]))
        self.assertEqual(warnings, [])


class TestSchemaValidator(unittest.TestCase):
    def setUp(self):
        self.schema = ctdeck.load_schema()

    def _minimal(self):
        return {
            "case_id": "CASE-0001",
            "added": "2026-01-01",
            "study": {"region": "chest"},
            "findings": [],
            "impression": "Unremarkable.",
            "confidence": "low",
        }

    def test_minimal_record_passes(self):
        self.assertEqual(ctdeck.validate_against(self._minimal(), self.schema, self.schema), [])

    def test_missing_required_field(self):
        case = self._minimal()
        del case["impression"]
        errors = ctdeck.validate_against(case, self.schema, self.schema)
        self.assertTrue(any("impression" in e for e in errors))

    def test_bad_case_id_pattern(self):
        case = self._minimal()
        case["case_id"] = "CASE-1"
        self.assertTrue(ctdeck.validate_against(case, self.schema, self.schema))

    def test_bad_enum_value(self):
        case = self._minimal()
        case["study"]["region"] = "elbow"
        errors = ctdeck.validate_against(case, self.schema, self.schema)
        self.assertTrue(any("region" in e for e in errors))

    def test_unexpected_field_rejected(self):
        case = self._minimal()
        case["hallucinated"] = True
        errors = ctdeck.validate_against(case, self.schema, self.schema)
        self.assertTrue(any("hallucinated" in e for e in errors))

    def test_bad_date_format(self):
        case = self._minimal()
        case["added"] = "01/01/2026"
        self.assertTrue(ctdeck.validate_against(case, self.schema, self.schema))

    def test_finding_ref_is_resolved(self):
        case = self._minimal()
        case["findings"] = [{"id": "x", "organ": "liver"}]  # missing description
        errors = ctdeck.validate_against(case, self.schema, self.schema)
        self.assertTrue(any("description" in e for e in errors))

    def test_size_must_be_positive(self):
        case = self._minimal()
        case["findings"] = [{"id": "x", "organ": "liver", "description": "d", "size_mm": [0]}]
        self.assertTrue(ctdeck.validate_against(case, self.schema, self.schema))

    def test_frames_accepted(self):
        case = self._minimal()
        case["frames"] = [{"id": "carina", "image": None, "plane": "axial",
                           "window": "soft_tissue", "slice_level": "carina", "notes": None}]
        self.assertEqual(ctdeck.validate_against(case, self.schema, self.schema), [])

    def test_frame_requires_id(self):
        case = self._minimal()
        case["frames"] = [{"plane": "axial"}]
        errors = ctdeck.validate_against(case, self.schema, self.schema)
        self.assertTrue(any("id" in e for e in errors))

    def test_frame_rejects_bad_window(self):
        case = self._minimal()
        case["frames"] = [{"id": "f", "window": "ultrasound"}]
        self.assertTrue(ctdeck.validate_against(case, self.schema, self.schema))

    def test_plane_and_window_no_longer_live_on_study(self):
        case = self._minimal()
        case["study"]["plane"] = "axial"
        errors = ctdeck.validate_against(case, self.schema, self.schema)
        self.assertTrue(any("plane" in e for e in errors),
                        "plane belongs to a frame, not the study")

    def test_size_capped_at_three_axes(self):
        case = self._minimal()
        case["findings"] = [{"id": "x", "organ": "liver", "description": "d",
                             "size_mm": [1, 2, 3, 4]}]
        self.assertTrue(ctdeck.validate_against(case, self.schema, self.schema))


class TestOfficialReport(unittest.TestCase):
    def setUp(self):
        self.schema = ctdeck.load_schema()

    def _case(self):
        return {
            "case_id": "CASE-0001", "added": "2026-01-01",
            "study": {"region": "chest"}, "findings": [],
            "impression": "x", "confidence": "high",
        }

    def test_official_report_accepted(self):
        case = self._case()
        case["official_report"] = {"text": "Findings.", "provided_by": "user",
                                   "date": None, "read_delta": "missed the nodules"}
        self.assertEqual(ctdeck.validate_against(case, self.schema, self.schema), [])

    def test_official_report_requires_text(self):
        case = self._case()
        case["official_report"] = {"provided_by": "user"}
        errors = ctdeck.validate_against(case, self.schema, self.schema)
        self.assertTrue(any("text" in e for e in errors))

    def test_concordance_enum_enforced(self):
        case = self._case()
        case["findings"] = [{"id": "n", "organ": "lung", "description": "d",
                             "concordance": "sort-of-right"}]
        self.assertTrue(ctdeck.validate_against(case, self.schema, self.schema))

    def test_concordance_and_source_accepted(self):
        case = self._case()
        case["findings"] = [{"id": "n", "organ": "lung", "description": "d",
                             "source": "official_report", "concordance": "missed"}]
        self.assertEqual(ctdeck.validate_against(case, self.schema, self.schema), [])

    def test_annotations_accepted(self):
        case = self._case()
        case["frames"] = [{"id": "f", "annotations": [
            {"id": "n1", "label": "nodule", "x": 0.7, "y": 0.4, "r": 0.04,
             "kind": "candidate", "note": "maybe"}]}]
        self.assertEqual(ctdeck.validate_against(case, self.schema, self.schema), [])

    def test_annotation_coordinates_must_be_fractional(self):
        case = self._case()
        case["frames"] = [{"id": "f", "annotations": [
            {"id": "n1", "label": "nodule", "x": 350, "y": 0.4}]}]
        self.assertTrue(ctdeck.validate_against(case, self.schema, self.schema),
                        "pixel coordinates should be rejected; x/y are fractions")

    def test_annotation_kind_enum_enforced(self):
        case = self._case()
        case["frames"] = [{"id": "f", "annotations": [
            {"id": "n1", "label": "n", "x": 0.5, "y": 0.5, "kind": "probably"}]}]
        self.assertTrue(ctdeck.validate_against(case, self.schema, self.schema))

    def test_read_after_report_flag_accepted(self):
        case = self._case()
        case["frames"] = [{"id": "lw", "window": "lung", "read_after_report": True}]
        self.assertEqual(ctdeck.validate_against(case, self.schema, self.schema), [])

    def test_report_sourced_finding_may_have_empty_seen_on(self):
        # A finding from the report can describe a slice no frame shows.
        case = self._case()
        case["frames"] = [{"id": "f"}]
        case["findings"] = [{"id": "n", "organ": "lung", "description": "d",
                             "source": "official_report", "seen_on": []}]
        self.assertEqual(ctdeck.validate_against(case, self.schema, self.schema), [])


class TestTemplateAndExamples(unittest.TestCase):
    def test_template_is_valid_json(self):
        json.loads((ROOT / "templates" / "case-template.json").read_text())

    def test_examples_conform_to_schema(self):
        schema = ctdeck.load_schema()
        for path in sorted((ROOT / "examples").glob("CASE-*.json")):
            with self.subTest(case=path.name):
                case = json.loads(path.read_text())
                self.assertEqual(ctdeck.validate_against(case, schema, schema), [])
                self.assertEqual(case["case_id"], path.stem)

    def test_real_cases_conform_to_schema(self):
        schema = ctdeck.load_schema()
        for path in sorted((ROOT / "cases").glob("CASE-*.json")):
            with self.subTest(case=path.name):
                case = json.loads(path.read_text())
                self.assertEqual(ctdeck.validate_against(case, schema, schema), [])

    def test_reported_cases_score_every_finding(self):
        # If a case has ground truth, every finding should say how the read fared.
        for path in sorted((ROOT / "cases").glob("CASE-*.json")):
            case = json.loads(path.read_text())
            if not case.get("official_report"):
                continue
            for f in case.get("findings", []):
                with self.subTest(case=path.name, finding=f["id"]):
                    self.assertIn(f.get("concordance"),
                                  ctdeck.CONCORDANCE_ORDER)

    def test_seen_on_only_references_declared_frames(self):
        for path in sorted((ROOT / "cases").glob("CASE-*.json")):
            case = json.loads(path.read_text())
            frame_ids = {fr["id"] for fr in case.get("frames", [])}
            for f in case.get("findings", []):
                with self.subTest(case=path.name, finding=f["id"]):
                    self.assertTrue(set(f.get("seen_on", [])) <= frame_ids)

    def test_example_pair_reports_progression(self):
        a = json.loads((ROOT / "examples" / "CASE-9001.json").read_text())
        b = json.loads((ROOT / "examples" / "CASE-9002.json").read_text())
        matched, resolved, new = ctdeck.match_findings(a, b)
        self.assertEqual(len(matched), 2)
        self.assertEqual(len(new), 1)
        self.assertEqual(ctdeck.overall_change(matched, resolved, new)[0], "progression")


if __name__ == "__main__":
    unittest.main()
