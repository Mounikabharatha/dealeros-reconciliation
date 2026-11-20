# Decisions

Each entry: the decision, the alternative I rejected, and the line that separated them.

1. **Tenant isolation = PostgreSQL Row-Level Security + a restricted role on every connection.**
   Rejected: a custom Django manager / queryset mixin that adds `org_id=` automatically.
   A manager is still application code that a raw query, `.objects` on another model, or a new teammate can skip; an RLS policy cannot be skipped by anything that connects as `dealeros_app`.

2. **The role switch happens on `connection_created` for *every* connection; only `migrate` and test-database setup opt out, explicitly, with `admin_connection()`. Even `ingest` runs as the restricted role.**
   Rejected: switching role inside a request middleware.
   Opt-in protection fails open when someone forgets it; opt-out protection fails closed.
   *Known limit:* on a laptop where Django connects as a Postgres superuser, code could run `RESET ROLE` to escape. In production the app would log in directly as a non-superuser `dealeros_app` login role, which closes that; I did not build two connection configs to keep the README to one setup path.

3. **Tenant is a transaction-local setting (`set_config(..., true)`), restored when a nested block exits.**
   Rejected: session-level `SET app.current_org`.
   A session setting survives on a pooled connection into the next user's request; a transaction-local one dies with the transaction. The nested-restore came from a failing test (see README, "How I worked with the agent").

4. **Reconcile in pure Python from the CSVs, then load each org's findings under its own tenant context.**
   Rejected: loading raw A/B rows into tables and reconciling in SQL.
   Reconciliation has to read across tenants (REC-1077 lives in ORG-A in System A and ORG-B in System B); the database role the app uses must never be able to do that, so cross-tenant reading stays outside the app's connection.

5. **A disagreement that crosses orgs (REC-1077) becomes two findings, one per org, each showing only its own side.**
   Rejected: showing it only to System A's org, with System B's location in the detail.
   Telling ORG-A "System B put this at LOC-201" leaks ORG-B's location and entry; each org still needs to know something is wrong with its own row.

6. **Not reported as problems:** references that clean up to exactly one record (`rec1034`, ` REC - 1070 `, `1112`); amounts that only differ in digit grouping (`1,25,400.00` is parsed first); a split entry whose parts add up to the cent (REC-1055); a cancelled record that System B also doesn't have; System B dated up to 3 days later *within the same month*.
   Rejected: exact-match on every field.
   These are formatting and timing differences that a person would close without any action, which makes them noise in a list that is supposed to be actionable.

7. **REC-1009 (31 Mar vs 2 Apr) *is* reported, as `DATE_MISMATCH`.**
   Rejected: treating every lag of 3 days or less as normal.
   The two systems put the amount in different months, so a monthly report would differ; that is something a person has to decide on.

8. **The question endpoint is deterministic: it parses the question into one closed query (count / list / amount gap, at most one reason, location, month or record) and refuses everything else. No language model.**
   Rejected: sending the rows and question to an LLM and asking it to cite rows.
   An LLM that writes numbers can be talked into a wrong one; here every number is computed by code over RLS-scoped rows, so it always cites real rows and runs without anyone needing an API key. The cost is narrow phrasing: unknown words are refused rather than guessed, and an LLM could later be added only to *translate* phrasing into the same closed query.

9. **"Amount gap" = sum of absolute differences, and rows where one side has no amount are excluded and named.**
   Rejected: a signed sum, or counting a missing amount as 0.
   Signed differences cancel each other out and zero is a guess; both would produce a confident wrong number.

10. **Not reported: REC-1050's blank `actor_id` in System A.**
    Rejected: a "data quality" reason code for it.
    System B has no actor field, so it is not a disagreement between the systems, and the brief asks for disagreements only. REC-1050 is still reported for its blank System B amount.
