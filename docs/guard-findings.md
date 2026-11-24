# Usage guard — verification findings

Companion to `docs/guard-spec.md`. The spec is the design; this file is the evidence log.
Everything marked **VERIFIED** was executed on this machine. Everything else is stated as unverified on purpose.

Versions at time of testing: herdr 0.9.5, codex 0.171.0, Claude Code 2.1.331, Antigravity (Electron + Go language server, bundle dated 2025-11-21).

---

## A. Verification results

### A1. Hook blocking — the load-bearing assumption

| Harness | Event | Result | Evidence |
| --- | --- | --- | --- |
| Claude Code | `PreToolUse` + `permissionDecision: deny` | **VERIFIED blocks** | agent reported "A PreToolUse hook blocked the Bash call with this error: `PreToolUse:Bash hook error: SPIKE: blocked by test hook`" and explicitly declined to work around it |
| Codex | `PreToolUse` + `permissionDecision: deny` | **VERIFIED blocks** | `ERROR codex_core::tools::router: error=Command blocked by PreToolUse hook: SPIKE: blocked by test hook. Command: echo hi` → `hook: PreToolUse Blocked` → model reported the block and stopped |
| Codex | `UserPromptSubmit` + `decision: block` | **VERIFIED blocks, costs 0 tokens** | `hook: UserPromptSubmit` → `hook: UserPromptSubmit Blocked`; run ended before the model call |
| Codex | `PreModelRequest` | **VERIFIED does NOT block** | hook ran (`hook: PreModelRequest` → `Completed`), `{"decision":"block","reason":"…"}` accepted without error, model proceeded normally (6,302 tokens, answered) |
| Claude Code | `UserPromptSubmit` + `decision: block` | **NOT TESTED** (quota) | shape documented in Claude's hooks reference; exit code 2 + stderr is the documented fallback |
| Antigravity | any hook | **NOT TESTED** | app is installed but has no signed-in state; all Antigravity claims below come from its binaries |

Conclusions:

1. The core design holds. Both harnesses deny at the tool boundary, and the agent parks and reports rather than retrying. The reason string does the work — a specific reason plus a reset time is what stops the loop.
2. **Codex `preModelRequest` is not the better gate I hoped for.** The spec's open question is answered: drop it. Codex's finest mid-turn gate is `preToolUse`, same as Claude.
3. Codex's `UserPromptSubmit` is the cheapest gate in the whole system: it refuses the turn before the model runs, so a tripped guard costs zero tokens on the *next* prompt.

### A2. Hook payload shapes (captured, real)

Claude `PreToolUse` stdin:

```json
{"session_id":"30706006-…","transcript_path":"/Users/seanyu/.claude/projects/-private-tmp/…jsonl","cwd":"/private/tmp","prompt_id":"eff410d3-…","permission_mode":"default","effort":{"level":"medium"},"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo hi","description":"Print hi via echo"},"tool_use_id":"toolu_011JtDYjD7MHAtG8WqXbcaDj"}
```

Codex `PreToolUse` stdin:

```json
{"session_id":"01a20e00-…","turn_id":"01a20e00-…","transcript_path":"/private/tmp/codex-spike/sessions/…jsonl","cwd":"/private/tmp","hook_event_name":"PreToolUse","model":"gpt-5.6-luna","permission_mode":"bypassPermissions","tool_name":"Bash","tool_input":{"command":"echo hi"},"tool_use_id":"exec-e300b2ba-…"}
```

Notes:

- Both use **PascalCase `PreToolUse`** in the payload, and Codex accepts PascalCase in `hooks.json`. Codex's internal wire enum is camelCase (`preToolUse`) but the config file surface is PascalCase.
- Codex's payload carries `permission_mode` and `model`; Claude's carries `prompt_id` and `effort`.
- Neither needs to be parsed by the guard. Passing the event name as argv (as the prototype does) avoids reading stdin at all.

### A3. Hook trust (Codex)

