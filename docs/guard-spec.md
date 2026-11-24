# Usage guard — spec

Status: draft for review. Not implemented.
Scope: `herdr-agent-usage`, new `guard` subsystem. Extends the existing plugin; no new repo, no new plugin.
Verification evidence for every assumption below: `docs/guard-findings.md`.

## 1. Problem

Subscription quota is discovered after it is spent. `herdr-agent-usage` reports Claude and Codex usage, but nothing acts on it. A long unattended run can cross a self-imposed line and keep going until the provider's hard wall, at which point work fails mid-flight.

Goal: let the user declare a trip line per provider window ("Claude weekly 40%"), and have every Claude Code, Codex, and Antigravity agent in the fleet **stop at a turn boundary** when that line is crossed — without killing processes, losing sessions, or spending quota to find out.

## 2. Non-goals (v1)

Explicitly cut. Do not build:

- `guard run -- <cmd>` process supervisor. The hook covers Claude and Codex, which is the entire fleet. pi does not consume their quota.
- Interrupt / `herdr agent send-keys Escape` path. It loses the in-flight turn; the hook does not.
- A guard dashboard pane. Tab-bar marker plus `guard status` is enough.
- Slack, webhooks, notification-channel abstraction.
- A daemon or watcher process.
- Herdr `[[events]]` hooks. The validated event surface is lifecycle-shaped (`pane.updated`, `pane.focused`, `worktree.created`); there is no usage event.
- Per-pane scoping. Quota is account-scoped, so the guard is account-scoped.
- Claude-only alerting niceties. `herdr_agents_tracker` already ships threshold alerts, `status --check` exit codes, and auto-resume; Claude Code itself has built-in quota auto-resume. The only reason this subsystem exists is **enforcement**.

## 3. Verified baseline

Measured on this machine, 200 invocations each:

| Path | ms per tool call |
| --- | --- |
| bare `bash` spawn floor | 2.89 |
| hook: 1 file read + integer compare | 4.75 |
| hook: fast exit when unarmed | 4.34 |
| hook via `jq` | 7.13 |
| `find` + loop over `profiles/*.json` | 9.56 |
| codex reader, warm cache | 36.0 |
| codex reader, cold (`codex app-server` boot) | 363 |

Consequences that constrain the design:

- The hook must read **only precomputed files**. No `jq`, no `find`, no `python3`, no network, no profile clustering.
- All expensive work stays in writers that already run on their own schedule.
- Cost per turn is `tool_calls × 4.8 ms`. A 100-tool-call turn costs 0.5 s inside a multi-minute turn. Acceptable. It stays acceptable only under the rule above.

Vendor surfaces confirmed:

- Claude Code `PreToolUse` and `UserPromptSubmit` can block, with `permissionDecision: "deny"` + `permissionDecisionReason` (or exit code 2 + stderr). Claude has **no** pre-model-request hook. `PostToolBatch` fires before the next model call but is context-only and cannot block. `EndConversation` calls skip `PreToolUse`.
- Codex 0.171.0 has `preToolUse` with the same `permissionDecision` / `permissionDecisionReason` wire, `userPromptSubmit`, `permissionRequest` (with an `interrupt` field), and `preModelRequest`. Hooks require trust via `~/.codex/config.toml` `[hooks.state]`.
- Claude hooks run inside subagents too, so a fleet is covered by one hook.
- Claude usage only refreshes when a `statusLine` fires (`refreshInterval: 60`). Detection lag is up to ~60 s and per-turn jumps are lumpy.

## 4. Decisions

