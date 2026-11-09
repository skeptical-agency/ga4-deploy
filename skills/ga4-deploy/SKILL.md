---
name: ga4-deploy
description: Deploy GA4 Admin API configs (channel groupings, audiences, annotations, enhanced measurement) via the ga4-deploy plugin tools
---

# GA4 Deploy workflow

Spec-driven GA4 Admin API deploys. The tools encode every production quirk;
your job is to gather requirements, build specs, dry-run, then deploy.

## Order of operations

1. `ga4_status` — confirm auth (else walk the user through env vars +
   `hermes auth add ga4deploy:google`).
2. `ga4_discover` level=accounts → properties → streams to resolve IDs.
   Never guess a property id.
3. Build the spec. **Always dry_run=true first** and show the user the plan.
4. Deploy, then check the read-back the tool returns. If it disagrees with
   the spec, stop — do not retry blindly.

## Channel groupings

- Inspect the system default first (`mode=inspect_default`) when the user
  wants to "fix" attribution: most overrides are Default Group + 1-2 changed
  channels.
- Spec is DNF (OR of AND-groups); the tool distributes to CNF automatically.
- Order matters: rules evaluate top-down, first match wins. End with a
  catch-all rule (`conditionGroups` omitted) named "Other" or similar.
- Max 50 rules, max 2 custom groupings per property, and there is NO delete
  endpoint — the tool refuses cap violations; to replace, PATCH in place.
- `IN_LIST` is auto-converted to anchored regex alternation. Never try to
  hand-build `inListFilter` — it saves but renders blank in the UI.
- Regex is RE2, case-insensitive, unanchored unless FULL_REGEX (then anchor
  with ^...$ yourself). Values in IN_LIST lists are escaped automatically.
- UI verification after deploy: Admin → Data settings → Channel groups.
  Reporting attribution lags ~24-48h and applies to NEW sessions only.

## Audiences

- filterClauses are IMMUTABLE. Wrong audience = archive + rebuild, never edit.
- Deploy skips existing displayNames (idempotent).
- description must be <90 chars; membershipDurationDays 1..540.
- Dimensions: `pageLocation` works; `pagePath`/`page_location` are rejected —
  the tool errors with the correction instead of a 400.
- Scopes: across_all_sessions / within_same_session / within_same_event.
  ACROSS_ALL_EVENTS does not exist.

## Annotations

- color ∈ {RED, BLUE, YELLOW, GREEN} uppercase only. ORANGE and lowercase fail.
- description ≤150 chars. Single date or start+end range.
- Creation dedupes by title+date against existing — safe to re-run batches.

## Enhanced measurement

- GET omits false fields. Absent = disabled. Always send `false` explicitly
  when turning something off.
- set targets one stream (measurement id G-XXXX or resource name); the tool
  builds the updateMask from exactly the fields you pass.
- These are v1alpha endpoints — v1beta EM settings 404 as HTML.

## Fleet deploys

For the same config across N properties: loop properties, dry-run the whole
fleet first, then deploy sequentially. Rate limits are generous but the tool
already backs off on 429/5xx. Collect the per-property verify blocks into one
summary table for the user.

## Hard rules

- Never deploy without a dry-run unless the user explicitly says so.
- Never archive an audience without naming exactly what will be archived.
- Property ids come from ga4_discover, never from memory or chat text.
- If a write returns an error, report it verbatim — GA4 error strings carry
  the exact rejected field, which is the whole diagnosis.
