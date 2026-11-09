"""LLM-facing schemas for GA4 Deploy tools."""

_CONDITION = {
    "type": "object",
    "properties": {
        "dimension": {"type": "string",
                       "description": "sessionSource, sessionMedium, sessionSourceMedium, "
                                      "sessionCampaignName, sessionDefaultChannelGroup (mapped to "
                                      "the eachScope* names the v1alpha API actually requires)"},
        "match_type": {"type": "string",
                        "enum": ["FULL_REGEX", "REGEX_CONTAINS", "EXACTLY_MATCHES",
                                  "CONTAINS", "BEGINS_WITH", "ENDS_WITH", "IN_LIST"],
                        "description": "IN_LIST is auto-converted to anchored FULL_REGEXP "
                                       "alternation (inListFilter renders BLANK in the GA4 UI)"},
        "expression": {"type": ["string", "array"],
                        "description": "string for regex/text matches; array of values for IN_LIST"},
    },
    "required": ["dimension", "match_type", "expression"],
}

_GROUPING_SPEC = {
    "type": "object",
    "properties": {
        "displayName": {"type": "string", "description": "<=80 chars"},
        "description": {"type": "string", "description": "<=256 chars"},
        "primary": {"type": "boolean", "description": "make this the property's default grouping"},
        "groupRules": {
            "type": "array",
            "description": "max 50 rules; evaluated top-down by 'order'; first match wins. "
                           "End with an empty-conditions catch-all rule (Other).",
            "items": {
                "type": "object",
                "properties": {
                    "displayName": {"type": "string"},
                    "order": {"type": "integer"},
                    "conditionGroups": {
                        "type": "array",
                        "description": "DNF: rule matches if ANY conditionGroup matches; each "
                                       "group is an AND of conditions. Distributed to CNF "
                                       "automatically. Omit entirely for a catch-all.",
                        "items": {
                            "type": "object",
                            "properties": {"conditions": {"type": "array", "items": _CONDITION}},
                            "required": ["conditions"],
                        },
                    },
                },
                "required": ["displayName", "order"],
            },
        },
    },
    "required": ["displayName", "groupRules"],
}

_AUDIENCE_SPEC = {
    "type": "object",
    "properties": {
        "displayName": {"type": "string"},
        "description": {"type": "string", "description": "<90 chars (API rejects >=100)"},
        "membershipDurationDays": {"type": "integer", "description": "1..540"},
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clauseType": {"type": "string", "enum": ["INCLUDE", "EXCLUDE"]},
                    "scope": {"type": "string",
                               "enum": ["across_all_sessions", "within_same_session", "within_same_event"],
                               "description": "ACROSS_ALL_EVENTS does not exist; use within_same_session"},
                    "filters": {
                        "type": "array",
                        "description": "ANDed inside the clause. pagePath is rejected by the API — "
                                       "use pageLocation.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["event", "dimension"]},
                                "name": {"type": "string", "description": "event name (type=event)"},
                                "field": {"type": "string", "description": "dimension (type=dimension)"},
                                "match": {"type": "string", "description": "CONTAINS/EXACT/BEGINS_WITH/... default CONTAINS"},
                                "value": {"type": "string"},
                                "at_any_point": {"type": "boolean",
                                                  "description": "dimension matched at any point in time"},
                            },
                            "required": ["type"],
                        },
                    },
                },
                "required": ["filters"],
            },
        },
    },
    "required": ["displayName", "description", "clauses"],
}

_ANNOTATION = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string", "description": "<=150 chars (API max)"},
        "color": {"type": "string", "enum": ["RED", "BLUE", "YELLOW", "GREEN"],
                   "description": "uppercase only; ORANGE/purple/pink/grey are rejected"},
        "date": {"type": "string", "description": "YYYY-MM-DD (single-day annotation)"},
        "start": {"type": "string", "description": "YYYY-MM-DD (range start, with 'end')"},
        "end": {"type": "string", "description": "YYYY-MM-DD (range end)"},
    },
    "required": ["title"],
}

SCHEMAS = {
    "ga4_status": {
        "type": "object",
        "properties": {},
        "description": "Check GA4 Admin API auth and list accessible accounts.",
    },
    "ga4_discover": {
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": ["accounts", "properties", "streams"],
                       "description": "accounts: all GA4 accounts. properties: properties under "
                                      "'account'. streams: data streams of 'property'."},
            "account": {"type": "string", "description": "account id or accounts/NNN (level=properties)"},
            "property": {"type": "string", "description": "property id or properties/NNN (level=streams)"},
        },
        "required": ["level"],
    },
    "ga4_channel_groupings": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["list", "inspect_default", "deploy"],
                      "description": "list: existing groupings + custom count. inspect_default: dump "
                                     "the system Default Group's rules as readable expressions (the "
                                     "base to override). deploy: create/PATCH from specs."},
            "property": {"type": "string", "description": "GA4 property id (e.g. 506448290)"},
            "groupings": {"type": "array", "items": _GROUPING_SPEC,
                           "description": "mode=deploy. Max 2 custom groupings exist per property — "
                                          "the tool refuses to exceed the cap; PATCH in place instead."},
            "dry_run": {"type": "boolean", "description": "plan + rule summaries without writing"},
        },
        "required": ["mode", "property"],
    },
    "ga4_audiences": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["list", "deploy", "archive"]},
            "property": {"type": "string"},
            "audiences": {"type": "array", "items": _AUDIENCE_SPEC,
                           "description": "mode=deploy. Existing displayName is skipped (filterClauses "
                                          "are immutable — edits need archive + rebuild)."},
            "audience_name": {"type": "string",
                                "description": "mode=archive: audience resource name or bare id"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["mode", "property"],
    },
    "ga4_annotations": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["list", "create"]},
            "property": {"type": "string"},
            "annotations": {"type": "array", "items": _ANNOTATION,
                              "description": "mode=create. Deduped by title+date against existing."},
            "dry_run": {"type": "boolean"},
        },
        "required": ["mode", "property"],
    },
    "ga4_enhanced_measurement": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["get", "set"]},
            "property": {"type": "string"},
            "stream": {"type": "string",
                        "description": "measurement id (G-XXXX), stream id, or full resource name. "
                                       "mode=get without it lists every WEB stream."},
            "settings": {
                "type": "object",
                "description": "mode=set. Subset of: pageViewsEnabled, scrollsEnabled, "
                               "outboundClicksEnabled, siteSearchEnabled, videoStartEnabled, "
                               "videoProgressEnabled, videoCompleteEnabled, fileDownloadsEnabled, "
                               "formInteractionsEnabled, searchQueryParameter, uriQueryParameter, "
                               "uriSearchQueryParameter. Send false explicitly — GET omits false.",
            },
        },
        "required": ["mode", "property"],
    },
}
