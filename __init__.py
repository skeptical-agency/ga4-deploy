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


def register(ctx):
    for name, schema in SCHEMAS.items():
        ctx.register_tool(
            name=name,
            toolset="ga4deploy",
            schema=schema,
            handler=HANDLERS[name][0],
            description=TOOL_DESCRIPTIONS.get(name, name),
        )

    # Bundled skill(s)
    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.exists():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