- `~/.codex/hooks.json` hooks require trust, recorded in `~/.codex/config.toml` under `[hooks.state."<path>:<event>:<n>:<n>"]` as `trusted_hash` and sometimes `trusted_content_hash`.
- **`trusted_hash` is not a plain SHA-256 of `hooks.json`.** Verified: file hash `929ee9f8…` vs stored `0187e544…`. Canonical-JSON and stripped variants also miss. The hash covers something narrower (likely the individual hook entry).
- `--dangerously-bypass-hook-trust` works and is what the spike used. Codex printed a warning each invocation.
- Codex did **not** write trust state into a fresh `CODEX_HOME` even when bypassed.
- **Conclusion: do not compute the trust hash. Install the hook, then let Codex prompt once and have the user approve.** Programmatic trust is unverified and not worth reverse-engineering.

### A4. Decision engine prototype — 20/20

A throwaway prototype implemented the spec's `policy.json` / `usage.json` / `decision` contract, latch, staleness rule, and hook output, driven by a shell harness asserting the §7 failure-mode table. Both were scratch and are not kept — phase 1 (`bin/guard.sh`, `tests/guard.sh`) supersedes them. The results are what matter and they are recorded below.

```text
--- failure-mode table ---
  PASS  unarmed -> exit 30
  PASS  unarmed -> hook silent
  PASS  armed, 39% vs 40% -> exit 0
  PASS  armed below -> hook silent
  PASS  armed, 41% vs 40% -> exit 10
  PASS  tripped -> PreToolUse deny JSON
  PASS  reason carries pct + threshold
  PASS  reason carries reset time
  PASS  tripped -> UserPromptSubmit block JSON
  PASS  codex event name passed through
--- staleness ---
  PASS  stale while armed -> exit 20 (fail-open)
  PASS  stale -> hook silent (fail-open)
  PASS  stale while tripped -> still exit 10 (latch wins)
  PASS  stale tripped -> hook still denies
--- latch ---
  PASS  latched: lower reading does not clear
  PASS  until=reset + resets_at passed -> cleared
  PASS  until=manual -> resets_at passing does NOT clear
--- corrupt / missing ---
  PASS  missing decision -> hook silent
  PASS  corrupt policy -> unarmed
  PASS  corrupt usage -> stale

pass=20 fail=0
```

The two rules that carried the design are now proven, not asserted: **fail-open entering, never fail-out**, and **latch beats staleness**.

### A5. Two bugs found by the prototype (both worth carrying into the real implementation)

1. **bash `local` declares every name before assigning any.** `local spec="${a#*=}" win="${spec%%=*}"` leaves `win` empty — bash marks all names local first, so `${spec}` reads the fresh empty local. Cost me two test rounds. Declare, then assign on separate lines. This will bite again in any option parser.
2. **`guard arm` must evaluate immediately, and that is surprising.** Arming against an already-fresh `usage.json` above the threshold trips on the spot. That is correct per D10 (arming below the current number should trip at once) but the first `arm` after a heavy session will trip instantly. `guard arm` must say so in its output rather than silently going tripped.
3. Minor: `d=$(<"$DECISION") 2>/dev/null` does **not** suppress the "No such file or directory" from the redirect. Use `[ -f "$DECISION" ] || exit 0` first — which is cheaper anyway and is what the hot path should do.

---

## B. Measured costs (200 invocations each)

| Path | ms |
| --- | --- |
| bare `bash` spawn floor | 2.89 |
| hook: `[ -f ]` + read + integer compare | 4.75 |
| hook: fast exit when unarmed | 4.34 |
| hook via `jq` | 7.13 |
| `find` + loop over `profiles/*.json` | 9.56 |
| codex reader, warm cache | 36.0 |
| codex reader, cold (`codex app-server` boot) | 363 |

Budget: `tool_calls × 4.8 ms` per turn. 100 tool calls = 0.5 s inside a multi-minute turn. Holds only while the hook reads precomputed files — the three rules in spec §3 are load-bearing.

Spike cost in vendor tokens: ~12k Codex tokens across three runs, one small Claude Haiku call. Codex `UserPromptSubmit` cost 0.

---

## C. Environment gotchas (will break the implementation if not handled)

