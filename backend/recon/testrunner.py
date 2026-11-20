"""Test runner: build the test database as the owner, run every test as the app.

After setup the connection is closed, so the next one is opened through the
normal path and drops to the restricted ``dealeros_app`` role. Tests therefore
see the database exactly as the running application does.
"""
from django.test.runner import DiscoverRunner

from recon.db import admin_connection


class RestrictedRoleTestRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        with admin_connection():
            return super().setup_databases(**kwargs)

    def teardown_databases(self, old_config, **kwargs):
        with admin_connection():
            return super().teardown_databases(old_config, **kwargs)
