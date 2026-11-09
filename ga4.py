"""GA4 Deploy engine — GA4 Admin API over Hermes-owned OAuth.

RULE 11 COMPLIANT: this module never sees a token. The grant is declared under
`oauth:` in plugin.yaml, signed in with `hermes auth add ga4deploy:google`,
stored and refreshed by Hermes, attached by credentialed_provider_request().

Every quirk encoded here was verified against the live API in production
(27-account fleet deploys, API probes). The GA4 Admin API docs are frequently
wrong or silent; these mappings are ground truth:

- v1alpha for channelGroups / audiences / annotations / EM settings;
  v1beta customChannelGroups and dataStreams/*/enhancedMeasurementSettings
  return HTML 404s.
- Channel-group filters need eachScope* field names (sessionSource is rejected).
- inListFilter saves fine but renders BLANK in the GA4 UI -> always converted
  to anchored FULL_REGEXP alternation.
- Audiences: filterClauses are immutable; andGroup may only contain orGroup
  wrappers; pagePath is rejected (pageLocation works).
- Annotations: color is an uppercase enum; dedupe by title+date.
- EM settings: GET omits false fields (absent == false); PATCH with updateMask.
"""

import re
import time
from urllib.parse import urlencode

API = "https://analyticsadmin.googleapis.com"
PROVIDER = "google"

AUTH_HINT = (
    "Not signed in. Setup: set GA4DEPLOY_GOOGLE_CLIENT_ID / GA4DEPLOY_GOOGLE_CLIENT_SECRET "
    "in .env (Google Cloud Desktop OAuth client, GA4 Admin API enabled, analytics.edit scope, "
    "app published to Production), then run: hermes auth add ga4deploy:google"
)


class NotSignedIn(RuntimeError):
    pass


def _api(method, path, params=None, body=None, retries=3):
    """One GA4 Admin API call through Hermes-owned credentials (rule 11)."""
    from hermes_cli.plugin_provider_requests import (  # documented public helper
        ProviderNotSignedIn,
        credentialed_provider_request,
    )

    url = f"{API}/{path.lstrip('/')}"
    if params:
        url += "?" + urlencode({k: v for k, v in params.items() if v not in (None, "")})
    last = None
    for attempt in range(retries):
        try:
            resp = credentialed_provider_request(PROVIDER, method, url, json=body, timeout=60)
        except ProviderNotSignedIn as exc:
            raise NotSignedIn(f"{AUTH_HINT} ({exc})")
        if resp.status < 300:
            try:
                data = resp.json()
            except Exception:
                return {"raw": (resp.text or "")[:500]}
            return data if isinstance(data, dict) else {"raw": data}
        text = (resp.text or "")[:400]
        if resp.status == 401:
            raise NotSignedIn(
                f"401 from GA4 Admin API — try: hermes auth refresh ga4deploy:google. {text[:150]}")
        last = f"HTTP {resp.status}: {text}"
        if resp.status in (429, 500, 503):
            time.sleep(5 * (attempt + 1))
            continue
        raise RuntimeError(last)
    raise RuntimeError(f"failed after {retries} attempts: {last}")


# ---------------------------------------------------------------- discovery

def list_accounts():
    out, token = [], None
    while True:
        data = _api("GET", "v1beta/accounts", params={"pageSize": 200, "pageToken": token})
        out += data.get("accounts", [])
        token = data.get("nextPageToken")
        if not token:
            return out


def list_properties(account_id):
    acct = re.sub(r"^accounts/", "", str(account_id))
    data = _api("GET", "v1beta/properties",
                params={"filter": f"parent:accounts/{acct}", "pageSize": 200})
    return data.get("properties", [])


def list_streams(prop):
    p = _prop(prop)
    return _api("GET", f"v1alpha/{p}/dataStreams").get("dataStreams", [])


def _prop(prop):
    pid = str(prop)
    return pid if pid.startswith("properties/") else f"properties/{pid}"


def status():
    try:
        accts = list_accounts()
    except NotSignedIn as exc:
        return {"authed": False, "hint": str(exc)}
    return {
        "authed": True,
        "account_count": len(accts),
        "accounts": [{"name": a.get("name"), "displayName": a.get("displayName")} for a in accts[:50]],
    }


# ------------------------------------------------------- channel groupings

