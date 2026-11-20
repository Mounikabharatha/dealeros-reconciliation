"""`manage.py migrate`, run as the owning user instead of the restricted role.

Schema changes need table ownership; application queries must never have it.
This is the only place (with `ingest` and test setup) that opts out.
"""
from django.core.management.commands.migrate import Command as DjangoMigrate

from recon.db import admin_connection


class Command(DjangoMigrate):
    def handle(self, *args, **options):
        with admin_connection():
            return super().handle(*args, **options)