1. **`ANTHROPIC_API_KEY` shadows the claude.ai login.** `claude -p` failed with `Invalid API key · Fix external API key` until run under `env -u ANTHROPIC_API_KEY`. Any guard test harness or CI must unset it, or it will silently test nothing.
2. **Claude `--bare` skips hooks** defined in settings and plugins. Never test hooks under `--bare`.
3. **`claude --settings <file-or-json>` exists.** Hooks can be tested in full isolation without touching `~/.claude/settings.json`. Use it in tests.
4. **`CODEX_HOME` works.** A temp home with a copied `auth.json` and a minimal `config.toml` gives isolated Codex hook testing. Use it in tests.
5. **Codex rejects `permissionDecision: "allow"`** (`PreToolUse hook returned unsupported permissionDecision:allow`). Only emit `deny`.
6. **Claude `EndConversation` skips `PreToolUse` and `PostToolUse`.** Irrelevant for us (it only ends the session) but do not write tests that assume every tool call is gated.
7. Claude Code's built-in `Notification` matcher already includes `quota_auto_resume_fired` / `quota_auto_resume_stale` / `quota_auto_resume_disabled`. Claude has native quota auto-resume. Do not build a resume path.

---

## D. Antigravity scope

The user runs Antigravity (`/Applications/Antigravity.app`). It is a Google agent IDE: Electron/VS Code-derived shell over a Go `language_server` (196 MB, `Contents/Resources/bin/language_server`). Its agent, tools, policy engine, and quota all live in that Go binary, not in `app.asar`.

**Nothing below is runtime-verified.** The app has no signed-in state on this machine, and the CLI log shows the account is refused for location reasons. The hook contract in D7 does come from Antigravity's own bundled documentation (`docs/hooks.md`), which is a stronger source than the binary strings the rest of this section is built on.

### D1. Data surface — quota is readable

Confirmed symbols:

- `RetrieveUserQuotaSummary` on `/exa.language_server_pb.LanguageServerService/…` — a **local** RPC on the language server.
- `GetUserQuotaSummary` on `JetskiRemoteAgentProxyService`.
- `FetchQuotaStatus` on both `google.cloud.businessaicode.v1beta.PredictionService` and `google.gca.aicode.v1main.PredictionService`.
- Response types: `QuotaSummaryBucket`, `QuotaSummaryGroup`, `QuotaLimit`, `QuotaType`, `QuotaResponse_TokenType`, `QuotaMetadata`, `remaining_fraction`.
- Tier/plan: `aicode_user_tier`, `tier_description`, `AntigravityExtension_UserTier`.
- Failure string in the wild: `individual quota reached`.
- Billing doc reference in the binary: `https://aistudio.google.com/docs/billing#tier-spend-caps`.

Local state that likely carries usage without any API call:

- `~/.gemini/antigravity-cli/` — `settings.json`, `conversation_summaries.db`, `jetski_state.pbtxt`, `brain/`, `implicit/*.pb`, `cli.log`.
- `~/.gemini/oauth_creds.json`, `~/.gemini/google_accounts.json`, `~/.gemini/installation_id`.

**Implication:** `remaining_fraction` is a *remaining* direction while Claude and Codex report *used*. The guard's internal contract must stay percent-**used** (spec D3 direction) and invert on ingest, exactly as the existing plugin already does for its own readers.

### D2. Enforcement surface — hooks exist, and they can deny

Confirmed strings, verbatim:

- "**Hooks** defined in `plugins/<name>/hooks.json` are registered and run"
- "Runtime plugin discovery strictly loads `hooks.json` from the plugin [root]"
- "The working directory is set to the directory containing `hooks.json`."
- `tool call denied by pre-tool hook: %s`
- `unknown pre-tool hook decision %q` / `unsupported hook decision: %s` / `failed to parse pre-tool hook permission override %q: %v`
- `.denied is True when a pre-tool hook or the permission check rejected the call`
- `A pre-tool hook changed the arguments of this tool call before it ran.`
- `post-tool hook failed: %v`, `failed to call custom stop hook %s: %v`
- `UserPromptSubmit` hooks: `Not running UserPromptSubmit hooks: failed to create customization manager: %v`, `The following system message was injected by a UserPromptSubmit hook:`
- `HookType` includes `HOOK_TYPE_POST_INVOCATION`; `AgentBehavior` includes `AGENT_BEHAVIOR_AUTONOMOUS`.
- Plugin/install surface: `agy plugin install` stages plugins; `hooks/hooks.json` is imported to `<plugin_dir>/hooks.json`; manifests are `plugin.json` or `.antigravity-plugin/plugin.json`.