FIELD_MAP = {
    "sessionSource": "eachScopeSource",
    "sessionMedium": "eachScopeMedium",
    "sessionSourceMedium": "eachScopeSourceMedium",
    "sessionCampaignName": "eachScopeCampaignName",
    "sessionDefaultChannelGroup": "eachScopeDefaultChannelGroup",
    "source": "eachScopeSource",
    "medium": "eachScopeMedium",
    "sourceMedium": "eachScopeSourceMedium",
    "campaignName": "eachScopeCampaignName",
    "defaultChannelGroup": "eachScopeDefaultChannelGroup",
}

MATCH_MAP = {
    "FULL_REGEX": "FULL_REGEXP",
    "FULL_REGEXP": "FULL_REGEXP",
    "REGEX_CONTAINS": "PARTIAL_REGEXP",
    "PARTIAL_REGEXP": "PARTIAL_REGEXP",
    "EXACTLY_MATCHES": "EXACT",
    "EXACT": "EXACT",
    "CONTAINS": "CONTAINS",
    "BEGINS_WITH": "BEGINS_WITH",
    "ENDS_WITH": "ENDS_WITH",
}

_RE2_META = set(r".^$*+?()[]{}|\-")


def _re2_escape(value):
    """Escape RE2 metacharacters only (Python's re.escape adds spaces etc.)."""
    return "".join("\\" + ch if ch in _RE2_META else ch for ch in str(value))


def _to_filter(cond):
    mt = str(cond.get("match_type", "")).upper()
    field = FIELD_MAP.get(cond.get("dimension", ""), cond.get("dimension", ""))
    if mt == "IN_LIST":
        # NEVER inListFilter: saves 200 but renders BLANK in the GA4 UI.
        # Anchored FULL_REGEXP alternation is the working equivalent.
        values = cond.get("expression") or cond.get("values") or []
        if not isinstance(values, list) or not values:
            raise ValueError(f"IN_LIST needs a non-empty expression list: {cond}")
        expr = "^(?:" + "|".join(_re2_escape(v) for v in values) + ")$"
        return {"filter": {"fieldName": field,
                           "stringFilter": {"matchType": "FULL_REGEXP", "value": expr}}}
    if mt not in MATCH_MAP:
        raise ValueError(f"unknown match_type {mt!r} — use one of {sorted(set(MATCH_MAP))}")
    expr = str(cond.get("expression", ""))
    if expr.startswith("(?i)"):
        expr = expr[4:]  # API string filters are already case-insensitive
    return {"filter": {"fieldName": field,
                       "stringFilter": {"matchType": MATCH_MAP[mt], "value": expr}}}


def _dnf_to_cnf(condition_groups):
    """[{conditions:[...]}, ...] (OR of ANDs) -> list of OR-lists (AND of ORs)."""
    cnf = [[]]
    for clause in condition_groups or []:
        conds = clause.get("conditions") or []
        if not conds:
            continue
        cnf = [g + [c] for g in cnf for c in conds]
    return cnf


def _build_expression(rule):
    cnf = _dnf_to_cnf(rule.get("conditionGroups"))
    if not cnf or not cnf[0]:
        # catch-all (e.g. "Other"): match every session
        cnf = [[{"dimension": "sessionSource", "match_type": "FULL_REGEX", "expression": ".*"}]]
    and_group = [{"orGroup": {"filterExpressions": [_to_filter(c) for c in or_list]}}
                 for or_list in cnf]
    return {"andGroup": {"filterExpressions": and_group}}


def _summarize_rule(rule):
    top = rule.get("expression", {}).get("andGroup", {}).get("filterExpressions", [])
    parts = []
    for og in top:
        descs = []
        for f in og.get("orGroup", {}).get("filterExpressions", []):
            flt = f.get("filter", {})
            if "inListFilter" in flt:
                descs.append(f"{flt.get('fieldName')}:IN[...]")
            else:
                sf = flt.get("stringFilter", {})
                descs.append(f"{flt.get('fieldName')}:{sf.get('matchType')}={str(sf.get('value'))[:40]}")
        parts.append("(" + " OR ".join(descs) + ")")
    return " AND ".join(parts)


def _convert_grouping(spec):
    rules = sorted(spec.get("groupRules") or [], key=lambda r: r.get("order", 0))
    if not rules:
        raise ValueError("groupRules is empty")
    if len(rules) > 50:
        raise ValueError(f"{len(rules)} rules — API max is 50")
    body = {
        "displayName": str(spec.get("displayName", ""))[:80],
        "description": str(spec.get("description", ""))[:256],
        "groupingRule": [{"displayName": r["displayName"], "expression": _build_expression(r)}
                         for r in rules],
    }
    if spec.get("primary"):
        body["primary"] = True
    return body


