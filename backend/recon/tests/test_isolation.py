"""Tenant isolation is enforced by PostgreSQL, not by our querysets.

Every query in this file deliberately has NO org filter (``.all()`` and raw
SQL): we bypass the application-level filter entirely and check that the
database alone refuses the other org's rows.

To see these tests fail, comment out the two lines marked "DEMO" in
recon/migrations/0002_row_level_security.py and re-run them (WALKTHROUGH.md).
"""
from django.db import connection
from django.db.utils import DatabaseError
from django.test import TestCase

from recon.db import tenant_context
from recon.models import Location, ReconException


def seed():
    for org, loc in (("ORG-A", "LOC-101"), ("ORG-B", "LOC-201")):
        with tenant_context(org):
            Location.objects.create(location_id=loc, org_id=org, name=loc)
            for i in range(3):
                ReconException.objects.create(
                    org_id=org, reason_code="AMOUNT_MISMATCH", record_id=f"REC-{org[-1]}{i}",
                    location_id=loc, detail="seed",
                )


class DatabaseEnforcesTenantIsolation(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed()

    def test_runs_as_restricted_role_not_superuser(self):
        """Guard: if the app ran as a superuser, RLS would be silently skipped."""
        with connection.cursor() as c:
            c.execute("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            user, is_super, bypass = c.fetchone()
        self.assertEqual(user, "dealeros_app")
        self.assertFalse(is_super)
        self.assertFalse(bypass)

    def test_unfiltered_orm_query_returns_only_own_org(self):
        with tenant_context("ORG-A"):
            orgs = set(ReconException.objects.all().values_list("org_id", flat=True))
            locs = set(Location.objects.all().values_list("org_id", flat=True))
        self.assertEqual(orgs, {"ORG-A"})
        self.assertEqual(locs, {"ORG-A"})

    def test_asking_for_other_org_explicitly_returns_nothing(self):
        with tenant_context("ORG-A"):
            self.assertEqual(ReconException.objects.filter(org_id="ORG-B").count(), 0)
            self.assertFalse(Location.objects.filter(location_id="LOC-201").exists())

    def test_raw_sql_returns_only_own_org(self):
        with tenant_context("ORG-B"):
            with connection.cursor() as c:
                c.execute("SELECT DISTINCT org_id FROM recon_exception")
                self.assertEqual([r[0] for r in c.fetchall()], ["ORG-B"])

    def test_no_tenant_set_means_no_rows(self):
        """A view that forgets tenant_context() sees nothing (fails closed)."""
        self.assertEqual(ReconException.objects.count(), 0)
        self.assertEqual(Location.objects.count(), 0)

    def test_tenant_does_not_leak_out_of_its_block(self):
        with tenant_context("ORG-A"):
            with tenant_context("ORG-B"):
                self.assertEqual(set(ReconException.objects.values_list("org_id", flat=True)), {"ORG-B"})
            self.assertEqual(set(ReconException.objects.values_list("org_id", flat=True)), {"ORG-A"})
        self.assertEqual(ReconException.objects.count(), 0)

    def test_cannot_write_a_row_into_another_org(self):
        with self.assertRaises(DatabaseError):
            with tenant_context("ORG-A"):
                ReconException.objects.create(
                    org_id="ORG-B", reason_code="AMOUNT_MISMATCH", location_id="LOC-201", detail="x"
                )

    def test_cannot_move_own_row_into_another_org(self):
        with self.assertRaises(DatabaseError):
            with tenant_context("ORG-A"):
                ReconException.objects.all().update(org_id="ORG-B")

    def test_cannot_update_or_delete_other_orgs_rows(self):
        with tenant_context("ORG-A"):
            self.assertEqual(ReconException.objects.filter(org_id="ORG-B").update(detail="hacked"), 0)
            self.assertEqual(ReconException.objects.filter(org_id="ORG-B").delete()[0], 0)
        with tenant_context("ORG-B"):
            self.assertEqual(ReconException.objects.count(), 3)
            self.assertFalse(ReconException.objects.filter(detail="hacked").exists())
