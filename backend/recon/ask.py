"""Answer a plain-language question about the caller's exceptions.

Design: the question is parsed into a small, closed query (one metric, at most
one filter of each kind). Numbers are computed by code over rows that RLS
already scoped to the caller's org, and every number carries the ids of the
rows it came from. No language model writes any number, so nothing can be
talked into inventing one.

Refusal is the default. The question is refused when:
* it uses any word outside the vocabulary below (we do not guess what it means),
* it needs logic we do not support (negation, comparison, "why", forecasts),
* it names a location, month or year that is not in the caller's data,
* it is ambiguous (two reasons, two locations, no metric).
"""
import re
from decimal import Decimal

from .reconcile import REASONS

REASON_PHRASES = [
    ("MISSING_IN_SYSTEM_B", r"missing (?:from|in) (?:system )?b"),
    ("MISSING_IN_SYSTEM_A", r"missing (?:from|in) (?:system )?a"),
    ("AMOUNT_MISSING_IN_SYSTEM_B", r"(?:no|blank|empty|missing) amounts?"),
    ("ADJUSTMENT_MISSING_IN_SYSTEM_B", r"(?:missing )?adjustments?"),
    ("AMOUNT_MISMATCH", r"amount mismatch(?:es)?|different amounts?|amounts? (?:differ|mismatch(?:es)?)"),
    ("DUPLICATE_IN_SYSTEM_B", r"duplicates?|duplicated|double[- ]?(?:counted|posted|entries)"),
    ("CANCELLED_IN_A_ACTIVE_IN_B", r"cancell?ed|voided|voids?"),
    ("LOCATION_MISMATCH", r"location mismatch(?:es)?|wrong locations?"),
    ("FILED_UNDER_OTHER_ORGANISATION", r"(?:other|another|wrong) organi[sz]ations?"),
    ("DATE_MISMATCH", r"date mismatch(?:es)?|different dates?|wrong dates?|dates? differ"),
    ("CATEGORY_MISMATCH", r"category mismatch(?:es)?|different categor(?:y|ies)"),
    ("UNREADABLE_REFERENCE", r"unreadable references?"),
    ("SYSTEM_A_TOTAL_DOES_NOT_ADD_UP", r"(?:does not|doesn't) add up"),
]
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}

COUNT_WORDS = {"how many", "count", "number"}
SUM_WORDS = {"amount", "amounts", "value", "difference", "differences", "gap", "money"}
LIST_WORDS = {"which", "list", "show", "what", "wrong"}
FILLER = {
    "how", "many", "count", "number", "of", "the", "a", "an", "are", "is", "there", "were", "was",
    "in", "at", "for", "with", "my", "our", "me", "show", "list", "which", "what", "whats", "s",
    "exceptions", "exception", "records", "record", "rows", "entries", "entry", "items", "issues",
    "problems", "disagreements", "total", "sum", "amount", "amounts", "value", "difference",
    "differences", "gap", "money", "combined", "all", "do", "does", "have", "has", "we", "i", "give",
    "tell", "please", "from", "on", "system", "systems", "location", "locations", "wrong", "by",
    "per", "each", "reason", "reasons", "code", "codes", "it", "this", "that", "these", "those",
}
# Words that mean the question needs logic we do not do. Named explicitly so
# the refusal can say why, instead of a generic "unknown word".
UNSUPPORTED = {
    "not", "no", "except", "excluding", "without", "more", "less", "than", "above", "below",
    "over", "under", "greater", "fewer", "before", "after", "between", "average", "mean",
    "median", "percent", "percentage", "why", "will", "would", "should", "could", "if",
    "predict", "forecast", "expect", "trend", "compare", "versus", "vs", "and", "or",
}


def refuse(why):
    return {"answered": False, "answer": f"I can't answer that from the exceptions data: {why}", "facts": []}


def _ids(rows):
    out = []
    for r in rows:
        out += r.source_ids()
    return out


def _cite(rows):
    return ", ".join(_ids(rows)) if rows else "no matching rows"


