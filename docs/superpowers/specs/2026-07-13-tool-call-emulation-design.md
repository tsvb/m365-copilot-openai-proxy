# Read-Only Tool-Call Emulation for M365 Copilot Proxy

**Date:** 2026-07-13
**Status:** Design approved, pending implementation plan

## Summary

Add a read-only "file interaction" capability to the M365 Copilot OpenAI proxy so
that agentic clients — OpenCode specifically — can have Copilot inspect a real
codebase. Microsoft 365 Copilot exposes no native function-calling interface, so
this is achieved by **emulating** OpenAI's tool-calling protocol: the proxy prompts
Copilot to emit structured action requests, parses them, and reshapes them into
OpenAI `tool_calls` responses that OpenCode executes locally.

The first increment is **read-only** (`read`, `glob`, `grep`, `list`) and is built
to **keep-and-use quality** (robust parsing, retry/fallback, tests, clean module
boundaries), so that `write`/`edit`/`bash` can be added later by relaxing an
allowlist rather than rewriting.

## Motivation & key finding

The proxy currently flattens every request into a single plain-text prompt and
returns Copilot's prose. It drops any `tools` array the client sends
(`models.py`, `extra="ignore"`), so OpenCode connects and chats but cannot read,
edit, or run anything.

Empirical testing against the live proxy established the feasibility boundary:

- Prompting Copilot to "follow a user-supplied tool protocol" or "pretend to have
  tools that aren't available" → **hard refusal** (a tuned identity/safety behavior).
- Prompting Copilot to "output JSON describing the plan" → **clean, parseable JSON
  on the first attempt.**

Conclusion: Copilot can reliably emit structured JSON. The blocker is *framing*, not
capability. Reframing tool-calling as content generation ("request information by
emitting an action") avoids the refusal. This design is built around that finding.

## Scope

**In scope (v1):**
- Read-only tools only: `read`, `glob`, `grep`, `list` (reflected from whatever the
  client advertises; filtered by a read-only allowlist).
- OpenAI Chat Completions endpoint (`/v1/chat/completions`) as the integration
  surface, since that is what OpenCode's OpenAI-compatible provider uses.
- Single tool call per turn.

**Out of scope (v1):**
- `write`, `edit`, `bash`, or any state-changing tool.
- Parallel / multi-tool calls in a single turn.
- True token-by-token streaming of the final answer (buffered-then-re-streamed
  instead — see Data Flow).
- The `/v1/responses` and `/v1/messages` endpoints (chat completions only for now).

## Chosen approach

**Approach 1 — Faithful tool-call emulation, client-driven loop.**

The proxy stays a stateless translator and speaks OpenAI's tool protocol exactly.
OpenCode already runs the agent loop; the proxy lets it. Each HTTP request maps to
exactly one Copilot turn, and OpenCode's message array is the sole loop state.

The rejected alternative (Approach 2 — a proxy-side agent loop that executes file
ops itself and returns only prose) was declined because the proxy has no knowledge
of OpenCode's project directory, it duplicates tools OpenCode already has, it
bypasses OpenCode's UI and permission model, and it widens the security surface.
Approach 1 integrates correctly: reads run in OpenCode's own process (its project
root, its permissions, visible in its UI) and the path to `write`/`bash` later is a
one-line allowlist change.

## Architecture & module boundaries

The feature is a new **tool-emulation path** inside `/v1/chat/completions`, activated
only when the request carries a `tools` array. Plain chat requests keep flowing
through existing code unchanged.

Guiding boundary: **`substrate_client.py` never learns about tools** (it still just
sends text and returns text), and the emulation module never touches the network.
Parse/render logic is therefore unit-testable without a live Copilot.

- **`tool_emulation.py` (new)** — pure functions, no I/O:
  - `render_action_prompt(tools, messages) -> str` — the reframed prompt plus the
    conversation transcript, including prior actions and their results as
    observations.
  - `parse_copilot_turn(text, allowed_names) -> ToolAction | FinalAnswer`.
  - a tolerant JSON extractor (strips markdown fences and surrounding whitespace).
