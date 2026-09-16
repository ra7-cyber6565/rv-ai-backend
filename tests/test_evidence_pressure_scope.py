"""Pure-stdlib condition accounting; these are software, not laboratory tests."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.evidence_scope import ambient_pressure_requested, pressure_scope


QUESTION = "Is room-temperature superconductivity proven at normal atmospheric pressure?"


class PressureScopeTests(unittest.TestCase):
    def test_standard_atmosphere_has_exact_equivalent_units(self):
        for expression in ("1 atm", "101325 Pa", "101.325 kPa", ".101325 MPa"):
            with self.subTest(expression=expression):
                scope = pressure_scope(QUESTION, "Measurements at " + expression)
                self.assertEqual(scope["state"], "MATCHING_PRESSURE_ONLY")
                self.assertEqual(Decimal(scope["reported_pressures"][0]["pascals"]), Decimal(101325))
                self.assertEqual(scope["scientific_confirmation"], "NOT_ASSESSED")

    def test_high_pressure_units_are_not_atmospheric_proof(self):
        for expression in ("1 GPa", "1000 MPa", "10 kbar", "1e9 Pa"):
            with self.subTest(expression=expression):
                scope = pressure_scope(QUESTION, "Reported transition at " + expression)
                self.assertEqual(scope["state"], "DIFFERENT_PRESSURE")
                self.assertEqual(Decimal(scope["reported_pressures"][0]["pascals"]), Decimal(10**9))

    def test_no_experimental_tolerance_is_invented(self):
        scope = pressure_scope(QUESTION, "Measured at 0.1 MPa")
        self.assertEqual(scope["reported_pressures"][0]["pascals"], "100000.0")
        self.assertFalse(scope["reported_pressures"][0]["standard_atmosphere"])
        self.assertEqual(scope["scientific_confirmation"], "NOT_ASSESSED")

    def test_mixed_material_or_pressure_results_need_review(self):
        scope = pressure_scope(QUESTION, "One sample at ambient pressure; another at 1 GPa.")
        self.assertEqual(scope["state"], "MIXED_CONDITIONS")

    def test_near_ambient_and_missing_pressure_are_not_promoted(self):
        for text in ("near-ambient pressure", "near ambient pressure", "room temperature signatures in ceramics"):
            with self.subTest(text=text):
                self.assertEqual(pressure_scope(QUESTION, text)["state"], "PRESSURE_UNSPECIFIED")

    def test_unrelated_questions_do_not_activate_pressure_gate(self):
        for question in ("How do I build a Python app?", "What is standard pressure?", "Compare high-pressure hydrides"):
            with self.subTest(question=question):
                self.assertFalse(ambient_pressure_requested(question))
                self.assertFalse(pressure_scope(question, "1 GPa")["required"])

    def test_case_units_malformed_numbers_and_extreme_exponents_stay_unknown(self):
        for text in ("1 mPa", "1 gpa", "-1 GPa", "1,000 GPa", "1e999999999 Pa"):
            with self.subTest(text=text):
                scope = pressure_scope(QUESTION, text)
                self.assertEqual(scope["state"], "PRESSURE_UNSPECIFIED")
                self.assertEqual(scope["reported_pressures"], [])

    def test_explicit_ambient_is_only_a_condition_mention(self):
        scope = pressure_scope(QUESTION, "Ambient pressure measurements were inconclusive.")
        self.assertEqual(scope["state"], "MATCHING_PRESSURE_ONLY")
        self.assertEqual(scope["scientific_confirmation"], "NOT_ASSESSED")


if __name__ == "__main__":
    unittest.main()
