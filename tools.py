"""Tool handlers — thin JSON wrappers over the ga4 engine."""

import json

from . import ga4
from .schemas import SCHEMAS


def _ok(payload):
    return json.dumps(payload, default=str)


def _fail(exc):
    return _ok({"error": str(exc)[:600]})


def status(args, ctx=None):
    try:
        return _ok(ga4.status())
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def discover(args, ctx=None):
    try:
        level = args.get("level", "accounts")
        if level == "accounts":
            accts = ga4.list_accounts()
            return _ok({"level": level, "count": len(accts),
                        "accounts": [{"name": a.get("name"), "displayName": a.get("displayName")}
                                     for a in accts]})
        if level == "properties":
            if not args.get("account"):
                return _ok({"error": "level=properties needs 'account'"})
            props = ga4.list_properties(args["account"])
            return _ok({"level": level, "count": len(props),
                        "properties": [{"name": p.get("name"), "displayName": p.get("displayName"),
                                         "propertyType": p.get("propertyType"),
                                         "timeZone": p.get("timeZone"),
                                         "currencyCode": p.get("currencyCode")} for p in props]})
        if level == "streams":
            if not args.get("property"):
                return _ok({"error": "level=streams needs 'property'"})
            streams = ga4.list_streams(args["property"])
            return _ok({"level": level, "count": len(streams),
                        "streams": [{"name": s.get("name"), "type": s.get("type"),
                                      "displayName": s.get("displayName"),
                                      "measurementId": s.get("webStreamData", {}).get("measurementId"),
                                      "defaultUri": s.get("webStreamData", {}).get("defaultUri")}
                                     for s in streams]})
        return _ok({"error": f"unknown level {level!r}"})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def channel_groupings(args, ctx=None):
    try:
        mode = args.get("mode", "list")
        prop = args.get("property")
        if not prop:
            return _ok({"error": "'property' is required"})
        if mode == "list":
            return _ok(ga4.channel_groupings_list(prop))
        if mode == "inspect_default":
            return _ok(ga4.channel_groupings_list(prop, inspect_default=True))
        if mode == "deploy":
            return _ok(ga4.channel_groupings_deploy(prop, args.get("groupings") or [],
                                                     dry_run=bool(args.get("dry_run"))))
        return _ok({"error": f"unknown mode {mode!r}"})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def audiences(args, ctx=None):
    try:
        mode = args.get("mode", "list")
        prop = args.get("property")
        if not prop:
            return _ok({"error": "'property' is required"})
        if mode == "list":
            return _ok(ga4.audiences_list(prop))
        if mode == "deploy":
            return _ok(ga4.audiences_deploy(prop, args.get("audiences") or [],
                                             dry_run=bool(args.get("dry_run"))))
        if mode == "archive":
            if not args.get("audience_name"):
                return _ok({"error": "mode=archive needs 'audience_name'"})
            return _ok(ga4.audiences_archive(prop, args["audience_name"]))
        return _ok({"error": f"unknown mode {mode!r}"})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def annotations(args, ctx=None):
    try:
        mode = args.get("mode", "list")
        prop = args.get("property")
        if not prop:
            return _ok({"error": "'property' is required"})
        if mode == "list":
            return _ok(ga4.annotations_list(prop))
        if mode == "create":
            return _ok(ga4.annotations_create(prop, args.get("annotations") or [],
                                               dry_run=bool(args.get("dry_run"))))
        return _ok({"error": f"unknown mode {mode!r}"})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def enhanced_measurement(args, ctx=None):
    try:
        mode = args.get("mode", "get")
        prop = args.get("property")
        if not prop:
            return _ok({"error": "'property' is required"})
        if mode == "get":
            return _ok(ga4.em_get(prop, stream=args.get("stream")))
        if mode == "set":
            if not args.get("stream") or not args.get("settings"):
                return _ok({"error": "mode=set needs 'stream' and 'settings'"})
            return _ok(ga4.em_set(prop, args["stream"], args["settings"]))
        return _ok({"error": f"unknown mode {mode!r}"})
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


HANDLERS = {
    "ga4_status": (status, SCHEMAS["ga4_status"]),
    "ga4_discover": (discover, SCHEMAS["ga4_discover"]),
    "ga4_channel_groupings": (channel_groupings, SCHEMAS["ga4_channel_groupings"]),
    "ga4_audiences": (audiences, SCHEMAS["ga4_audiences"]),
    "ga4_annotations": (annotations, SCHEMAS["ga4_annotations"]),
    "ga4_enhanced_measurement": (enhanced_measurement, SCHEMAS["ga4_enhanced_measurement"]),
}