So Antigravity maps onto the same two-gate model: a pre-tool gate that can deny, and a `UserPromptSubmit` gate. The decision vocabulary is *not* Claude's `permissionDecision` — it is Antigravity's own ("unknown pre-tool hook decision %q" implies an enum we have not read yet). **The hook shim must be per-harness anyway**, which the prototype's `guard hook <provider> <event>` argv design already supports.

### D3. Native budget — possibly do not build this at all

Confirmed symbols: `BudgetConfig`, `BudgetConfig_BudgetScope`, `BudgetScope`, `budget_tokens`, `budget_scopes`, `budget_consumption_detail`, `budget_exhausted`, `budget_hook`, `budget_validation`.

Antigravity appears to have a **first-class token budget with a hook on exhaustion**, scoped per session or per conversation. If it is configurable, a chunk of the Antigravity requirement is native and the guard should stay out of the way.

Also present: a policy engine (`PolicyDecision`, `PolicyRule`, `PolicyConfig_WorkspaceContainment`) and a guardrail system rooted at `~/.gemini/config/` alongside `outside-of-project.json`, `sidecar.json`, `memory-hook`, `verifier.py`, `test_security.py`. Note that Antigravity's own safety text treats `hooks.json` and `~/.gemini/config/**` as **tamper-sensitive** — editing them may trip its own guardrails and will be flagged as `irreversible` by its risk classifier. Install must be reversible and clearly attributed.

### D4. Antigravity spike (must run before committing)

Items 1–2 are already answered: `bin/agy-usage.py` ships in Epic 3 (`d1948ec`) and [`docs/usage-sources.md`](usage-sources.md) documents the transport — `agy -p "/usage" --output-format json`, backed by `POST https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary`, with the local language server exposing `GetUserStatus` over Connect RPC on a random localhost port and the CSRF token in its process arguments. `remainingFraction` is 0–1 **remaining**, so used = 1 − fraction.

Remaining spike:

1. Author a minimal `hooks.json` with a pre-tool hook that denies, install via `agy plugin install`, and confirm a tool call is actually blocked and what the decision enum is. Also confirm `PreInvocation` + `terminationBehavior: "terminate"` stops before the model call.
2. Determine whether `BudgetConfig` already covers "stop at N%". If it does, Antigravity's guard work is *configuration*, not code.
3. Confirm which paths are writable without tripping guardrails: prefer the plugin path over `~/.gemini/config/**`.
4. Both blocked on an eligible account — see `PLAN.md` → Blocked.

### D5. Effort estimate

- Antigravity **reader** (quota → `usage.json`): **already shipped.** `bin/agy-usage.py` emits `(key, used_percent, reset_epoch)` — exactly the row format the guard consumes. No work.
- Antigravity **hook shim**: small. The prototype's `guard hook <provider> <event>` argv design covers it; the output shape differs (`decision: deny` / `terminationBehavior: terminate`, not `permissionDecision`).
- Antigravity **installer**: medium — a different install surface (`agy plugin install`, `plugins/<name>/hooks.json`) and a tamper-sensitive one.
- Risk: Antigravity's own guardrails may treat the guard's config edits as tampering. This is the one place where the guard could make the harness *less* safe.
- Not verifiable on this machine: the account is refused for location, so phase 4 ships blind.

### D6. Antigravity CLI (`agy`) — a real, documented surface

`/opt/homebrew/bin/agy` exists. This is the best-instrumented of the three harnesses.

CLI flags that matter: `-p/--print` (headless single prompt), `--output-format text|json|stream-json`, `--settings` (session-only JSON, never saved — same isolation trick as `claude --settings`), `--dangerously-skip-permissions`, `--model`, `--effort`, `--sandbox`, `--log-file`. Subcommands: `plugin install|uninstall|list|enable|disable`, `models`, `mcp`, `agents`, `install`, `acp`, `update`.

Quota is reachable from the CLI: `~/.gemini/antigravity-cli/cli.log` shows `quota_manager.go` calling `POST https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary`, and `cache.go` caching it under the key `retrieveUserQuotaSummary`. So the reader can be a CLI invocation or the same endpoint the CLI uses.

