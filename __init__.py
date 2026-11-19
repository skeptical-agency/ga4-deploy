"""GA4 Deploy — plugin registration."""

from pathlib import Path

from .schemas import SCHEMAS
from .tools import HANDLERS

TOOL_DESCRIPTIONS = {
    "ga4_status": "Check GA4 Admin API auth and list accessible accounts",
    "ga4_discover": "Walk GA4 accounts -> properties -> data streams",
    "ga4_channel_groupings": "List/inspect-default/deploy custom channel groupings (DNF specs, "
                              "inList-safe, 2-cap enforced, read-back verified)",
    "ga4_audiences": "List/deploy/archive GA4 audiences (immutable-clause safe, dedup by name)",
    "ga4_annotations": "List/create reporting annotations (color enum + 150-char + dedupe enforced)",
    "ga4_enhanced_measurement": "Get/set enhanced measurement toggles per web stream (updateMask built, "
                                 "absent=false documented)",
}

# tool name -> modes that mutate the GA4 property. Everything else (list/get/
# inspect_default) and every dry_run call passes through without approval.
LIVE_WRITE_MODES = {
    "ga4_channel_groupings": {"deploy"},
    "ga4_audiences": {"deploy", "archive"},
    "ga4_annotations": {"create"},
    "ga4_enhanced_measurement": {"set"},
}


def _on_pre_tool_call(tool_name="", args=None, **kwargs):
    """Escalate every live (non-dry-run) GA4 write to Hermes's human-approval gate.

    Returns ``{"action": "approve", ...}`` so the call requires explicit user
    approval; returns None for reads and dry runs. Never raises.
    """
    try:
        modes = LIVE_WRITE_MODES.get(tool_name)
        if not modes or not isinstance(args, dict):
            return None
        mode = str(args.get("mode", ""))
        if mode not in modes:
            return None
        # archive has no dry_run — it always mutates. Other writes honour dry_run.
        if mode != "archive" and args.get("dry_run"):
            return None
        prop = args.get("property") or "?"
        message = ("LIVE WRITE: {tool} mode={mode} will modify GA4 property {prop}. "
                   "This is NOT a dry run — human approval required."
                   ).format(tool=tool_name, mode=mode, prop=prop)
        return {
            "action": "approve",
            "message": message,
            "rule_key": "ga4-deploy:{tool}:{mode}".format(tool=tool_name, mode=mode),
        }
    except Exception:  # noqa: BLE001 — a broken gate must not break the tool call path
        return None


def register(ctx):
    for name, schema in SCHEMAS.items():
        ctx.register_tool(
            name=name,
            toolset="ga4deploy",
            schema=schema,
            handler=HANDLERS[name][0],
            description=TOOL_DESCRIPTIONS.get(name, name),
        )

    ctx.register_hook("pre_tool_call", _on_pre_tool_call)

    # Bundled skill(s)
    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.exists():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
