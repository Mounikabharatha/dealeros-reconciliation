"""JSON API. Plain Django views; the surface is five endpoints.

Every data view is wrapped in ``org_scoped``, which opens a transaction with
the caller's org as the database tenant. The ``.filter(org_id=...)`` calls
below are a second, application-level guard only: the isolation tests delete
them (by bypassing the views) and the database still refuses other orgs' rows.
"""
import json
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import ask as ask_module
from .db import tenant_context
from .models import Location, ReconException, UserOrg
from .reconcile import REASONS


def _org_for(user):
    try:
        return user.org.org_id
    except UserOrg.DoesNotExist:
        return None


def org_scoped(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Please log in."}, status=401)
        org = _org_for(request.user)
        if not org:
            return JsonResponse({"error": "Your user is not assigned to an organisation."}, status=403)
        with tenant_context(org):
            return view(request, org, *args, **kwargs)
    return wrapper


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return None


@require_GET
@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({"ok": True})


@require_POST
def login_view(request):
    body = _json_body(request) or {}
    user = authenticate(request, username=body.get("username", ""), password=body.get("password", ""))
    if user is None:
        return JsonResponse({"error": "Wrong username or password."}, status=400)
    login(request, user)
    return JsonResponse({"username": user.username, "org_id": _org_for(user)})


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"ok": True})


@require_GET
def me(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Please log in."}, status=401)
    return JsonResponse({"username": request.user.username, "org_id": _org_for(request.user)})


def _serialize(e):
    label, action = REASONS[e.reason_code]
    diff = e.difference
    return {
        "id": e.id,
        "reason_code": e.reason_code,
        "reason": label,
        "action": action,
        "record_id": e.record_id,
        "entry_ids": e.entry_ids,
        "location_id": e.location_id,
        "event_date": e.event_date.isoformat() if e.event_date else None,
        "system_a_amount": None if e.system_a_amount is None else str(e.system_a_amount),
        "system_b_amount": None if e.system_b_amount is None else str(e.system_b_amount),
        "difference": None if diff is None else str(diff),
        "detail": e.detail,
    }


@require_GET
@org_scoped
def exceptions_list(request, org):
    """GET /api/exceptions?reason_code=...&location_id=..."""
    qs = ReconException.objects.filter(org_id=org)
    reason = request.GET.get("reason_code")
    location = request.GET.get("location_id")
    if reason:
        qs = qs.filter(reason_code=reason)
    if location:
        qs = qs.filter(location_id=location)
    all_rows = ReconException.objects.filter(org_id=org)
    return JsonResponse({
        "org_id": org,
        "count": qs.count(),
        "results": [_serialize(e) for e in qs],
        # Filter options come from this org's own rows/locations only.
        "filters": {
            "reason_codes": [
                {"code": c, "label": REASONS[c][0]}
                for c in sorted(set(all_rows.values_list("reason_code", flat=True)))
            ],
            "locations": list(Location.objects.filter(org_id=org).order_by("location_id")
                              .values_list("location_id", flat=True)),
        },
    })


@require_POST
@org_scoped
def ask(request, org):
    """POST /api/ask {"question": "..."}"""
    body = _json_body(request)
    if body is None or not isinstance(body.get("question"), str):
        return JsonResponse({"error": 'Send JSON like {"question": "..."}'}, status=400)
    rows = list(ReconException.objects.filter(org_id=org))
    locations = set(Location.objects.filter(org_id=org).values_list("location_id", flat=True))
    return JsonResponse(ask_module.answer(body["question"], rows, locations))