Local state: `~/.gemini/antigravity-cli/{settings.json,conversation_summaries.db,jetski_state.pbtxt,brain/,implicit/*.pb,cli.log}`, plus `~/.gemini/{oauth_creds.json,google_accounts.json,installation_id}`.

Bundled customization docs are on disk at `~/.gemini/antigravity-cli/builtin/skills/agy-customizations/docs/` — `hooks.md`, `plugins.md`, `json_configs.md`, `rules.md`, `skills.md`, `mcp_servers.md`. These are the vendor's own specs, not strings scraped from a binary.

**Blocker on this machine:** the CLI log shows the account is refused — `Account ineligible: Your current account is not eligible for Antigravity, because it is not currently available in your location`, and quota returns `PERMISSION_DENIED (code 403): You do not have a valid license of this product`. Antigravity cannot be runtime-tested here at all.

### D7. Antigravity hook contract (authoritative, from `docs/hooks.md`)

`hooks.json` lives in a customization root (e.g. `.agents/hooks.json`) or `plugins/<name>/hooks.json`. Its top level is **named hooks**, each with `enabled` and event arrays — a different shape from Claude and Codex, which are event-first.

```json
{
  "usage-guard": {
    "PreToolUse": [
      { "matcher": "*", "hooks": [ { "type": "command", "command": "<bin> guard hook antigravity PreToolUse", "timeout": 5 } ] }
    ]
  }
}
```

Events and their contract:

| Event | Structure | Output contract |
| --- | --- | --- |
| `PreToolUse` | grouped (`matcher` + `hooks`) | `{"decision": "allow"\|"deny"\|"ask"\|"force_ask", "reason", "permissionOverrides", "overwrite"}` — **`deny` hard-blocks** |
| `PostToolUse` | grouped | expects `{}` |
| `PreInvocation` | flat list | `{"injectSteps": [...], "terminationBehavior": ""\|"terminate"}` — **`terminate` stops before the model call** |
| `PostInvocation` | flat list | `{"terminationBehavior": "force_continue"\|"terminate"}` |
| `SessionStart` | flat list | `{"injectSteps": [...]}` |
| `Stop` | flat list | `{"decision": "continue"}` blocks the stop (inverse — not useful to us) |

Matcher is a regex on the tool name, derived by lowercasing the step type and stripping the `CORTEX_STEP_TYPE_` prefix (`run_command`, `view_file`, `browser_.*`). Handler is `type: "command"` only, run via `sh -c`, cwd = the directory containing `hooks.json`, default timeout 30 s. Plugin hooks additionally get `PLUGIN_ROOT` and `PLUGIN_DATA`.

Payload is camelCase protojson on stdin: `conversationId`, `workspacePaths`, `transcriptPath`, `artifactDirectoryPath`, `modelName`, `lastUserInput`, `hookEventName`, `cwd`, plus event-specific `toolCall{id,name,args}` / `stepIdx` / `invocationNum` / `terminationReason`.

Two consequences for us:

1. **`PreInvocation` + `terminationBehavior: "terminate"` is a true pre-model gate** — the equivalent of Codex `UserPromptSubmit`, and it can pair with an injected `errorMessage` so the user sees why. Antigravity is the only harness of the three with both gate types.
2. **"Hooks run synchronously and block the agent loop (no async execution)"**, and multiple named hooks for the same event are **merged and executed sequentially**. So our hook adds serial latency on every tool call and every invocation, on top of whatever else the user has installed. Antigravity is the worst case of the three for hook latency.

### D8. Gate matrix — the three harnesses are not equivalent

| Harness | Pre-model gate | Tool gate | Cost of a trip |
| --- | --- | --- | --- |
| Claude Code | **none exists** (verified: no pre-model hook in the event list; `PostToolBatch` is context-only) | `PreToolUse` + `permissionDecision: deny` — **verified** | ~1 extra model call |
| Codex | **none** (`preModelRequest` verified non-blocking) | `preToolUse` + `permissionDecision: deny` — **verified** | ~1 extra model call |
| Codex (`UserPromptSubmit`) | turn start only | — | **0 tokens** — verified |
| Antigravity | `PreInvocation` + `terminate` | `PreToolUse` + `decision: deny` | **0 tokens** |

