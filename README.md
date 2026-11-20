# DealerOS: reconciliation exceptions, one tenant at a time

A vertical slice: two CSV exports that should agree → a list of the records they
disagree about → stored per tenant with PostgreSQL Row-Level Security → a JSON API
→ a plain React table with filters → one endpoint that answers questions about the
exceptions, citing the rows behind every number, and refuses when it can't.

Stack: Django 5.2 + PostgreSQL (required, for RLS) + React 18 (Vite).

## How to run it

**You need:** Python 3.11+, Node 18+, and PostgreSQL 14+ running locally (tested on PostgreSQL 17, Python 3.11, Node 24). The
Postgres user you connect as must be able to create a database and a role; the
default user of a Homebrew / Postgres.app / apt install can.

```bash
git clone <this repo> dealeros && cd dealeros

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

createdb dealeros
python backend/manage.py migrate     # tables + RLS policies + the dealeros_app role
python backend/manage.py ingest      # reconcile data/*.csv, load, create demo users
python backend/manage.py test recon  # 39 tests, including the isolation tests
python backend/manage.py runserver   # API on http://127.0.0.1:8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev                          # UI on http://localhost:5173
```

Open **http://localhost:5173** and log in:

| user  | password   | org   | sees |
|-------|------------|-------|------|
| alice | alice-pass | ORG-A | 7 exceptions (LOC-101/102/103) |
| bob   | bob-pass   | ORG-B | 6 exceptions (LOC-201/202) |

**Postgres somewhere else (password, other host, Docker)?** Set these before
`createdb`/`migrate` (all optional; empty means the libpq default):

```bash
export POSTGRES_HOST=localhost POSTGRES_PORT=5432 POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=dealeros
export PGHOST=$POSTGRES_HOST PGUSER=$POSTGRES_USER PGPASSWORD=$POSTGRES_PASSWORD   # so createdb uses them too
```

