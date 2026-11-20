"""Reconciliation against the real assignment CSVs: every finding, and every
deliberate non-error, pinned down so a change in the rules shows up here."""
from django.conf import settings
from django.test import SimpleTestCase

from recon.reconcile import normalize_ref, parse_amount, reconcile

EXPECTED = {
    # (org, reason, record_id, entry_ids)
    ("ORG-A", "MISSING_IN_SYSTEM_B", "REC-1015", ()),
    ("ORG-A", "ADJUSTMENT_MISSING_IN_SYSTEM_B", "REC-1027", ("ENT/2026/4027",)),
    ("ORG-A", "DUPLICATE_IN_SYSTEM_B", "REC-1042", ("ENT/2026/4042", "ENT/2026/4902")),
    ("ORG-A", "AMOUNT_MISMATCH", "REC-1064", ("ENT/2026/4064",)),
    ("ORG-A", "FILED_UNDER_OTHER_ORGANISATION", "REC-1077", ()),
    ("ORG-A", "ADJUSTMENT_MISSING_IN_SYSTEM_B", "REC-1088", ("ENT/2026/4088",)),
    ("ORG-A", "MISSING_IN_SYSTEM_A", "REC-1999", ("ENT/2026/4901",)),
    ("ORG-B", "FILED_UNDER_OTHER_ORGANISATION", "", ("ENT/2026/4077",)),
    ("ORG-B", "ADJUSTMENT_MISSING_IN_SYSTEM_B", "REC-1003", ("ENT/2026/4003",)),
    ("ORG-B", "DATE_MISMATCH", "REC-1009", ("ENT/2026/4009",)),
    ("ORG-B", "CANCELLED_IN_A_ACTIVE_IN_B", "REC-1019", ("ENT/2026/4019",)),
    ("ORG-B", "AMOUNT_MISSING_IN_SYSTEM_B", "REC-1050", ("ENT/2026/4050",)),
    ("ORG-B", "MISSING_IN_SYSTEM_B", "REC-1061", ()),
}


class ReconcileDataset(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result = reconcile(settings.DATA_DIR)
        cls.by_record = {}
        for f in cls.result.findings:
            cls.by_record.setdefault(f.record_id, []).append(f)

    def test_exact_set_of_exceptions(self):
        got = {(f.org_id, f.reason_code, f.record_id, tuple(f.entry_ids)) for f in self.result.findings}
        self.assertEqual(got, EXPECTED)
        self.assertEqual(len(self.result.findings), len(EXPECTED))  # no duplicates
        self.assertEqual(self.result.unassignable, [])

    def test_messy_references_are_matched_not_reported(self):
        for rid in ("REC-1034", "REC-1070", "REC-1112"):
            self.assertNotIn(rid, self.by_record)

    def test_split_entry_that_adds_up_is_not_reported(self):
        self.assertNotIn("REC-1055", self.by_record)

    def test_lakh_formatted_amount_is_parsed_before_comparing(self):
        (f,) = self.by_record["REC-1064"]
        self.assertEqual(str(f.system_b_amount), "125400.00")

    def test_cross_org_finding_does_not_expose_the_other_side(self):
        a_side = next(f for f in self.result.findings if f.org_id == "ORG-A" and f.record_id == "REC-1077")
        b_side = next(f for f in self.result.findings if f.org_id == "ORG-B" and f.reason_code == "FILED_UNDER_OTHER_ORGANISATION")
        self.assertEqual(a_side.entry_ids, [])
        self.assertNotIn("LOC-201", a_side.detail)
        self.assertNotIn("ENT/", a_side.detail)
        self.assertEqual(b_side.record_id, "")
        self.assertNotIn("REC-1077", b_side.detail)
        self.assertNotIn("LOC-102", b_side.detail)

    def test_118_records_matched(self):
        self.assertEqual(self.result.matched_records, 118)


class Parsing(SimpleTestCase):
    def test_normalize_ref(self):
        self.assertEqual(normalize_ref("rec1034"), "REC-1034")
        self.assertEqual(normalize_ref(" REC - 1070 "), "REC-1070")
        self.assertEqual(normalize_ref("1112"), "REC-1112")
        self.assertIsNone(normalize_ref(""))
        self.assertIsNone(normalize_ref("REC-1-2"))  # ambiguous: refuse, don't guess

    def test_parse_amount(self):
        self.assertEqual(str(parse_amount("1,25,400.00")), "125400.00")
        self.assertEqual(str(parse_amount("125,400.00")), "125400.00")
        self.assertIsNone(parse_amount(""))
        self.assertIsNone(parse_amount("n/a"))
