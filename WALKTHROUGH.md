# Walkthrough

Follow "How to run it" in the README first (venv active, `createdb dealeros` done).
Every command below is run from the repo root.

## 1. The isolation test, passing

```bash
python backend/manage.py test recon.tests.test_isolation -v 2
```

```
test_asking_for_other_org_explicitly_returns_nothing ... ok
test_cannot_move_own_row_into_another_org ... ok
test_cannot_update_or_delete_other_orgs_rows ... ok
test_cannot_write_a_row_into_another_org ... ok
A view that forgets tenant_context() sees nothing (fails closed). ... ok
test_raw_sql_returns_only_own_org ... ok
Guard: if the app ran as a superuser, RLS would be silently skipped. ... ok
test_tenant_does_not_leak_out_of_its_block ... ok
test_unfiltered_orm_query_returns_only_own_org ... ok
Ran 9 tests
OK
```

None of these tests apply an org filter. They call `.all()`, raw SQL, or filter
for the *other* org on purpose. The only thing standing between ORG-A and ORG-B's
rows is the database.

## 2. Remove the database protection: the test fails

Open `backend/recon/migrations/0002_row_level_security.py` and comment out the two
lines marked `# DEMO` (the `ENABLE` and `FORCE ROW LEVEL SECURITY` lines):

```python
#        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",  # DEMO
#        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",  # DEMO
```

(or `sed -i.bak -E 's/^(        f"ALTER TABLE \{table\} (ENABLE|FORCE))/#\1/' backend/recon/migrations/0002_row_level_security.py`)

The test database is rebuilt from the migrations on every run, so just re-run:

```bash
python backend/manage.py test recon.tests.test_isolation
```

```
FAIL: test_asking_for_other_org_explicitly_returns_nothing   AssertionError: 3 != 0
FAIL: test_cannot_move_own_row_into_another_org              AssertionError: DatabaseError not raised
FAIL: test_cannot_update_or_delete_other_orgs_rows           AssertionError: 3 != 0
FAIL: test_cannot_write_a_row_into_another_org               AssertionError: DatabaseError not raised
FAIL: test_no_tenant_set_means_no_rows                       AssertionError: 6 != 0
FAIL: test_raw_sql_returns_only_own_org                      AssertionError: Lists differ: ['ORG-A', 'ORG-B'] != ['ORG-B']
FAIL: test_tenant_does_not_leak_out_of_its_block             AssertionError: Items in the first set but not the second
FAIL: test_unfiltered_orm_query_returns_only_own_org         AssertionError: Items in the first set but not the second
Ran 9 tests
FAILED (failures=8)
```

ORG-A now reads ORG-B's rows, can write rows into ORG-B, and a request with no
tenant sees all 6 rows. The one test still passing is the role guard
(`test_runs_as_restricted_role_not_superuser`), which checks the role, not RLS.

## 3. Put it back: the test passes

Uncomment the two lines (or `mv backend/recon/migrations/0002_row_level_security.py.bak backend/recon/migrations/0002_row_level_security.py`, or `git checkout -- backend/recon/migrations/0002_row_level_security.py`) and re-run:

```bash
python backend/manage.py test recon.tests.test_isolation
```

```
Ran 9 tests
OK
```

## 4. The same thing through the API, with the view's own filter deleted

`test_api.ExceptionsApi.test_view_with_app_filter_deleted_still_isolated` replaces
`ReconException.objects.filter` with "return everything" while alice calls
`GET /api/exceptions`. She still gets exactly her 7 rows, because the database
filtered them.

```bash
python backend/manage.py test recon.tests.test_api.ExceptionsApi.test_view_with_app_filter_deleted_still_isolated
```

## 5. In the browser

1. `python backend/manage.py runserver` and, in another terminal, `cd frontend && npm run dev`.
2. Open http://localhost:5173 and log in as **alice / alice-pass**. 7 rows, locations LOC-101..103 only.
3. Filter Location = LOC-101: 2 rows (REC-1042, REC-1064). Filter Reason = "System B has the amount before the adjustment was added": REC-1027, REC-1088.
4. Ask `total amount difference at LOC-101`. Answer: 170,681.22, citing REC-1042, ENT/2026/4042, ENT/2026/4902, REC-1064, ENT/2026/4064.
5. Ask `How many exceptions at LOC-201?`. Refused: there is no location LOC-201 in your organisation's data. ORG-B's location is not revealed.
6. Ask `What was the profit last year?`. Refused, naming the words it doesn't recognise.
7. Log out and log in as **bob / bob-pass**: 6 different rows, locations LOC-201/202 only.