def channel_groupings_list(prop, inspect_default=False):
    p = _prop(prop)
    groups = _api("GET", f"v1alpha/{p}/channelGroups").get("channelGroups", [])
    out = []
    for g in groups:
        entry = {
            "name": g.get("name"),
            "displayName": g.get("displayName"),
            "systemDefined": bool(g.get("systemDefined")),
            "primary": bool(g.get("primary")),
            "rule_count": len(g.get("groupingRule") or []),
        }
        if inspect_default and g.get("systemDefined"):
            entry["rules"] = [{"channel": r.get("displayName"), "when": _summarize_rule(r)}
                              for r in g.get("groupingRule") or []]
        out.append(entry)
    return {"property": p, "custom_count": sum(1 for g in groups if not g.get("systemDefined")),
            "groupings": out,
            "note": "GA4 hard limit: 2 custom groupings per property. There is NO delete endpoint — "
                    "to replace one, PATCH it in place with the new displayName + rules."}


def channel_groupings_deploy(prop, groupings, dry_run=False):
    p = _prop(prop)
    if not isinstance(groupings, list) or not groupings:
        raise ValueError("groupings must be a non-empty list of specs")
    existing = _api("GET", f"v1alpha/{p}/channelGroups").get("channelGroups", [])
    customs = {g["displayName"]: g["name"] for g in existing if not g.get("systemDefined")}

    bodies = [_convert_grouping(s) for s in groupings]
    new_names = {b["displayName"] for b in bodies if b["displayName"] not in customs}
    if len(customs) + len(new_names) > 2:
        raise ValueError(
            f"would leave {len(customs) + len(new_names)} custom groupings — GA4 allows max 2 "
            f"(existing: {sorted(customs)}). PATCH an existing one in place instead.")

    actions, plan = [], []
    for body in bodies:
        dn = body["displayName"]
        if dn in customs:
            plan.append({"action": "PATCH", "target": customs[dn], "displayName": dn,
                         "rules": len(body["groupingRule"]),
                         "summary": [_summarize_rule({"expression": e}) for e in
                                     (r["expression"] for r in body["groupingRule"])][:50]})
            if not dry_run:
                res = _api("PATCH", f"v1alpha/{customs[dn]}", body=body,
                           params={"updateMask": "displayName,description,groupingRule"})
                actions.append({"action": "PATCH", "displayName": dn, "name": res.get("name"), "ok": True})
        else:
            plan.append({"action": "CREATE", "displayName": dn, "rules": len(body["groupingRule"]),
                         "summary": [_summarize_rule({"expression": e}) for e in
                                     (r["expression"] for r in body["groupingRule"])][:50]})
            if not dry_run:
                res = _api("POST", f"v1alpha/{p}/channelGroups", body=body)
                actions.append({"action": "CREATE", "displayName": dn, "name": res.get("name"), "ok": True})
    result = {"property": p, "dry_run": dry_run, "plan": plan}
    if not dry_run:
        verify = channel_groupings_list(p)
        result["actions"] = actions
        result["verify_custom_count"] = verify["custom_count"]
        result["verify"] = [{"displayName": g["displayName"], "rules": g["rule_count"]}
                            for g in verify["groupings"] if not g["systemDefined"]]
    return result


# --------------------------------------------------------------- audiences

SCOPE_MAP = {
    "across_all_sessions": "AUDIENCE_FILTER_SCOPE_ACROSS_ALL_SESSIONS",
    "within_same_session": "AUDIENCE_FILTER_SCOPE_WITHIN_SAME_SESSION",
    "within_same_event": "AUDIENCE_FILTER_SCOPE_WITHIN_SAME_EVENT",
}

BAD_DIMENSIONS = {
    "pagePath": "pageLocation",
    "page_location": "pageLocation",
    "page": "pageLocation",
}


def _audience_filter(f):
    kind = str(f.get("type", "")).lower()
    if kind == "event":
        return {"eventFilter": {"eventName": f["name"]}}
    if kind == "dimension":
        field = f.get("field", "")
        if field in BAD_DIMENSIONS:
            raise ValueError(f"dimension {field!r} is rejected by the audiences API — "
                             f"use {BAD_DIMENSIONS[field]!r}")
        df = {"fieldName": field,
              "stringFilter": {"matchType": MATCH_MAP.get(str(f.get("match", "CONTAINS")).upper(), "CONTAINS"),
                               "value": str(f.get("value", ""))}}
        if f.get("at_any_point"):
            df["atAnyPointInTime"] = True
        return {"dimensionOrMetricFilter": df}
    raise ValueError(f"filter type must be 'event' or 'dimension', got {kind!r}")