| # | Decision | Rationale |
| --- | --- | --- |
| D1 | Extend `herdr-agent-usage`; guard code in new files | The readers, profile clustering, and pane→session mapping already exist. A second plugin would re-derive them or couple to a private state layout. |
| D2 | Enforcement is agent hooks, not process kill | Both agents support a deny decision. The agent parks with session and context intact, and can be resumed after reset. |
| D3 | Account-scoped, not per-pane | The weekly limit is shared. Once tripped, a pane started 10 minutes later is denied at its first tool call. That is the desired behaviour. |
| D4 | Latch per `(provider, window)`, sticky | The raw percentage flaps (stale payload, profile switch, window roll). A latch gives one clean stop and one alert per trip. |
| D5 | Default re-arm `--until reset`; `--until manual` optional | Matches the domain: quota windows reset, they do not recede. |
| D6 | Fail-open entering, never fail-out | Stale data must not trip the guard; stale data must not un-trip it. |
| D7 | Two state files, not one | `policy.json` is written rarely, `usage.json` often. One merged file would need a merge on every frequent write and can clobber policy. |
| D8 | The hook reads one precomputed verdict file | Keeps the hot path at ~4.8 ms. Writers compute the verdict, the hook only reads it. |
| D9 | Alert via `herdr notification show`, once per trip | One line, existing API, `--sound request`. |
| D10 | Threshold is a trip line, not a cap | ~60 s lag plus lumpy jumps means 40% can land at ~50%. Arm with headroom. |
| D11 | Codex parity is gated on a spike | Two unknowns (§9). Ship Claude first regardless. |
| D12 | Keep the CLI runnable without herdr | The plugin is packaging. Agents and scripts call the binary directly. |

## 5. State and data contract

All under the existing `$STATE_DIR` (`HERDR_PLUGIN_STATE_DIR`, default `~/.local/state/herdr/plugins/herdr-agent-usage`), new `guard/` subdirectory, mode 700.

### `guard/policy.json` — written by `arm` / `disarm` only

```json
{
  "armed": true,
  "armed_at": 1796032800,
  "until": "reset",
  "scope": "account",
  "rules": [
    { "provider": "claude", "window": "seven_day", "threshold": 40 },
    { "provider": "codex",  "window": "five_hour", "threshold": 80 }
  ]
}
```

`window` accepts the plugin's existing keys: `five_hour`, `seven_day`, `seven_day_<model>`, `week:<Name>`, `spend`. CLI aliases: `5h` → `five_hour`, `wk` → `seven_day`.

### `guard/usage.json` — written by the existing writers

```json
{
  "ts": 1796032860,
  "claude": {
    "profile": "1796032800",
    "windows": {
      "five_hour": { "pct": 12, "resets_at": 1796035000 },
      "seven_day": { "pct": 41, "resets_at": 1796032800 }
    }
  },
  "codex": {
    "windows": {
      "five_hour": { "pct": 24, "resets_at": 1795527077 },
      "seven_day": { "pct": 1,  "resets_at": 1796120196 }
    }
  }
}
```

Derived from the existing readers: `windows()` over the primary profile file for Claude, and `bin/codex-limits.py` output for Codex. No new data sources.

### `guard/decision` — the hook's only read. Flat, one line, pure bash.

```text
ok
```

or, when tripped:

```text
tripped<TAB>claude<TAB>seven_day<TAB>41<TAB>40<TAB>1796032800
```

Field order: `verdict`, `provider`, `window`, `pct`, `threshold`, `resets_at`. Verdicts: `ok`, `tripped`, `stale`, `unarmed`.

The hook does not parse JSON. It reads this file, takes field 1, and if it is not `ok` builds the deny reason from fields 2–6.

### `guard/log` — append-only trip record

```text
1796032860	claude	seven_day	41	40	1796032800	tripped
1796032861	claude	seven_day	41	40	1796032800	notified
```

Answers "did it actually stop anything", after the fact.

### Latch state

Latch lives in the decision file plus one extra file, `guard/tripped` — one line per latched `(provider, window)`:

```text
claude	seven_day	1796032800
```

Sticky. Cleared only when `until = reset` and the stored `resets_at` has passed, or by `disarm`.

### Writers that call `guard_eval`

`guard_eval` recomputes `usage.json` → `decision` → latch transitions → notification. Called from:

1. `collect` — after writing a Claude profile (runs whenever any Claude session is alive).
2. `codex_windows` — after refreshing the Codex cache.
3. `bar` — the tab-bar tick, every 2 s. Catches resets and stale→fresh transitions.
4. `guard arm` — immediately, so arming below the current number trips at once.

`guard_eval` must stay under ~50 ms and must never block on network. `fetch_api` stays backgrounded where it already is.

## 6. Latch state machine

Per `(provider, window)`:

```text
          arm                  observed pct >= threshold
   idle ───────► armed ─────────────────────────────────► tripped
                  ▲                                        │
                  │   until=reset AND resets_at passed     │
                  └────────────────────────────────────────┘
                    or disarm
```