def answer(question, rows, location_ids):
    """``rows``: the caller's ReconException rows (already RLS-scoped)."""
    text = (question or "").strip()
    if not text:
        return refuse("the question is empty.")
    if len(text) > 300:
        return refuse("the question is too long; ask one thing at a time.")

    found_codes = set(re.findall(r"\b[A-Z][A-Z_]{5,}\b", text)) & set(REASONS)
    low = " " + text.lower().replace("’", "'") + " "
    for code in found_codes:
        low = low.replace(" " + code.lower() + " ", " ")

    reasons = set(found_codes)
    for code, pattern in REASON_PHRASES:
        low, n = re.subn(rf"\b(?:{pattern})\b", " ", low)
        if n:
            reasons.add(code)

    locs = {f"LOC-{n}" for n in re.findall(r"\bloc(?:ation)?[- ]?(\d+)\b", low)}
    low = re.sub(r"\bloc(?:ation)?[- ]?\d+\b", " ", low)
    recs = {f"REC-{n}" for n in re.findall(r"\brec[- ]?(\d+)\b", low)}
    low = re.sub(r"\brec[- ]?\d+\b", " ", low)
    ents = {e.upper() for e in re.findall(r"\bent/\d{4}/\d+\b", low)}
    low = re.sub(r"\bent/\d{4}/\d+\b", " ", low)
    years = {int(y) for y in re.findall(r"\b(\d{4})\b", low)}
    low = re.sub(r"\b\d{4}\b", " ", low)
    months = {MONTHS[m] for m in re.findall(r"\b(" + "|".join(MONTHS) + r")\b", low)}
    low = re.sub(r"\b(" + "|".join(MONTHS) + r")\b", " ", low)

    words = re.findall(r"[a-z0-9']+", low.replace("'s", " s").replace("n't", " not"))
    bad = sorted({w for w in words if w in UNSUPPORTED})
    if bad:
        return refuse(f"it needs logic I don't support ({', '.join(bad)}). I can count, list, or "
                      "total the amount gap, filtered by one reason, one location, or one month.")
    unknown = sorted({w for w in words if w not in FILLER})
    if unknown:
        return refuse(f"I don't know what {', '.join(repr(w) for w in unknown)} refers to in this data.")

    if len(reasons) > 1 or len(locs) > 1 or len(months) > 1 or len(recs | ents) > 1:
        return refuse("it asks about more than one reason, location, month or record at once. "
                      "Ask about one at a time.")
    loc = next(iter(locs), None)
    if loc and loc not in location_ids:
        return refuse(f"there is no location {loc} in your organisation's data.")

    dated = [r.event_date for r in rows if r.event_date]
    data_years = {d.year for d in dated}
    if years - data_years:
        return refuse(f"the data only covers {_span(dated)}.")
    data_months = {(d.year, d.month) for d in dated}
    if months and not any(m == month for _, m in data_months for month in months):
        return refuse(f"the data only covers {_span(dated)}.")

    selected = list(rows)
    applied = []
    if reasons:
        code = next(iter(reasons))
        selected = [r for r in selected if r.reason_code == code]
        applied.append(f"reason \"{REASONS[code][0]}\" ({code})")
    if loc:
        selected = [r for r in selected if r.location_id == loc]
        applied.append(f"location {loc}")
    if months:
        month = next(iter(months))
        year = next(iter(years), None)
        selected = [r for r in selected if r.event_date and r.event_date.month == month
                    and (year is None or r.event_date.year == year)]
        applied.append(f"month {[k for k, v in MONTHS.items() if v == month][0].title()}"
                       + (f" {year}" if year else ""))
    rid = next(iter(recs | ents), None)
    if rid:
        selected = [r for r in selected if rid in r.source_ids()]
        applied.append(f"record {rid}")
    scope = " with " + " and ".join(applied) if applied else ""

    grouped_by = None
    if re.search(r"\b(?:by|per|each)\b", low):
        if re.search(r"\b(?:by|per|each) locations?\b", low):
            grouped_by = "location"
        elif re.search(r"\b(?:by|per|each) reasons?(?: codes?)?\b", low):
            grouped_by = "reason"
        else:
            return refuse("I can only break results down by location or by reason.")

    if any(w in SUM_WORDS for w in words):
        return _sum(selected, scope)
    if "how many" in low or any(w in {"count", "number", "total"} for w in words) or grouped_by:
        return _count(selected, scope, grouped_by)
    if any(w in LIST_WORDS for w in words) or rid:
        return _list(selected, scope)
    return refuse("I can't tell whether you want a count, a list, or the total amount gap.")


def _n(count):
    return f"{count} exception{'' if count == 1 else 's'}"


def _span(dates):
    if not dates:
        return "no dates"
    return f"{min(dates):%d %b %Y} to {max(dates):%d %b %Y}"


def _count(rows, scope, grouped_by):
    if grouped_by:
        key = (lambda r: r.location_id) if grouped_by == "location" else (lambda r: r.reason_code)
        groups = {}
        for r in rows:
            groups.setdefault(key(r), []).append(r)
        facts = [{"label": k, "value": len(v), "cited_ids": _ids(v)} for k, v in sorted(groups.items())]
        lines = [f"- {f['label']}: {f['value']} ({', '.join(f['cited_ids'])})" for f in facts]
        head = f"{_n(len(rows))}{scope}, by {grouped_by}:"
        return {"answered": True, "answer": "\n".join([head] + lines) if facts else head + " none.",
                "facts": facts}
    n = len(rows)
    return {"answered": True,
            "answer": f"{_n(n)}{scope}: {_cite(rows)}.",
            "facts": [{"label": "exceptions", "value": n, "cited_ids": _ids(rows)}]}


def _list(rows, scope):
    if not rows:
        return {"answered": True, "answer": f"No exceptions{scope}.", "facts": []}
    lines = [f"- {', '.join(r.source_ids())} at {r.location_id}: {REASONS[r.reason_code][0]}. {r.detail}"
             for r in rows]
    return {"answered": True, "answer": f"{_n(len(rows))}{scope}:\n" + "\n".join(lines),
            "facts": [{"label": "exceptions", "value": len(rows), "cited_ids": _ids(rows)}]}


def _sum(rows, scope):
    both = [r for r in rows if r.system_a_amount is not None and r.system_b_amount is not None]
    skipped = [r for r in rows if r not in both]
    gap = sum((abs(r.difference) for r in both), Decimal("0.00"))
    msg = (f"The amount gap between System A and System B{scope} is {gap:,.2f} in total "
           f"(sum of absolute differences), from {_cite(both)}.")
    if skipped:
        msg += (f" Not included because one system has no amount for them: {_cite(skipped)}. "
                "Their gap is unknown, so the true total may be higher.")
    facts = [{"label": "amount gap", "value": str(gap), "cited_ids": _ids(both)}]
    return {"answered": True, "answer": msg, "facts": facts}
