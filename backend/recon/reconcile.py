"""Match System A records to System B entries and list the disagreements.

Pure Python, no database: input is the three CSV files, output is a list of
``Finding``. This keeps the matching rules testable on their own and keeps
cross-tenant reading (which reconciliation needs, e.g. REC-1077) out of the
application's database connection entirely.

What is deliberately NOT reported (non-errors):
* Messy references (``rec1034``, `` REC - 1070 ``, ``1112``) that clean up to
  exactly one System A record: a formatting difference, not a disagreement.
* Amounts written with different digit grouping (``1,25,400.00``): parsed first,
  then compared. Only a different *value* is reported.
* One record split across several System B entries whose amounts add up to
  System A's total to the cent (REC-1055).
* A cancelled (VOIDED) System A record with no System B entry: both agree it
  does not exist.
* A small posting lag: System B dated up to 3 days after System A, inside the
  same calendar month. Crossing into another month is reported, because it
  moves the amount into a different reporting period.
"""
import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

POSTING_LAG_DAYS = 3

# code -> (what it means, what to do). Shown to users as-is, so plain words.
REASONS = {
    "MISSING_IN_SYSTEM_B": (
        "In System A but missing from System B",
        "Ask the System B team to record this event.",
    ),
    "MISSING_IN_SYSTEM_A": (
        "In System B but there is no matching record in System A",
        "Check whether System A should have this event, or remove the System B entry.",
    ),
    "AMOUNT_MISMATCH": (
        "The two systems show different amounts",
        "Check the source paperwork and correct whichever system is wrong.",
    ),
    "ADJUSTMENT_MISSING_IN_SYSTEM_B": (
        "System B has the amount before the adjustment was added",
        "Add the adjustment to the System B entry.",
    ),
    "AMOUNT_MISSING_IN_SYSTEM_B": (
        "System B entry has no amount",
        "Fill in the amount in System B.",
    ),
    "DUPLICATE_IN_SYSTEM_B": (
        "Recorded twice in System B",
        "Delete the extra System B entry so it is not counted twice.",
    ),
    "CANCELLED_IN_A_ACTIVE_IN_B": (
        "Cancelled in System A but still active in System B",
        "Cancel the System B entry too, or reinstate the record in System A.",
    ),
    "LOCATION_MISMATCH": (
        "The two systems put it at different locations",
        "Confirm the right location and correct the other system.",
    ),
    "FILED_UNDER_OTHER_ORGANISATION": (
        "The other system filed this under a location that is not in your organisation",
        "Contact support: the record is attached to the wrong organisation.",
    ),
    "DATE_MISMATCH": (
        "The two systems show different dates",
        "Confirm the correct date; it may land in a different month's report.",
    ),
    "CATEGORY_MISMATCH": (
        "The two systems show different categories",
        "Confirm the correct category and fix the other system.",
    ),
    "UNREADABLE_REFERENCE": (
        "System B entry does not say which record it belongs to",
        "Add the record number to the System B entry.",
    ),
    "SYSTEM_A_TOTAL_DOES_NOT_ADD_UP": (
        "In System A, base plus adjustment does not equal the total",
        "Correct the System A record.",
    ),
}


@dataclass
class Finding:
    org_id: str
    reason_code: str
    location_id: str
    detail: str
    record_id: str = ""
    entry_ids: list = field(default_factory=list)
    event_date: date | None = None
    system_a_amount: Decimal | None = None
    system_b_amount: Decimal | None = None


@dataclass
class Result:
    findings: list
    unassignable: list  # rows whose location is in no org: cannot be shown to anyone
    matched_records: int


def normalize_ref(raw):
    """``' REC - 1070 '``, ``rec1070`` and ``1070`` all mean ``REC-1070``.

    Exactly one run of digits is required; anything else is unreadable rather
    than guessed at.
    """
    digits = re.findall(r"\d+", raw or "")
    if len(digits) != 1:
        return None
    return f"REC-{digits[0]}"


