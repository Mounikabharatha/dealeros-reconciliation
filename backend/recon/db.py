"""Database-level tenant isolation plumbing.

Two rules, both enforced by PostgreSQL rather than by Django querysets:

1. Every application connection runs as the restricted role ``dealeros_app``
   (no superuser, no BYPASSRLS). The switch happens on ``connection_created``,
   so it applies to every connection unless code *explicitly* opts out with
   ``admin_connection()`` (only ``migrate``, ``ingest`` and test setup do).
   Forgetting something here fails closed, not open.

2. The tenant is a transaction-local setting, ``app.current_org``. Row-Level
   Security policies (migration 0002) compare each row's ``org_id`` with it.
   No setting means no rows: forgetting ``tenant_context()`` also fails closed.
"""
from contextlib import contextmanager

from django.conf import settings
from django.db import connection, transaction
from django.db.backends.signals import connection_created
from django.dispatch import receiver

_admin_mode = False


@receiver(connection_created)
def _restrict_new_connection(sender, connection, **kwargs):
    if _admin_mode:
        return
    with connection.cursor() as cursor:
        # Identifier comes from settings, not user input.
        cursor.execute(f'SET ROLE "{settings.DEALEROS_APP_ROLE}"')


@contextmanager
def admin_connection():
    """Run the block on a fresh connection as the connecting (owner) user.

    Used for schema migrations and the CSV ingest only. Closes the connection
    on both sides so a privileged connection is never reused by app code.
    """
    global _admin_mode
    connection.close()
    _admin_mode = True
    try:
        yield
    finally:
        connection.close()
        _admin_mode = False


@contextmanager
def tenant_context(org_id):
    """Open a transaction in which the database only shows ``org_id``'s rows."""
    if not org_id:
        raise ValueError("tenant_context needs an org_id")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.current_org', true)")
            previous = cursor.fetchone()[0] or ""
            # is_local=true: the setting dies with the transaction, so it can
            # never leak into the next request that reuses this connection.
            cursor.execute("SELECT set_config('app.current_org', %s, true)", [org_id])
        try:
            yield
        finally:
            # When nested inside a bigger transaction (a savepoint), "dies with
            # the transaction" is not soon enough: restore the outer value now.
            # On error the savepoint rollback restores it for us.
            if not connection.needs_rollback:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.current_org', %s, true)", [previous])
