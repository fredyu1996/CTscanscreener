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

    def test_size_capped_at_three_axes(self):
        case = self._minimal()
        case["findings"] = [{"id": "x", "organ": "liver", "description": "d",
                             "size_mm": [1, 2, 3, 4]}]
        self.assertTrue(ctdeck.validate_against(case, self.schema, self.schema))


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

    def test_example_pair_reports_progression(self):
        a = json.loads((ROOT / "examples" / "CASE-9001.json").read_text())
        b = json.loads((ROOT / "examples" / "CASE-9002.json").read_text())
        matched, resolved, new = ctdeck.match_findings(a, b)
        self.assertEqual(len(matched), 2)
        self.assertEqual(len(new), 1)
        self.assertEqual(ctdeck.overall_change(matched, resolved, new)[0], "progression")


if __name__ == "__main__":
    unittest.main()
