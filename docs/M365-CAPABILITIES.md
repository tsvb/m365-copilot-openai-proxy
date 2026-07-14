# M365 Copilot Proxy — Agentic Capability Map

*Based on empirical, low-exposure probing on 2026-07-13 against a paid M365 Copilot
tenant with Work IQ enabled. Copilot behavior can change; re-probe before relying on
anything marked unverified.*

## Summary

In **Work mode** (`M365_WORK_MODE=true`), the proxy can **read and reason across every
major Microsoft 365 surface plus the web**. It **cannot edit files**, and its **action
tools (email/calendar) are self-reported but unverified**. The realistic agentic sweet
spot is a **read-only, multi-source analyst**, not a file editor or an autonomous actor.

## Read / ground — confirmed working

| Surface | Depth observed |
|---|---|
| Outlook email | Full body read + detail extraction (claimed and consistent with grounding) |
| Calendar | Meetings, times, attendees |
| OneDrive / SharePoint files | Find + read full contents *"if it can open the specific document"* |
| Teams messages | Chats and channels (returned real activity counts) |
| Company directory / people | Manager, coworker roles |
| Public web | Bing grounding |

## Actions — claimed by Copilot, NOT verified

Verifying these requires performing real side effects on a live corporate mailbox /
calendar, which was deliberately **not** done. Treat as unconfirmed.

- **Email:** create / update / delete drafts, send / reply / forward, archive, create
  inbox rules, folders, categories.
- **Calendar:** schedule / modify / cancel meetings and events.
- **Files:** ❌ **cannot** create, edit, or save changes to OneDrive/SharePoint
  documents (explicitly denied by Copilot).

## Reliability and limits

- **Per-turn grounding variance.** The same query sometimes grounds and sometimes
  refuses. Any agentic loop must retry on refusal.
- **Weak targeting / enumeration.** Copilot could not reliably list "all files in a
  folder" or report a folder's file count. You can name a *specific* document; you
  cannot reliably sweep a location.
- **Action/confirmation protocol is unhandled.** Real M365 actions normally surface a
  *confirmation card* in the Copilot UI that the user approves. The proxy only streams
  text and never answers that card, so even if an action tool fires it may stall or
  fail to complete. This is the largest unknown for the actions path.
- **Read depth partly unproven.** A clean deep-read test was muddied because this repo
  lives under the user's OneDrive, so "most recent file" probes hit dev files (e.g.
  `.env`, `.pyc`) rather than business documents.
- **No file writes.** Confirmed — read-only for documents.

## What "pseudo-agentic" can and can't mean here

- ✅ **Read-only multi-source analyst** — ask questions spanning mail + files +
  calendar + Teams + people + web and have Copilot reason across them. Feasible today,
  low risk. This is the strong capability.
- ⚠️ **Action-taking (email/calendar)** — possibly available, but unverified, likely
  blocked by the confirmation-card protocol, and high-risk on a healthcare tenant.
  Requires explicit consent and guardrails (draft-only, dry-run) before any test.
- ❌ **Working *on* files (edit/save)** — not possible through this API.

## Safe next step if the actions path is ever explored

The lowest-risk probe is a single **draft-only** email attempt (creates a draft in the
mailbox, sends nothing). It would reveal whether the action tools execute at all and
whether the confirmation-card wall is real — but it still writes to the real mailbox,
so it should only be run with explicit consent.