The asymmetry matters: on Claude and Codex a trip costs one more model call before the agent settles, because the agent has already committed to the turn. On Antigravity it can cost nothing. Design the Antigravity shim around `PreInvocation` first and treat `PreToolUse` as the backstop, not the other way round.

---

## E. Revised architecture — harness adapters

The verification forces one structural change to the spec: the guard is not "Claude + Codex", it is a **harness-agnostic core with per-harness adapters**.

```text
  writers (per harness)          core                        shims (per harness × event)
  ─────────────────────          ────                        ───────────────────────────
  Claude statusLine  ─┐
  Codex app-server   ─┼─►  usage.json  ─┐
  Antigravity RPC    ─┘                 ├─► guard_eval ─► decision ─► guard hook claude PreToolUse
                                        │                            guard hook claude UserPromptSubmit
  arm / disarm ──────────► policy.json ─┘                            guard hook codex  PreToolUse
                                                                     guard hook codex  UserPromptSubmit
                                                                     guard hook antigravity <event>
```

What that buys:

- The hot path and the latch logic are written once. 20/20 prototype tests cover all harnesses at once.
- Adding a harness is a writer, a shim, and an installer — never a change to the decision engine.
- The existing `herdr-agent-usage` reader work is reused verbatim for Claude and Codex.

What it changes in the spec:

- §8 hook installation becomes per-adapter with a shared reversible-install helper.
- The `window` vocabulary needs a per-provider mapping (`remaining_fraction` inverted on ingest for Antigravity).
- `provider` becomes `harness` in `policy.json` for clarity, with `claude` / `codex` / `antigravity` as values.
- New non-goal: do **not** reimplement Antigravity's native `BudgetConfig` if it already does the job.

---

## F. Carry-over checklist

- [x] Claude `PreToolUse` deny blocks — proven
- [x] Codex `PreToolUse` deny blocks — proven
- [x] Codex `UserPromptSubmit` blocks at zero token cost — proven
- [x] Codex `PreModelRequest` does not block — drop it
- [x] Decision engine + latch + staleness: 20/20 against the failure table
- [x] Hot path cost 4.75 ms; three "never do this in the hook" rules measured
- [x] Codex trust is interactive; do not reverse-engineer the hash
- [ ] Claude `UserPromptSubmit` block — documented, untested (needs one small call)
- [ ] Antigravity spike D4 (5 items) — untouched
- [ ] Phase 1 implementation: `bin/guard.sh` and `tests/guard.sh`, rebuilt from the prototype and its harness
- [ ] Phase 2: Claude hooks, reversible installer, real session for a week
- [ ] Then Codex, then Antigravity

## G. Repro commands

```sh
# Codex hook block, isolated home
CODEX_HOME=/tmp/codex-spike codex exec --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust \
  -m gpt-5.6-luna -c model_reasoning_effort=low "Run the shell command: echo hi"

# Claude hook block, isolated settings (must drop the shadowing key)
env -u ANTHROPIC_API_KEY claude -p --settings /tmp/claude-spike-settings.json \
  --allowedTools Bash --model haiku --no-session-persistence "Run the shell command: echo hi"
```

---

## H. Blast radius, cost, and impact

Measured this round: `guard_eval` **31 ms** (jq, off the hot path), hook **6.8 ms**, concurrent hook spawns **1→11.3 / 5→16.2 / 10→23.4 / 20→42.7 ms wall** (spawns overlap, so a 10-wide parallel batch costs +23 ms wall, not 10×6.8).

### H1. Latency — negligible, and not the risk

`tool_calls × ~6 ms`, per harness. A 10-wide parallel tool batch adds ~23 ms. A 100-tool-call turn costs ~0.6 s inside a multi-minute turn. Applies whether armed or not (4.3 ms floor when unarmed).

Two multipliers to remember: hooks fire **inside subagents**, so a fleet multiplies; and on Antigravity hooks are synchronous and sequentially merged, so our 6 ms stacks on every other hook the user has.

Verdict: not the thing to worry about.

### H2. Tokens — one extra model call per trip, on Claude and Codex only

Measured in the Codex spike: blocked run 5,682 tokens vs normal run 6,302. A `PreToolUse` trip does not save tokens on that turn; the agent has already committed, so it costs one more model call to react. Gate choice decides this: `UserPromptSubmit` (Codex) and `PreInvocation` (Antigravity) trip at **0 tokens**.

