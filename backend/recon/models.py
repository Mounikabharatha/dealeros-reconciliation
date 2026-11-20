from django.conf import settings
from django.db import models


class UserOrg(models.Model):
    """Which org (tenant) a user belongs to. Exactly one per user.

    Not tenant data itself, so it has no RLS: we must read it to *find* the
    tenant before any tenant context exists.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org")
    org_id = models.CharField(max_length=32)

    def __str__(self):
        return f"{self.user} -> {self.org_id}"


class Location(models.Model):
    """Tenant-scoped (RLS). Mirrors locations.csv."""

    location_id = models.CharField(max_length=32, primary_key=True)
    org_id = models.CharField(max_length=32, db_index=True)
    name = models.CharField(max_length=128)

    class Meta:
        db_table = "recon_location"


class ReconException(models.Model):
    """One disagreement between System A and System B. Tenant-scoped (RLS).

    ``record_id`` and ``entry_ids`` are the source-row identifiers every
    answer must cite. A cross-tenant disagreement becomes one row per org,
    each showing only that org's own side.
    """

    org_id = models.CharField(max_length=32, db_index=True)
    reason_code = models.CharField(max_length=48, db_index=True)
    record_id = models.CharField(max_length=32, blank=True)  # System A id ("" if none)
    entry_ids = models.JSONField(default=list)  # System B ids
    location_id = models.CharField(max_length=32, db_index=True)
    event_date = models.DateField(null=True)
    system_a_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    system_b_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    detail = models.TextField()

    class Meta:
        db_table = "recon_exception"
        ordering = ["record_id", "reason_code", "id"]

    @property
    def difference(self):
        if self.system_a_amount is None or self.system_b_amount is None:
            return None
        return self.system_b_amount - self.system_a_amount

    def source_ids(self):
        return ([self.record_id] if self.record_id else []) + list(self.entry_ids)