e.g. with Docker: `docker run -d --name dealeros-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16`, then the exports above. (These settings were tested against a fresh, empty PostgreSQL connected as `postgres` over TCP; the Docker command itself was not run, as Docker isn't installed on my machine.)

### The API

All endpoints need a logged-in session (the UI handles this).

* `GET /api/exceptions?reason_code=&location_id=`: the caller's org's exceptions, plus the filter options.
* `POST /api/ask` `{"question": "How many duplicates?"}` returns `{"answered": bool, "answer": str, "facts": [{"label", "value", "cited_ids"}]}`.
* `POST /api/login`, `POST /api/logout`, `GET /api/me`, `GET /api/csrf`.

Questions it answers (count / list / total amount gap, optionally by one reason,
location, month or record): *How many exceptions are there?* · *Which records are
missing from System B?* · *total amount difference at LOC-101* · *number of
exceptions by location* · *show REC-1064*. Questions it refuses: anything about
data that isn't there (*profit*, *2024*, *who*), logic it doesn't do (*not*, *more
than*, *why*, *predict*), other orgs' locations, or more than one filter of a kind.

## What I built

**1. Ingest and reconcile.** [`backend/recon/reconcile.py`](backend/recon/reconcile.py) is pure Python.
`record_ref` is normalised to `REC-<digits>` (exactly one run of digits, or the entry is
reported as unreadable rather than guessed). Amounts are parsed before comparing
(`1,25,400.00` → 125400.00). 118 of 120 System A records match; the result is **13
exceptions** with plain reason labels and a "what to do" for each:

| Org | Record / entry | Reason |
|---|---|---|
| A | REC-1015 | In System A but missing from System B |
| A | REC-1027, REC-1088 | System B has the amount before the adjustment was added |
| A | REC-1042 (ENT 4042 + 4902) | Recorded twice in System B |
| A | REC-1064 | The two systems show different amounts (183,244.16 vs 125,400.00) |
| A | REC-1077 | The other system filed this under a location that is not in your organisation |
| A | ENT/2026/4901 → REC-1999 | In System B but there is no matching record in System A |
| B | REC-1003 | System B has the amount before the adjustment was added |
| B | REC-1009 | The two systems show different dates (31 Mar vs 2 Apr: different month) |
| B | REC-1019 | Cancelled in System A but still active in System B |
| B | REC-1050 | System B entry has no amount |
| B | REC-1061 | In System A but missing from System B |
| B | ENT/2026/4077 | The other system filed this under a location that is not in your organisation |

Deliberately **not** reported: the messy references (rec1034, " REC - 1070 ", 1112),
the split REC-1055 (two entries adding up to the cent), the number formatting
difference itself, and small same-month posting lags. Reasons in [DECISIONS.md](DECISIONS.md).

**2. Tenant isolation, enforced in PostgreSQL.**
* [`migrations/0002_row_level_security.py`](backend/recon/migrations/0002_row_level_security.py): `ENABLE` + `FORCE ROW LEVEL SECURITY` on both tenant tables, with a policy `org_id = current_setting('app.current_org')` for both reading (`USING`) and writing (`WITH CHECK`).
* [`recon/db.py`](backend/recon/db.py): every new connection runs `SET ROLE dealeros_app` (not a superuser, no `BYPASSRLS`). The tenant is a transaction-local setting, set by `tenant_context(org)`. Forgetting either gives **zero rows**, not every row.
* [`tests/test_isolation.py`](backend/recon/tests/test_isolation.py): queries with **no org filter at all** (`.all()`, raw SQL, explicit `org_id="ORG-B"`, cross-org insert/update/delete) and asserts the database refuses. [`tests/test_api.py`](backend/recon/tests/test_api.py) also deletes the view's own `.filter(org_id=...)` with a mock and shows the endpoint is still isolated.
* [WALKTHROUGH.md](WALKTHROUGH.md) shows these tests failing with the protection removed and passing with it back.

**3. Surface.** Plain JSON views ([`views.py`](backend/recon/views.py)) and one React file ([`App.jsx`](frontend/src/App.jsx)) with a table, reason and location filters (server-side), and a question box.

**4. Grounded answers.** [`recon/ask.py`](backend/recon/ask.py) parses the question into a closed query and computes every number in code over the caller's rows, citing the record and entry ids it used. Unknown words, unsupported logic, out-of-range periods and other orgs' locations are refused with a reason. No language model is involved, so no API key is needed and there is nothing to prompt-inject.

## What I deliberately did not build

* **An LLM in the ask path.** See DECISIONS #8. The closed query is the part that matters; an LLM could be put in front of it as a phrasing translator later.
* **Real authentication.** Two seeded users, as the brief allows. No sign-up, password reset or roles within an org.
* **Storing raw System A/B rows / drill-down.** Users see exceptions only ("Nothing else.").
* **Resolving or commenting on exceptions**, re-uploading CSVs from the UI, pagination (13 rows), CI, Docker Compose, frontend tests.
* **Visual design.** It's a plain table.

## Tests

`python backend/manage.py test recon`: 39 tests:
`test_isolation` (database-level tenant isolation), `test_reconcile` (the exact
13 findings on the real CSVs plus every non-error), `test_api` (login, filters,
cross-org attempts, ask answers and refusals).

## How I worked with the agent

I built this with Claude Code doing most of the writing: I gave it the brief and data, and it worked in the order isolation first, then reconciliation, API, UI and docs. It saved the most time on boilerplate (Django, Vite, the table) and on cataloguing every planted problem in the 241 CSV rows before any matching rule was written. It was confidently wrong twice in the isolation code: it wrote a test claiming the app "cannot switch back to a privileged role", which is false when Django connects as a Postgres superuser, so the test was deleted on review before it ever ran and the limit is documented in DECISIONS #2. Its first `tenant_context` also leaked the org past its block inside an outer transaction; the fail-closed test caught it (3 rows instead of 0), and the fix restores the previous value on exit. Because a test that passes by accident proves nothing, the isolation suite was then re-run with RLS commented out to confirm each test fails for the right reason (see WALKTHROUGH.md).
