# M365 Graph Grounding (Work Mode / Work IQ)

**Date:** 2026-07-13
**Status:** Implemented.

## Correction during implementation

The original design (below) attributed grounding to the paid Copilot **scenario**
(`OfficeWebPaidCopilot` / `licenseType=Premium`). That turned out to be necessary but
**not sufficient** — it grounded only intermittently. Re-capturing the real Copilot UI
with **Work IQ enabled** revealed the actual switch: **Work mode**, i.e.
`agent=work` + `scenario=officeweb` in the WebSocket URL **plus** the enterprise
option-sets in the invoke payload (`bizchat_enable_federated_connectors`,
`enterprise_flux_work`, `enterprise_toolbox_with_skdsstore`, `enterprise_pagination_support`,
etc.) and the Chat-surface `clientInfo` fields. Replicating the full Work-mode request
grounded reliably (4/4 on calendar, plus email and file queries returning real data).

The implementation therefore replaces the `M365_SCENARIO` / `M365_LICENSE_TYPE`
settings with a single **`M365_WORK_MODE`** boolean (default `true`). Work mode sends
the grounding request; web mode falls back to `agent=web` / `OfficeWebIncludedCopilot`
with the consumer option-sets for accounts without a paid license. The sections below
are the original (superseded) design, kept for history.

---

## Summary

Enable the proxy to answer questions grounded in the user's Microsoft 365 data
(mail, calendar, files, Teams, people) by connecting to the substrate chathub as
the **paid/premium** Copilot scenario instead of the "included/starter" web-only
one. This is the foundation for querying M365 data; natural-language querying works
the moment it lands. Structured JSON output, an OpenCode agent tool, and a CLI query
command are deferred to their own follow-on specs.

## Motivation & validated finding

The proxy currently cannot see the user's M365 data. An empirical probe against the
running proxy confirmed it:

- "Do I have any meetings on my calendar today?" → *"I can't access your calendar."*
- Email / files probes → *"unread count unavailable"* / *"No, 0"*.

Diffing the request the proxy sends against the request the real (grounded) M365
Copilot web UI sends — captured live over CDP from the signed-in Edge session —
isolated the cause to two WebSocket URL parameters:

| Parameter | Proxy sends | Real grounded Copilot |
|---|---|---|
| `scenario` | `OfficeWebIncludedCopilot` | `OfficeWebPaidCopilot` |
| `licenseType` | `Starter` | `Premium` |
| `plugins` | `[BingWebSearch]` | `[BingWebSearch]` (identical) |

Graph grounding is **not** a plugin — the plugin list is identical. It is unlocked by
connecting as the paid Copilot scenario. This was validated end to end with a
throwaway script: the same token and query, changing only these two URL params,
turned *"I can't access your calendar."* into a real grounded answer (`"0"`). No
`clientInfo`, `optionsSets`, or payload changes were needed.

## Scope

**In scope:**
- Make the substrate `scenario` and `license_type` configurable, defaulting to the
  paid/premium values that enable grounding.
- Plumb them from settings through the client factory into `SubstrateCopilotClient._ws_url`.

**Out of scope (own follow-on specs):**
- Structured JSON output of results.
- OpenCode `query_m365` agent tool.
- CLI `query` command.
- Any per-request scenario switching or new endpoints.

## Design

**Guiding decision:** configurable via env vars, defaulting to the grounding
(paid/premium) values — grounding is the point of the feature and the user holds the
license, so it should work out of the box, while an override keeps the proxy usable
for accounts without a paid Copilot license and faithful to the upstream project.

### Components

1. **`config.py`** — add two settings to `Settings`:
   - `scenario: str = Field(default="OfficeWebPaidCopilot", alias="M365_SCENARIO")`
   - `license_type: str = Field(default="Premium", alias="M365_LICENSE_TYPE")`

2. **`substrate_client.py`** — `SubstrateCopilotClient.__init__` gains `scenario` and
   `license_type` parameters (defaulting to `"OfficeWebPaidCopilot"` / `"Premium"`),
   stored on the instance. `_ws_url` interpolates `self._scenario` and
   `self._license_type` in place of the hardcoded `OfficeWebIncludedCopilot` /
   `Starter`. This is the only behavioral change to the request.

3. **`app.py`** — the default `copilot_client_factory` passes
   `resolved_settings.scenario` and `resolved_settings.license_type` into the
   `SubstrateCopilotClient` constructor alongside the token and time zone.

### Data flow

Unchanged. Every request — plain chat, all endpoints — now connects as the paid
Copilot, so Graph grounding is available everywhere and the user queries M365 data by
asking in natural language. No new endpoints, no request-shape changes beyond the two
URL params.

### Error handling

If an account without a paid Copilot license points at the premium scenario and the
substrate rejects the connection, it surfaces through the existing path as a
`SubstrateCopilotError` → HTTP 502. Documented as the override case; not specially
handled.

## Testing

- **Unit:** `SubstrateCopilotClient._ws_url` includes the configured `scenario` and
  `license_type` (default premium values, and a custom override). Because `_ws_url`
  is currently private and builds a full URL, assert on substrings
  (`scenario=OfficeWebPaidCopilot`, `licenseType=Premium`) using a client built with a
  valid fake JWT (mirror `make_jwt` in the existing tests).
- **Unit:** the default `copilot_client_factory` passes the settings' scenario/license
  into the client — verify by monkeypatching `SubstrateCopilotClient` to record its
  constructor args (mirror `test_default_client_factory_reloads_token_from_env`).
- **Verification (manual, already done and to be repeated post-change):** a grounded
  query ("meetings today") returns real data rather than "I can't access...".

## Risks & caveats

- **License dependency:** grounding requires the account's paid M365 Copilot license.
  The default assumes it; accounts without it must override to the starter values.
- **Broader data exposure:** every request now runs against the enterprise-grounded
  Copilot, so responses may draw on the user's mail/calendar/files. This is the intended
  capability but worth noting for anyone routing untrusted prompts through the proxy.
- **Acceptable use:** grounded automated queries reach real corporate M365 data; use
  should be a deliberate decision on a corporate tenant.
- **Parameter drift:** Microsoft could rename or gate the scenario/license values; if
  grounding regresses, re-capture the real UI's request and update the defaults.
