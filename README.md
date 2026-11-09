# GA4 Deploy

Script the GA4 Admin API from Hermes Agent: channel groupings, audiences,
reporting annotations and enhanced measurement — with every production quirk
enforced in code, deployed through your own Google OAuth.

Distilled from live fleet deploys across a 27-account marketing agency, where
the official docs were wrong often enough to cost real hours.

| Tool | What it does |
|---|---|
| `ga4_status` | Auth check + accessible accounts |
| `ga4_discover` | Walk accounts → properties → data streams |
| `ga4_channel_groupings` | list / inspect the system Default Group's rules / deploy specs (DNF → CNF auto-distributed, IN_LIST converted to anchored regex, 2-grouping cap enforced, PATCH-in-place, read-back verified) |
| `ga4_audiences` | list / deploy (skip-by-name idempotency) / archive (immutable filterClauses handled) |
| `ga4_annotations` | list / batch create (color enum + 150-char cap + title/date dedupe) |
| `ga4_enhanced_measurement` | get / set per web stream (updateMask built for you, absent=false semantics documented) |

## Why a plugin and not a prompt

The GA4 Admin API's documentation does not tell you:

- channel groups / audiences / annotations / EM settings live under **v1alpha**
  (the v1beta resources return raw HTML 404s);
- channel-group filters are rejected unless fields are named `eachScope*`;
- `inListFilter` **saves with HTTP 200 and then renders blank in the UI** —
  the only working form is anchored `FULL_REGEXP` alternation;
- a property can hold **at most 2 custom channel groupings** and there is **no
  delete endpoint** (replacement means PATCH-in-place);
- audience `filterClauses` are **immutable**, `andGroup` only accepts
  `orGroup` wrappers, and `pagePath` is rejected while `pageLocation` works;
- annotation `color` is an uppercase enum (lowercase and `ORANGE` fail);
- enhanced-measurement GET **omits false fields**, so "absent" means disabled.

Every one of those traps is encoded here as a validation, a conversion, or a
refusal with the fix in the error message. Specs go in as readable DNF; the
engine does the CNF distribution, field mapping, cap checks, idempotency and
post-write read-back.

## Setup (once, two minutes)

1. Google Cloud Console → create/reuse a project → enable the
   **Google Analytics Admin API** → create an **OAuth client (Desktop app)** →
   publish the OAuth consent screen to Production.
2. Put the pair in your Hermes `.env`:
   ```
   GA4DEPLOY_GOOGLE_CLIENT_ID=...
   GA4DEPLOY_GOOGLE_CLIENT_SECRET=***
   ```
3. Sign in (scopes: `analytics.edit` + `analytics.readonly`):
   ```
   hermes auth add ga4deploy:google
   ```

Hermes owns and refreshes the token — the plugin never sees it.

## Install

```
hermes plugins install skeptical-agency/ga4-deploy --enable
```

Then ask your agent things like:

- "show me the properties under account 123456 and their web streams"
- "dump the Default Group rules on property 506448290 so we can see what to override"
- "deploy this channel grouping spec to properties 111 and 222, dry-run first"
- "create 7-day and 30-day website-visitor audiences on the Summit property"
- "annotate the site relaunch on 2026-10-01 in blue across the whole fleet"
- "turn off file downloads enhanced measurement on G-XXXX"

## Disclosure

- All calls are plain REST to `analyticsadmin.googleapis.com` /
  `www.googleapis.com` through Hermes-owned OAuth (`credentialed_provider_request`).
  The plugin stores no tokens, keys or state.
- Write operations (deploy/create/set/archive) change live GA4 configuration
  for the authenticated user's properties. Every write path supports
  `dry_run`, and the bundled skill instructs the agent to dry-run and show
  the plan first.
- Reads are quota-free; writes count against the GA4 Admin API quota of the
  user's own Google Cloud project.

Built by [Skeptical Agency](https://skeptical.agency). MIT licensed.