Verdict: trivial, and avoidable on two of three harnesses.

### H3. A false trip is the real cost — and it is a big hammer

The guard is **account-scoped and latched**. One false trip blocks every pane on that account, including panes started afterwards, until the window resets or the user disarms. On a weekly window with six days left, that is six days of dead agents.

Two defects in the current design that make this worse, both found while testing:

1. **The latch is not keyed by account/profile.** `tripped` stores `(provider, window, resets_at)`. Sign into a different Claude account and account A's latch blocks account B. The latch key needs the profile id, which the reader already knows (`profiles/<seven_day.resets_at>.json`).
2. **`--until reset` cannot clear when `resets_at` is 0 or unknown.** A malformed or missing reset timestamp leaves the latch stuck with no automatic recovery, and the failure is invisible. Needs a fallback TTL (e.g. latch expires after the window length even without a usable `resets_at`).

The failure direction is asymmetric. False trip = visible, one-command recoverable. False allow = quota burns silently. But **stuck trip** is worse than either, because it looks like the agent is broken, not like the guard fired. Mitigation: the deny reason must name the guard and the reset time; `guard status` must state why it is tripped; `disarm` must be one obvious command.

### H4. Writing to shared, user-global config — the largest structural impact

The guard installs into files that are global and shared:

- `~/.claude/settings.json` — already holds `hooks.SessionStart` (`herdr-session.py`). A bad merge silently kills it. Claude merges hook arrays across settings levels, so our entries must append, never replace.
- `~/.codex/hooks.json` plus trust state in `~/.codex/config.toml`.
- Antigravity `.agents/hooks.json` or a plugin dir — and Antigravity's own safety text classifies `hooks.json` and `~/.gemini/config/**` as **tamper-sensitive and irreversible to modify**. Installing the guard there may trip Antigravity's own guardrails, and an agent editing them is classified as an attack. This is the one harness where the guard can make the tool *less* safe.

Also: `claude --bare` and `codex --ignore-user-config` skip our hooks, so the guard silently does not apply. Any place we claim coverage must state that caveat.

### H5. Concurrency inside the guard

Four writers call `guard_eval`: `collect` (once per live Claude session, concurrent), the 2 s tab-bar tick, the Codex cache refresh, and `arm`. At 31 ms per eval the tab tick costs ~1.5% of a core — fine — but the writers race on `decision` and `tripped`.

The prototype writes both non-atomically. A 40-way concurrent eval test left `decision` intact, but that was a 2-byte write; a six-field `tripped` line is far more exposed. **Both files need tmp + `mv`**, and the hook must tolerate a torn or empty `decision` — which it already does, by failing open. Keep that.

### H6. Tamper resistance — say this out loud

The guard is a hook listed in config that **the agent itself can write**. Claude and Codex do not protect their own hook config from the agent; only Antigravity treats it as tamper-sensitive. So this is a control against a well-behaved agent and your own forgetfulness, **not** a security boundary against an adversarial one. An agent determined to keep working can remove the guard, and on Claude and Codex nothing will stop it.

### H7. What it does not touch

- No network and no credentials on the hot path. The Claude OAuth keychain read stays on the writers, where it already is.
- No provider API calls, so it cannot cause rate-limit, quota, or auth side effects.
- No git, filesystem, or workspace writes.
- No effect on any tool that is not Claude Code, Codex, or Antigravity.
- When unarmed it is one process spawn and one `[ -f ]` test — 4.3 ms, no file reads that matter, no behaviour change.

### H8. Antigravity-specific impact

- **Best gate, worst latency.** `PreInvocation` + `terminate` is the only true zero-token pre-model gate of the three, but Antigravity runs hooks synchronously and merges them sequentially, so the guard's cost is additive on every invocation and every tool call.
- **Guardrail conflict is a genuine risk**, not a theoretical one — the vendor documents these exact files as safety controls.
- **Unverifiable here.** The account is refused for location, quota returns 403. Any Antigravity work is written blind against `docs/hooks.md` until that changes.
- Prefer a **plugin** (`agy plugin install`, `plugins/<name>/hooks.json`) over editing `.agents/hooks.json` or `~/.gemini/config/**`, because the plugin path is the documented distribution route and is less likely to look like tampering.