- `tripped` is sticky. A lower reading does not clear it.
- `tripped` blocks every pane on the account, including new panes.
- Latch is per window. `claude seven_day` tripped does not block `claude five_hour`, and does not touch `codex`.
- Notification fires once per trip, on the `armed → tripped` edge only.

## 7. Failure modes

| Condition | Behaviour |
| --- | --- |
| Not armed | allow (4.3 ms) |
| Armed, fresh, below threshold | allow |
| Armed, fresh, at or above threshold | trip → deny, latch, notify once |
| Armed, stale data | **allow** + warn once (fail-open) |
| Tripped, data stale | **deny** (latch wins) |
| Tripped, `until=reset`, `resets_at` passed | clear latch → armed |
| `policy.json` missing or corrupt | treat as unarmed, log |
| `usage.json` missing or corrupt | treat as stale |
| `decision` missing | treat as unarmed |
| Hook times out | agent proceeds; `timeout` set to 5 s, expected runtime <10 ms |

## 8. Interfaces

### CLI

```sh
herdr-agent-usage guard arm [--claude WINDOW=PCT]... [--codex WINDOW=PCT]... \
                             [--until reset|manual] [--scope account|provider]
herdr-agent-usage guard disarm
herdr-agent-usage guard status [--json]
herdr-agent-usage guard check  [--json]     # exit 0 ok · 10 tripped · 20 stale · 30 unarmed
herdr-agent-usage guard eval                # internal, called by writers
herdr-agent-usage guard hook claude PreToolUse        # hook entrypoint, argv-supplied event name
herdr-agent-usage guard hook claude UserPromptSubmit
herdr-agent-usage guard hook codex preToolUse
herdr-agent-usage guard hook codex userPromptSubmit
herdr-agent-usage guard install-hooks   [--agent claude|codex|all]
herdr-agent-usage guard uninstall-hooks [--agent claude|codex|all]
herdr-agent-usage guard log [--tail N]
herdr-agent-usage json                      # machine-readable snapshot for agents
```

The event name is passed as argv so the hook never parses its stdin payload.

Example:

```sh
herdr-agent-usage guard arm --claude wk=40 --until reset
```

### Hook output

Tripped, Claude `PreToolUse`:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "usage guard: claude weekly 41% >= 40% (resets Mon 5:00pm). Stop now and report where you got to."
  }
}
```

Tripped, Claude `UserPromptSubmit`:

```json
{
  "decision": "block",
  "reason": "usage guard: claude weekly 41% >= 40% (resets Mon 5:00pm). Do not start new work."
}
```

Codex uses the same `permissionDecision` shape for `preToolUse`. Codex rejects `permissionDecision: "allow"`; we never emit it. Exit 0 with no output means no decision.

The reason string must include the reset time and an explicit instruction to stop. An agent that is told why converges in 1–2 model calls; an agent that is told nothing retries.

### Hook installation

Claude, `~/.claude/settings.json`. Merge into the existing `hooks` object — the file currently holds `hooks.SessionStart` (`herdr-session.py`) and that entry must survive untouched:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "*", "hooks": [
        { "type": "command", "command": "'<bin>' guard hook claude PreToolUse", "timeout": 5 }
      ]}
    ],
    "UserPromptSubmit": [
      { "hooks": [
        { "type": "command", "command": "'<bin>' guard hook claude UserPromptSubmit", "timeout": 5 }
      ]}
    ]
  }
}
```

No `if` condition: we want every tool. `matcher: "*"` (or omitted) matches all.

Codex, `~/.codex/hooks.json`, same nesting with `preToolUse` / `userPromptSubmit`, plus the trust entry in `~/.codex/config.toml` `[hooks.state."<path>:<event>:0:0"]`.

Reversibility, following the existing `configure` / `uninstall` precedent:

- Back up before writing: `~/.claude/settings.json.bak-usage-guard`, `~/.codex/hooks.json.bak-usage-guard`.
- Every entry we add carries a `# usage-guard` marker where the format allows, and uninstall removes exactly our entries by command path.
- Uninstall restores byte-identical files when it was the only writer; otherwise it strips only our entries.
- `guard status` reports installed/uninstalled state.

### Config

Existing `$CONFIG_DIR/config`, sourced shell, same style as the current keys:

```sh
GUARD=1                    # 0 disables guard_eval entirely
GUARD_NOTIFY=1             # 0 disables the trip notification
GUARD_NOTIFY_SOUND=request # none | done | request
```

Thresholds live in `policy.json`, not here — they are state, not configuration.

## 9. Spike before phase 3 (30 minutes)

Blocking questions for Codex:

1. Does `preToolUse` with `permissionDecision: "deny"` actually block a tool call in codex 0.171.0?
2. Does `preModelRequest` block? It has no dedicated output wire in the binary, only the generic `decision:block` path. If it does block, it is strictly better than the tool boundary — it stops mid-turn with zero extra tokens.
3. Can the hook trust hash be written programmatically, or does it require interactive approval in `codex`?

Exit criteria: a decision to keep Codex in phase 3 or drop it to a follow-up.

## 10. Phases and acceptance

### Phase 0 — spike (30 min)

**Done.** See `docs/guard-findings.md` §A. Claude and Codex both block at the tool boundary; Codex `preModelRequest` does not; costs measured. One verification task remains (Claude `UserPromptSubmit`, documented but untested).

Antigravity's remaining spike is in `docs/guard-findings.md` §D4 and is blocked on an eligible account.

### Phase 1 — decision engine, no hooks

`guard arm|disarm|status|check|eval`, the three state files, latch, notification, `guard log`. Includes a test override: `GUARD_USAGE_FILE=/tmp/fake.json` and `GUARD_STATE_DIR` so tripping can be exercised without burning real quota.

Accept:

- Fake usage 41%, rule 40% → `guard check` exits 10, `guard status` shows tripped, `guard/log` has one line.
- Fake usage 39% → exits 0.
- Stale `ts` while armed → exits 20 and allows.
- Stale `ts` while tripped → still denies.
- `until=reset` with `resets_at` in the past → latch clears, exits 0.
- `guard eval` under 10 ms; `decision` file under 200 bytes.

### Phase 2 — Claude hooks

`install-hooks` / `uninstall-hooks` for Claude, reversibly. Use for a week before touching Codex.

Accept (this is the definition of done for v1):

> `guard arm --claude wk=40`, spawn a Claude pane, let weekly reach 40%. The agent's next tool call is denied with the reset time in the reason. One herdr toast fires. `guard status` shows `tripped`. After the window resets the agent works again, with no intervention.

Plus:

- `~/.claude/settings.json` still contains the pre-existing `hooks.SessionStart` entry.
- `uninstall-hooks` restores the file byte-identical to the backup.
- Measured hook cost stays under 10 ms (`time` over 200 invocations).

### Phase 3 — Codex hooks

Only if phase 0 passed.

Accept: a Codex pane is denied at its next tool call; trust step documented; uninstall restores `hooks.json` and removes the trust entry.

### Phase 4 — Antigravity hooks

Different contract, same core. Primary gate is `PreInvocation` + `terminationBehavior: "terminate"`, which stops before the model call at zero token cost; `PreToolUse` + `decision: "deny"` is the backstop. Install through `agy plugin install` rather than editing `.agents/hooks.json` or `~/.gemini/config/**`, which Antigravity treats as tamper-sensitive. The reader already exists (`bin/agy-usage.py`).

Accept: an Antigravity pane is refused before its model call when tripped, and the user sees the reason. **Cannot be verified until the account is eligible by location** — see `PLAN.md` → Blocked.

### Phase 5 — polish, only if missed

Tab-bar tripped marker, `guard status --json` consumed by the dashboard, README section, agent skill so agents know to call `guard check` before long runs.

## 11. Testing

New `tests/guard.sh`, plain shell with asserts, no framework. Every case runs against a temp state dir and a fake usage file. Cases map 1:1 to the phase 1 acceptance list plus the failure-mode table in §7. Add one case asserting `settings.json` is byte-identical after install-then-uninstall.

## 12. Open questions

- Exact JSON shape for `UserPromptSubmit` blocking — `decision: block` + `reason`, or `hookSpecificOutput` + `hookSpecificOutput.permissionDecision`. Verify at implementation; exit code 2 + stderr is the documented fallback for both events.
- Whether Claude's `PreToolUse` denial is reported to the user as a visible error or silently to the model. Affects the reason wording.
- Whether `guard_eval` from the 2 s tab-bar tick is too chatty when several panes are focused. Cheap to measure in phase 1.