- **`models.py` (extend)** — add `tools` / `tool_choice` to the chat request; add
  `tool_calls` to assistant messages and `tool_call_id` to tool messages, so the
  proxy can read OpenCode's loop state back in.
- **`app.py` (extend)** — `/v1/chat/completions` branches: `tools` present →
  emulation path (emits a `tool_calls` response or a final answer); absent →
  current path.
- **`translator.py` (extend)** — reuse existing flattening; add rendering of `tool`
  result messages as observations.
- **`config.py` (extend)** — read-only tool allowlist, max observation size,
  `max_reasks`.

## The emulation protocol

Two rules do the heavy lifting: reframe tool-calling as content generation, and only
require JSON for actions — never for the final answer.

**Prompt sent to Copilot each turn:**
- An identity/task frame that avoids the refusal trigger words. Not "you have tools,
  call them" but e.g. "You are analyzing a code repository. To inspect it, you can
  request information by emitting a single action. The system runs the action and
  returns the result to you."
- A list of available **actions** (the read-only subset), each with its name and
  argument shape derived from the schemas the client sent, so names match what
  OpenCode will execute.
- Instruction: "To request information, reply with ONLY a JSON object:
  `{"action":"read","args":{"filePath":"..."}}`. When you have enough information,
  reply normally with your answer — plain prose, no JSON."
- The conversation so far, including prior actions and their results as observations.

**Why the final answer is prose, not JSON:** forcing Copilot to JSON-escape a long
markdown answer (with code blocks) is exactly where a prose-tuned model breaks. JSON
is required only on the cheap, structured action step.

**Parsing (`parse_copilot_turn`):**
1. De-fence and trim.
2. If the entire cleaned message parses as a JSON object matching a known action
   name → `ToolAction`.
3. Otherwise → `FinalAnswer` (the prose).

The action JSON must be the *whole* trimmed message, not embedded in prose — so a
final answer that merely contains a JSON code block is not mistaken for a tool call.

**Consequence:** each `read` is a separate Copilot turn, so a multi-file answer takes
several round-trips. This is inherent to the emulation and is why it is noticeably
slower than a native tool-calling API.

## Data flow across the loop

OpenCode drives; the proxy is stateless between requests and re-renders from
OpenCode's message array every time.

**Turn 1 — user asks "summarize auth.py":**
1. OpenCode → proxy: messages `[user]` + `tools`.
2. Proxy filters tools to the allowlist, renders the action prompt, opens a fresh
   (non-persistent) Copilot turn, sends text.
3. Copilot replies `{"action":"read","args":{"filePath":"auth.py"}}`.
4. Proxy parses → `ToolAction`, returns an OpenAI response with
   `finish_reason:"tool_calls"` and one tool_call
   `{id:"call_ab12", function:{name:"read", arguments:"{\"filePath\":\"auth.py\"}"}}`.

**Turn 2 — OpenCode executes and returns:**
5. OpenCode reads the file itself (its project root, its permissions, its UI), then
   → proxy: messages `[user, assistant(tool_calls), tool(result, tool_call_id:"call_ab12")]`.
6. Proxy re-renders the whole thing; the `tool` message becomes an observation:
   `Observation for read(filePath=auth.py):\n<content>`. Fresh Copilot turn, full
   context in the prompt.
7. Copilot replies with prose (the summary).
8. Proxy parses → `FinalAnswer`, streams it back as assistant deltas,
   `finish_reason:"stop"`.

**Fresh Copilot conversation per request (not `:persist`):** the proxy manages
context itself via the rendered transcript. Letting Copilot also keep its own memory
would double-feed and desync from OpenCode's authoritative history. Deliberately
stateless on the Copilot side.

**Streaming — buffer the Copilot turn, then emit:** although OpenCode sends
`stream:true`, the proxy reads each Copilot turn to completion internally, parses the
complete text, then produces SSE:
- `ToolAction` → a single tool_calls chunk + done.
- `FinalAnswer` → re-chunk the prose into streamed deltas + done.

