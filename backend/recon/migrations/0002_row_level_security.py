"""Tenant isolation, enforced by PostgreSQL.

* ``dealeros_app`` is the role every application connection switches to
  (see recon/db.py). It is not a superuser and has no BYPASSRLS, so RLS
  policies always apply to it.
* Both tenant tables get ENABLE + FORCE ROW LEVEL SECURITY (FORCE makes the
  policy apply even to the table owner).
* The policy shows/accepts a row only when its org_id equals the
  transaction-local setting ``app.current_org``. If the setting is missing,
  current_setting(..., true) is NULL/'' and nothing matches: fail closed.

WALKTHROUGH demo: comment out the two lines marked "DEMO" below, run the
tests, and the isolation tests fail. Put them back and they pass.
"""
from django.db import migrations

ROLE = "dealeros_app"
TENANT_TABLES = ["recon_location", "recon_exception"]
POLICY = "current_setting('app.current_org', true)"

create_role = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
        CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;
    END IF;
END
$$;
GRANT {ROLE} TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO {ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROLE};
"""

forward = [create_role]
backward = []
for table in TENANT_TABLES:
    forward += [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",  # DEMO
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",  # DEMO
        f"""CREATE POLICY tenant_isolation ON {table}
                USING (org_id = {POLICY})
                WITH CHECK (org_id = {POLICY});""",
    ]
    backward += [
        f"DROP POLICY IF EXISTS tenant_isolation ON {table};",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
    ]


class Migration(migrations.Migration):
    dependencies = [
        ("recon", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("sessions", "0001_initial"),
    ]

    operations = [migrations.RunSQL(sql=forward, reverse_sql=backward)]
