# Plan

What is shipped, in flight, blocked, and parked. Last updated 2026-11-24.

## Epics

| # | Epic | Status |
| --- | --- | --- |
| 1 | Claude Code usage | shipped |
| 2 | Codex usage | shipped |
| 3 | Antigravity usage | shipped, one task blocked |
| 4 | Usage guard | spec verified, not implemented |

All three readers share the focused-pane dispatch and the bar/dashboard renderer, shipped with the first epic (`4711655`).

### Epic 1 — Claude Code usage

- [x] statusLine collector, chaining to whatever was installed before
- [x] Per-account profile clustering; the 5h window survives a payload that omits it
- [x] Dashboard: bars, reset countdowns, extra-usage spend, other profiles
- [x] Weekly reset shown in the tab bar next to the 5h reset
- [x] Optional OAuth usage-API fetch for per-model windows (macOS keychain)
- [ ] `configure` refreshes stale checkout paths instead of refusing when its marker is present — every `herdr plugin update` moves the checkout, so today each release needs `uninstall` then `configure` by hand to repoint `config.toml` and the Claude `statusLine`

Output: `Claude used · 5h 5% ↻7:30pm · wk 21% ↻Mon 5:00pm`

### Epic 2 — Codex usage

- [x] Read `account/rateLimits/read` over `codex app-server` stdio
- [x] Window labels from `windowDurationMins` (300 → `5h`, 10080 → `wk`)
- [x] Cache with a 2-minute refresh gate; a failed read keeps the last good value

Output: `Codex used · 5h 24% ↻8:31pm · wk 1% ↻Tue 5:16pm`

### Epic 3 — Antigravity usage

- [x] `agy -p "/usage" --output-format json` reader; remaining fraction → percent used
- [x] Cache-only tab bar with a detached background refresh (the CLI takes 2.6s per call)
- [x] Explicit failure states instead of silence: `ineligible`, `unauthenticated`, `pending`, raw error
- [x] Tab bar carries the primary model group; the dashboard carries every bucket
- [ ] Verify the shape of a successful `/usage` response — blocked, see Blocked
- [x] Source row and endpoint documented in [`docs/usage-sources.md`](docs/usage-sources.md)

### Epic 4 — Usage guard

Goal: declare a trip line per provider window ("Claude weekly 40%") and have every Claude Code, Codex, and Antigravity agent stop at a turn boundary when it is crossed.

Spec: [`docs/guard-spec.md`](docs/guard-spec.md). Evidence: [`docs/guard-findings.md`](docs/guard-findings.md).

- [x] Verify hook blocking on Claude Code (`PreToolUse` deny) and Codex (`PreToolUse` deny, `UserPromptSubmit` block)
- [x] Verify Codex `preModelRequest` does not block — dropped from the design
- [x] Measure the hot path: 6.8 ms per tool call; three "never do this in the hook" rules
- [x] Decision-engine prototype, 20/20 against the failure-mode table
- [x] Confirm the Antigravity hooks contract from the CLI's bundled `docs/hooks.md`
- [ ] Close two design defects found while testing: the latch is not keyed by account, so one account's trip blocks another; `--until reset` cannot clear an unknown `resets_at`, so a trip can stick invisibly
- [ ] Review the spec
- [ ] Phase 1 — decision engine: `bin/guard.sh`, `policy.json` / `usage.json` / `decision`, latch, `guard arm|disarm|status|check`
- [ ] Phase 2 — Claude hooks plus a reversible installer; use it for a week before going further
- [ ] Phase 3 — Codex hooks (trust approval is interactive, not scriptable)
- [ ] Phase 4 — Antigravity hooks: `PreInvocation` + `terminate` as the primary zero-token gate, `PreToolUse` + `deny` as backstop
- [ ] Verification task: Claude `UserPromptSubmit` block is documented but untested

## Blocked

- **The successful Antigravity `/usage` response is unverified** (task in Epic 3). Google refuses the signed-in account by location, and the quota backend answers `403 PERMISSION_DENIED`, so there is no quota to read and `parse_quota` runs only against a synthetic fixture. Unblocks with an eligible account or a VPN. Until then the `agy` tab-bar slot stays blank and the dashboard states the reason.
- **Antigravity guard hooks are unverifiable for the same reason.** The hooks contract is confirmed from the CLI's bundled `docs/hooks.md`, but no hook has been executed. Epic 4 phase 4 is written blind and its acceptance criteria cannot be met until an eligible account exists.

## Ideas

Nothing here is committed to. Each carries the trigger that would make it worth building.

- **pi usage reader** — parked. Trigger: pi usage stops being free to me, the LiteLLM key gains budget read access, or I start checking provider dashboards by hand.
  Design: spend from pi's own session logs, which record `provider`, `model`, `usage.cost` and a timestamp per assistant turn. Tab bar shows today's total; dashboard shows per-model rows; an optional daily budget turns it into `percent ↻midnight` using the existing renderer. Verified: no duplicate records across 83 session files, so resume and fork do not double count; full-corpus scan is 0.14s. Caveats: pi's price-table estimate rather than the invoice, and plan-covered models record `$0.00`.
- **Antigravity offline spend** — token counts live in `~/.gemini/antigravity*/conversations/*.db` as protobuf blobs. Heavy to decode; only worth it if quota stays unavailable.
- **Direct quota read for Antigravity** — call the Code Assist `retrieveUserQuotaSummary` endpoint with the CLI's own token instead of shelling out.
- **Other harness adapters** — OpenCode Go usage API, Copilot SDK quota, Gemini CLI (activity only). Per-provider notes in [`docs/usage-sources.md`](docs/usage-sources.md).
- **`doctor` command** — print the per-provider resolution table: which meter matched, which did not, and why.
- **Glyph instead of words** — `✳` or a per-agent mark in place of "Claude used". Dropped for now in favour of words.

## Shipped

- 2026-11-24 — released v0.2.0: Claude Code and Codex usage, tested against live accounts
- 2026-11-24 — local plan hub (`c2a842f`)
- 2026-11-24 — Antigravity reader with failure states and cache-only tab bar (`d1948ec`)
- 2026-11-24 — focused-pane dispatch, Claude Code and Codex readers (`4711655`)
- 2026-11-24 — fork from upstream `herdr-claude-usage` 0.1.1 (`4711655`)