This avoids parsing partial JSON from a token stream. Tradeoff: the final answer is
buffered-then-re-streamed rather than true token-by-token. True streaming of finals
is a possible later enhancement.

**Observation size guard:** large file contents folded into the next prompt risk
Copilot's context limit. OpenCode already caps read output; the proxy adds a
defensive cap (config) and marks truncation so one huge file cannot blow the turn.

## Error handling & fallbacks

Governing principle: the loop must always terminate in a valid OpenAI response —
never a hang or a 500.

| Situation | Handling |
|---|---|
| Expected an action, got malformed/ambiguous output | One stricter re-ask ("Reply with ONLY the JSON action, or your final answer."). Still bad → treat as `FinalAnswer`. |
| Copilot proposes an unknown or filtered tool (`write`, `bash`) | Re-ask: that action isn't available, use only listed read actions or answer. After `max_reasks` failures → finalize with a short explanatory message. |
| Copilot re-requests a file already in the transcript | Detect duplicate `action+args` against prior observations; nudge to continue or answer. Repeated → finalize. Guards against read loops. |
| Copilot refuses outright (identity refusal) | Treated as `FinalAnswer` and returned verbatim. |
| Substrate/WebSocket error, expired token | Existing path: HTTP 502 (streaming: SSE `error` event). Unchanged. |
| Empty Copilot turn | Re-ask once; then finalize with a generic "couldn't produce a result" message. |

Tunables: `max_reasks` (default 2) and the observation cap. OpenCode enforces its own
max-steps ceiling on the outer loop, bounding the whole thing from both ends.

Deliberate v1 non-goal: parallel/multi-tool calls. Exactly one tool_call per turn.

## Testing

Rendering and parsing are pure functions, and `create_app` already accepts an
injectable `copilot_client_factory` (used by the existing `test_app.py`), so the
whole loop is testable without a live Copilot or WebSocket.

**Unit tests — `tool_emulation.py` (pure):**
- `parse_copilot_turn`: clean action JSON; fenced action; prose final; prose that
  merely contains a JSON code block (must → final); unknown/filtered tool name;
  malformed JSON; empty string.
- `render_action_prompt`: allowlist filters out `write`/`bash`; action names/args
  reflect the schemas sent; a `tool` result renders as an observation; observation
  cap truncates and marks oversized content.

**Integration tests — `/v1/chat/completions` with a scripted fake client:**
- `tools` + user message, fake returns an action → response has
  `finish_reason:"tool_calls"` and one well-formed tool_call (valid `id`, name in
  allowlist, `arguments` is valid JSON).
- Follow-up request with `assistant(tool_calls)` + `tool(result)`, fake returns prose
  → streams a `FinalAnswer` with `finish_reason:"stop"`.
- Fallback: fake returns garbage twice → endpoint still returns a valid final
  response (no 500).
- Regression: request with no `tools` → old plain-chat path, unchanged.

**End-to-end manual (acceptance):** run actual OpenCode against the running proxy in
a small project and have it read and summarize a real file, confirming the reads show
up in OpenCode's UI and the round-trip completes.

## Risks & caveats

- **Reliability:** Copilot is a prose-tuned assistant being coaxed into structured
  behavior. It may occasionally add citations, fences, or safety preambles. The
  tolerant parser plus re-ask/fallback contain this, but it will not be as crisp as
  a native tool-calling model.
- **Latency:** every agent step is a full WebSocket round-trip; multi-step reads are
  noticeably slower than a real API.
- **Context limits:** large observations fed back as prompt text can approach
  Copilot's context ceiling; the observation cap mitigates but does not eliminate.
- **Product tuning drift:** Microsoft can change Copilot's behavior at any time,
  which could weaken the reframing.
- **Acceptable use:** this drives the browser-facing Copilot endpoint on a corporate
  tenant. Read-only keeps it conservative, but automated use should be a deliberate
  decision.