def _audience_clause(c):
    scope = SCOPE_MAP.get(str(c.get("scope", "across_all_sessions")).lower())
    if not scope:
        raise ValueError(f"scope must be one of {sorted(SCOPE_MAP)} "
                         f"(ACROSS_ALL_EVENTS does not exist — use within_same_session)")
    exprs = [_audience_filter(f) for f in c.get("filters") or []]
    if not exprs:
        raise ValueError("clause has no filters")
    # andGroup may ONLY contain orGroup wrappers — bare filters are rejected.
    or_wrapped = [{"orGroup": {"filterExpressions": [e]}} for e in exprs]
    return {"clauseType": str(c.get("clauseType", "INCLUDE")).upper(),
            "simpleFilter": {"scope": scope,
                             "filterExpression": {"andGroup": {"filterExpressions": or_wrapped}}}}


def _convert_audience(spec):
    desc = str(spec.get("description", ""))
    if len(desc) > 90:
        raise ValueError(f"description is {len(desc)} chars — API rejects >=100; keep under 90")
    days = str(spec.get("membershipDurationDays", 30))
    if not days.isdigit() or not (1 <= int(days) <= 540):
        raise ValueError("membershipDurationDays must be an integer 1..540")
    clauses = [_audience_clause(c) for c in spec.get("clauses") or []]
    if not clauses:
        raise ValueError("audience has no clauses")
    return {"displayName": str(spec.get("displayName", ""))[:255],
            "description": desc,
            "membershipDurationDays": days,
            "filterClauses": clauses}


def audiences_list(prop):
    p = _prop(prop)
    auds = _api("GET", f"v1alpha/{p}/audiences").get("audiences", [])
    return {"property": p, "count": len(auds),
            "audiences": [{"name": a.get("name"), "displayName": a.get("displayName"),
                           "membershipDurationDays": a.get("membershipDurationDays"),
                           "description": a.get("description", "")} for a in auds],
            "note": "filterClauses are IMMUTABLE — a wrong audience must be archived and rebuilt."}


def audiences_deploy(prop, audiences, dry_run=False):
    p = _prop(prop)
    existing = {a["displayName"] for a in _api("GET", f"v1alpha/{p}/audiences").get("audiences", [])}
    actions = []
    for spec in audiences or []:
        body = _convert_audience(spec)
        dn = body["displayName"]
        if dn in existing:
            actions.append({"action": "SKIP", "displayName": dn, "reason": "already exists"})
            continue
        if dry_run:
            actions.append({"action": "CREATE", "displayName": dn, "dry_run": True,
                            "clauses": len(body["filterClauses"])})
            continue
        res = _api("POST", f"v1alpha/{p}/audiences", body=body)
        actions.append({"action": "CREATE", "displayName": dn, "name": res.get("name"), "ok": True})
    return {"property": p, "dry_run": dry_run, "actions": actions}


def audiences_archive(prop, audience_name):
    p = _prop(prop)
    name = str(audience_name)
    if not name.startswith("properties/"):
        name = f"{p}/audiences/{name}"
    _api("POST", f"v1alpha/{name}:archive")
    remaining = audiences_list(p)
    return {"archived": name, "remaining_count": remaining["count"],
            "note": "archive is reversible only by rebuilding — there is no unarchive"}


# ------------------------------------------------------------- annotations

COLORS = {"RED", "BLUE", "YELLOW", "GREEN"}


def _gdate(iso):
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(iso).strip())
    if not m:
        raise ValueError(f"date must be YYYY-MM-DD, got {iso!r}")
    y, mo, d = (int(x) for x in m.groups())
    return {"year": y, "month": mo, "day": d}


def _convert_annotation(a):
    color = str(a.get("color", "BLUE")).upper()
    if color not in COLORS:
        raise ValueError(f"color {color!r} rejected — API enum is {sorted(COLORS)} "
                         f"(lowercase and ORANGE/purple/pink/grey all fail)")
    desc = str(a.get("description", ""))
    if len(desc) > 150:
        raise ValueError(f"description is {len(desc)} chars — API max is 150")
    title = str(a.get("title", "")).strip()
    if not title:
        raise ValueError("annotation title is required")
    body = {"title": title[:255], "color": color}
    if desc:
        body["description"] = desc
    if a.get("date"):
        body["annotationDate"] = _gdate(a["date"])
    elif a.get("start") and a.get("end"):
        body["annotationDateRange"] = {"startDate": _gdate(a["start"]), "endDate": _gdate(a["end"])}
    else:
        raise ValueError("annotation needs either 'date' or both 'start' and 'end' (YYYY-MM-DD)")
    return body


