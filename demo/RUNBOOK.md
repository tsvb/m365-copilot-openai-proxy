# Demo Runbook — M365 Copilot Proxy

**The story (one line):** this turns Microsoft 365 Copilot — a browser-only chat box —
into a standard AI API that answers from your real work data, with **no Azure app
registration, no admin consent, no Graph SDK**.

Target length: ~4–5 minutes, live. Four beats.

---

## Before you start (checklist)

- [ ] The signed-in **debug Edge window is open** (`m365.cloud.microsoft/chat`) and
      **Work IQ is ON** (the Work/Web toggle). Grounding depends on it.
- [ ] The proxy is running under `serve`:
      `uv run copilot-openai-proxy serve --no-launch-edge`
      (its own console window; leave it visible — you'll reference the `[r]` refresh).
- [ ] Token is valid: `Invoke-RestMethod http://127.0.0.1:8000/v1/token/status`
      → `valid: True`. (If not, press `r` in the serve console or just wait — it
      auto-refreshes.)
- [ ] Do a **dry run** of every command below once, right before the demo. Grounding
      is decided per turn; the scripts retry, but rehearse so you know what appears.
- [ ] Decide your audience → decide `-Safe` (see the warning box).

> ### ⚠️ Sensitivity — read this
> The grounded output is **real**: it shows real meetings, coworker names, client
> names, internal projects, and email counts from your account. DAS Health is a
> healthcare org — treat this as confidential.
> - **Trusted internal room:** full mode is fine and most impressive.
> - **External, recorded, or large audience:** use **`-Safe`** (counts + high-level
>   only), and never show email *contents* or anything PHI-adjacent.
> - Rehearse so nothing sensitive surprises you on screen.

---

## Beat 1 — "It's just an OpenAI call, but it knows your calendar." (~45s)

**Say:** "Getting calendar data into an app normally means an Azure AD app
registration, admin consent, Graph API scopes, token plumbing. Watch this instead."

**Run:**
```powershell
.\demo\hook.ps1
```

**Point out:** the request is the *exact* OpenAI chat-completions shape — model,
messages — yet the answer is your real day. "Any tool that speaks OpenAI can now read
M365 data. I registered nothing in Azure."

---

## Beat 2 — Morning briefing (the payoff). (~90s)

**Say:** "Because it's just an API, I can compose it into something I'd actually run
every morning."

**Run** (full, trusted room):
```powershell
.\demo\briefing.ps1
```
**Or** (safe, any audience):
```powershell
.\demo\briefing.ps1 -Safe
```

**Point out:** calendar + unread count + a *synthesized* "focus for today" that pulls
across calendar and mail — real cross-source reasoning over enterprise data, formatted
by a plain script. This is the beat leadership remembers.

---

## Beat 3 — Plug it into a real tool (breadth). (~60s)

**Say:** "The same endpoint powers coding agents and IDE assistants, not just scripts."

**Setup:** have a small repo/file ready (any project with a readable source file).

**Run** (from that repo's folder):
```powershell
opencode run "Read <file> and explain what it does in two sentences." -m m365copilot/m365-copilot --auto
```
(`--auto` so it doesn't pause on the read permission.)

**Point out:** OpenCode issued a real `read` tool call, the proxy fulfilled it, and
Copilot answered grounded in the file — a coding agent driven by M365 Copilot.

---

## Beat 4 — It runs itself (the kicker). (~30s)

**Say:** "And this isn't a fragile toy — it manages its own auth."

**Point out:** the browser token expires roughly hourly; the `serve` process reloads
the signed-in Copilot tab and re-captures a fresh token automatically — no
intervention. (If you want to show it, press `r` in the serve console and watch
`/v1/token/status` bump back up.)

**Close:** "M365 Copilot, turned into a programmable, self-healing API — your calendar,
mail, and files available to any script or AI tool, with zero Azure setup."

---

## Known rough edges (so nothing surprises you)

- **Meeting times can be off.** The proxy sends a hardcoded Tokyo timezone offset
  (`M365_TIME_ZONE` default `Asia/Tokyo`, offset 9), so specific meeting *times* may
  display shifted. The demo scripts avoid exact times for this reason. Fixable in the
  proxy (make the offset follow your timezone) — ask if you want it done before the demo.
- **Grounding is per-turn.** Copilot occasionally refuses even when it can; the scripts
  retry up to 3×. A dry run reduces surprises.
- **Read-only.** Tool use is read-only (`read`/`glob`/`grep`/`list`); no writes/sends.
- **Prerequisites are real.** Grounding needs a paid M365 Copilot license + Work IQ on,
  and the signed-in Edge window must stay open.
- **Framing.** This is an unofficial replay of your signed-in Copilot session — a
  powerful internal prototype, not a sanctioned/compliance-cleared integration.

## Files

- `demo/hook.ps1` — Beat 1.
- `demo/briefing.ps1` — Beat 2 (`-Safe` for audience-safe output).
- `demo/RUNBOOK.md` — this file.