def parse_amount(raw):
    """``'1,25,400.00'`` -> Decimal('125400.00'); blank or junk -> None."""
    text = (raw or "").strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _money(value):
    return "no amount" if value is None else f"{value:,.2f}"


def reconcile(data_dir):
    data_dir = Path(data_dir)
    org_of = {r["location_id"]: r["org_id"] for r in _read(data_dir / "locations.csv")}
    a_rows = _read(data_dir / "system_a.csv")
    b_rows = _read(data_dir / "system_b.csv")

    findings, unassignable = [], []

    def add(f):
        if f.org_id is None:
            unassignable.append(f)
        else:
            findings.append(f)

    entries_by_record = defaultdict(list)
    for b in b_rows:
        ref = normalize_ref(b["record_ref"])
        if ref is None:
            add(Finding(
                org_id=org_of.get(b["location_id"]), reason_code="UNREADABLE_REFERENCE",
                location_id=b["location_id"], entry_ids=[b["entry_id"]],
                event_date=date.fromisoformat(b["recorded_on"]) if b["recorded_on"] else None,
                system_b_amount=parse_amount(b["value"]),
                detail=f"System B entry {b['entry_id']} has record reference {b['record_ref']!r}, which names no record.",
            ))
            continue
        entries_by_record[ref].append(b)

    a_ids = {a["record_id"] for a in a_rows}
    for ref, entries in entries_by_record.items():
        if ref in a_ids:
            continue
        for b in entries:
            add(Finding(
                org_id=org_of.get(b["location_id"]), reason_code="MISSING_IN_SYSTEM_A",
                record_id=ref, entry_ids=[b["entry_id"]], location_id=b["location_id"],
                event_date=date.fromisoformat(b["recorded_on"]), system_b_amount=parse_amount(b["value"]),
                detail=f"System B entry {b['entry_id']} refers to {ref}, which does not exist in System A.",
            ))

    matched = 0
    for a in a_rows:
        rid, loc = a["record_id"], a["location_id"]
        org = org_of.get(loc)
        a_date = date.fromisoformat(a["event_date"])
        base, adj, total = (parse_amount(a[k]) for k in ("base_value", "adjustment", "total_value"))
        common = dict(org_id=org, record_id=rid, location_id=loc, event_date=a_date, system_a_amount=total)

        if None not in (base, adj, total) and base + adj != total:
            add(Finding(**common, reason_code="SYSTEM_A_TOTAL_DOES_NOT_ADD_UP",
                        detail=f"System A: {_money(base)} + {_money(adj)} = {_money(base + adj)}, but total says {_money(total)}."))

        entries = entries_by_record.get(rid, [])
        voided = a["state"].upper() == "VOIDED"

        if not entries:
            if not voided:  # voided + absent = both agree it is gone
                add(Finding(**common, reason_code="MISSING_IN_SYSTEM_B",
                            detail=f"{rid} ({_money(total)}) has no entry in System B."))
            continue
        matched += 1

        # Entries filed under another org cannot be reconciled here without
        # showing one tenant the other's data: one finding per side, each
        # holding only that side's own identifiers and amounts.
        same_org = [b for b in entries if org_of.get(b["location_id"]) == org]
        for b in entries:
            b_org = org_of.get(b["location_id"])
            if b_org == org:
                continue
            add(Finding(**common, reason_code="FILED_UNDER_OTHER_ORGANISATION",
                        detail=f"System B filed {rid} under a location outside your organisation."))
            add(Finding(org_id=b_org, reason_code="FILED_UNDER_OTHER_ORGANISATION",
                        entry_ids=[b["entry_id"]], location_id=b["location_id"],
                        event_date=date.fromisoformat(b["recorded_on"]),
                        system_b_amount=parse_amount(b["value"]),
                        detail=f"System B entry {b['entry_id']} at {b['location_id']} belongs to a record "
                               f"that System A holds for a different organisation."))
        if not same_org:
            continue
        ids = [b["entry_id"] for b in same_org]

        if voided:
            add(Finding(**common, entry_ids=ids, reason_code="CANCELLED_IN_A_ACTIVE_IN_B",
                        system_b_amount=sum((parse_amount(b["value"]) or 0) for b in same_org),
                        detail=f"{rid} is cancelled in System A, but System B still has {', '.join(ids)}."))
            continue

        for b in same_org:
            if b["location_id"] != loc:
                add(Finding(**common, entry_ids=[b["entry_id"]], reason_code="LOCATION_MISMATCH",
                            detail=f"System A says {loc}; System B entry {b['entry_id']} says {b['location_id']}."))
            b_date = date.fromisoformat(b["recorded_on"])
            lag = (b_date - a_date).days
            same_month = (b_date.year, b_date.month) == (a_date.year, a_date.month)
            if lag != 0 and not (0 < lag <= POSTING_LAG_DAYS and same_month):
                where = "" if same_month else " - a different month, so it falls in a different report"
                add(Finding(**common, entry_ids=[b["entry_id"]], reason_code="DATE_MISMATCH",
                            detail=f"System A: {a_date}; System B entry {b['entry_id']}: {b_date}{where}."))
            m = re.fullmatch(r"Entry for (\S+)", b["label"])
            if m and m.group(1) != a["category_code"]:
                add(Finding(**common, entry_ids=[b["entry_id"]], reason_code="CATEGORY_MISMATCH",
                            detail=f"System A: {a['category_code']}; System B entry {b['entry_id']}: {m.group(1)}."))

        _compare_amounts(add, common, rid, same_org, base, adj, total)

    return Result(findings=findings, unassignable=unassignable, matched_records=matched)