def annotations_list(prop):
    p = _prop(prop)
    anns = _api("GET", f"v1alpha/{p}/reportingDataAnnotations").get("reportingDataAnnotations", [])
    out = []
    for a in anns:
        d = a.get("annotationDate") or a.get("annotationDateRange", {}).get("startDate") or {}
        out.append({"name": a.get("name"), "title": a.get("title"),
                    "date": f"{d.get('year','')}-{d.get('month','')}-{d.get('day','')}" if d else "",
                    "color": a.get("color")})
    return {"property": p, "count": len(out), "annotations": out}


def annotations_create(prop, annotations, dry_run=False):
    p = _prop(prop)
    existing = set()
    for a in _api("GET", f"v1alpha/{p}/reportingDataAnnotations").get("reportingDataAnnotations", []):
        d = a.get("annotationDate") or a.get("annotationDateRange", {}).get("startDate") or {}
        existing.add((a.get("title"), (d.get("year"), d.get("month"), d.get("day"))))
    actions = []
    for spec in annotations or []:
        body = _convert_annotation(spec)
        d = body.get("annotationDate") or body.get("annotationDateRange", {}).get("startDate")
        key = (body["title"], (d.get("year"), d.get("month"), d.get("day")))
        if key in existing:
            actions.append({"action": "SKIP", "title": body["title"], "reason": "duplicate title+date"})
            continue
        if dry_run:
            actions.append({"action": "CREATE", "title": body["title"], "dry_run": True})
            continue
        res = _api("POST", f"v1alpha/{p}/reportingDataAnnotations", body=body)
        actions.append({"action": "CREATE", "title": body["title"], "name": res.get("name"), "ok": True})
    return {"property": p, "dry_run": dry_run, "actions": actions}


# ----------------------------------------------------- enhanced measurement

EM_BOOL_FIELDS = {
    "pageViewsEnabled", "scrollsEnabled", "outboundClicksEnabled", "siteSearchEnabled",
    "videoStartEnabled", "videoProgressEnabled", "videoCompleteEnabled",
    "fileDownloadsEnabled", "formInteractionsEnabled",
}
EM_STRING_FIELDS = {"searchQueryParameter", "uriQueryParameter", "uriSearchQueryParameter"}
EM_FIELDS = EM_BOOL_FIELDS | EM_STRING_FIELDS


def em_get(prop, stream=None):
    p = _prop(prop)
    streams = list_streams(p)
    web = [s for s in streams if s.get("type") == "WEB_STREAM"]
    if stream:
        sid = str(stream)
        web = [s for s in streams if sid in (s.get("name", ""), s.get("webStreamData", {}).get("measurementId", ""))]
        if not web:
            raise ValueError(f"no stream matching {stream!r} in {p}")
    out = []
    for s in web:
        sname = s.get("name", "")
        settings = _api("GET", f"v1alpha/{sname}/enhancedMeasurementSettings")
        out.append({
            "stream": sname,
            "measurementId": s.get("webStreamData", {}).get("measurementId"),
            "settings": settings,
            "note": "GET OMITS false fields — absent means disabled, not unknown",
        })
    return {"property": p, "streams": out}


def em_set(prop, stream, settings):
    p = _prop(prop)
    bad = set(settings) - EM_FIELDS
    if bad:
        raise ValueError(f"unknown EM fields {sorted(bad)} — valid: {sorted(EM_FIELDS)}")
    if not settings:
        raise ValueError("settings is empty")
    sid = str(stream)
    if sid.startswith("properties/"):
        sname = sid
    else:
        streams = list_streams(p)
        match = [s for s in streams
                 if sid in (s.get("name", ""), s.get("webStreamData", {}).get("measurementId", ""))]
        if not match:
            raise ValueError(f"no stream matching {sid!r} in {p}")
        sname = match[0]["name"]
    mask = ",".join(sorted(settings))
    res = _api("PATCH", f"v1alpha/{sname}/enhancedMeasurementSettings",
               params={"updateMask": mask}, body=dict(settings))
    return {"stream": sname, "updated": sorted(settings), "settings_after": res,
            "note": "false values must be sent explicitly; GET never shows them"}
