"""Load the CSVs, reconcile, and store each org's exceptions under that org.

Runs through the same restricted role as the web app: every write happens
inside tenant_context(org), so RLS's WITH CHECK also guards the loader.
Re-running replaces each org's rows (idempotent).
"""
import csv

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from recon.db import tenant_context
from recon.models import Location, ReconException, UserOrg
from recon.reconcile import reconcile

# Brief: "A hardcoded pair of users with an org each is fine."
DEMO_USERS = [("alice", "alice-pass", "ORG-A"), ("bob", "bob-pass", "ORG-B")]


class Command(BaseCommand):
    help = "Reconcile data/*.csv and load the exceptions (and demo users)."

    def add_arguments(self, parser):
        parser.add_argument("--data-dir", default=str(settings.DATA_DIR))

    def handle(self, *args, data_dir, **options):
        result = reconcile(data_dir)
        with open(f"{data_dir}/locations.csv", newline="", encoding="utf-8-sig") as f:
            locations = [{k.strip(): v.strip() for k, v in r.items()} for r in csv.DictReader(f)]
        orgs = sorted({loc["org_id"] for loc in locations})

        for org in orgs:
            with tenant_context(org):
                ReconException.objects.all().delete()  # RLS: only this org's rows
                Location.objects.all().delete()
                Location.objects.bulk_create(
                    Location(location_id=loc["location_id"], org_id=org, name=loc["location_name"])
                    for loc in locations if loc["org_id"] == org
                )
                rows = [f for f in result.findings if f.org_id == org]
                ReconException.objects.bulk_create(
                    ReconException(
                        org_id=f.org_id, reason_code=f.reason_code, record_id=f.record_id,
                        entry_ids=f.entry_ids, location_id=f.location_id, event_date=f.event_date,
                        system_a_amount=f.system_a_amount, system_b_amount=f.system_b_amount,
                        detail=f.detail,
                    )
                    for f in rows
                )
            self.stdout.write(f"{org}: {len(rows)} exceptions")

        for f in result.unassignable:
            self.stderr.write(f"Not loaded (location belongs to no org): {f.reason_code} {f.detail}")

        for username, password, org in DEMO_USERS:
            user, _ = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.save()
            UserOrg.objects.update_or_create(user=user, defaults={"org_id": org})
        self.stdout.write(
            f"Matched {result.matched_records} System A records to System B. "
            f"Users: {', '.join(u for u, _, _ in DEMO_USERS)}."
        )