def _compare_amounts(add, common, rid, entries, base, adj, total):
    values = [parse_amount(b["value"]) for b in entries]
    ids = [b["entry_id"] for b in entries]

    blank = [b["entry_id"] for b, v in zip(entries, values) if v is None]
    if blank:
        add(Finding(**common, entry_ids=blank, reason_code="AMOUNT_MISSING_IN_SYSTEM_B",
                    detail=f"System B entry {', '.join(blank)} for {rid} has no readable amount "
                           f"(System A: {_money(total)})."))
        return

    if sum(values) == total:
        return  # one entry that matches, or a clean split that adds up

    # Identical entries (same amount, date, location, label) are double-posts.
    seen, kept, dupes = set(), [], []
    for b, v in zip(entries, values):
        key = (v, b["recorded_on"], b["location_id"], b["label"])
        (dupes if key in seen else kept).append((b, v))
        seen.add(key)
    if dupes:
        dupe_ids = [b["entry_id"] for b, _ in dupes]
        add(Finding(**common, entry_ids=ids, system_b_amount=sum(values), reason_code="DUPLICATE_IN_SYSTEM_B",
                    detail=f"{rid} appears {len(entries)} times in System B ({', '.join(ids)}); "
                           f"{', '.join(dupe_ids)} repeats an earlier entry, so it is counted twice."))
        if sum(v for _, v in kept) == total:
            return
        entries, values = [b for b, _ in kept], [v for _, v in kept]
        ids = [b["entry_id"] for b in entries]

    b_total = sum(values)
    if len(values) == 1 and adj and b_total == base:
        add(Finding(**common, entry_ids=ids, system_b_amount=b_total, reason_code="ADJUSTMENT_MISSING_IN_SYSTEM_B",
                    detail=f"System B shows {_money(b_total)}, which is System A's amount before the "
                           f"{_money(adj)} adjustment (System A total {_money(total)})."))
        return
    add(Finding(**common, entry_ids=ids, system_b_amount=b_total, reason_code="AMOUNT_MISMATCH",
                detail=f"System A: {_money(total)}; System B: {_money(b_total)} "
                       f"(difference {_money(b_total - total)})."))
