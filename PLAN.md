# Plan

Local project management for this repo: what is shipped, in flight, blocked, and parked.
Conventions in [`docs/pm.md`](docs/pm.md). Last updated 2026-11-24.

## Epics

| # | Epic | Status | Detail |
| --- | --- | --- | --- |
| 1 | Focused-agent usage — Claude Code, Codex, Antigravity | shipped; one reader blocked upstream | [README](README.md), [sources](docs/usage-sources.md) |
| 2 | Usage guard — stop agents at a self-imposed quota line | draft, not implemented | [spec](docs/guard-spec.md), [findings](docs/guard-findings.md) |

### Epic 1 — Focused-agent usage

Goal: the tab bar and dashboard report subscription usage for whichever harness the focused pane runs, as percent used, with reset times.

- [x] Focused-pane dispatch (`HERDR_ACTIVE_PANE_ID` + `herdr pane get`)
- [x] Claude Code reader — statusLine payload, profile clustering, dashboard
- [x] Codex reader — `codex app-server` rate limits, cached
- [x] Antigravity reader — `agy -p "/usage"`, cache-only bar, background refresh, explicit failure states
- [ ] Verify the shape of a successful Antigravity `/usage` response — blocked
- [ ] pi reader — parked, see Ideas

Observed output: `Claude used · 5h 5% ↻7:30pm · wk 21% ↻Mon 5:00pm`,
`Codex used · 5h 24% ↻8:31pm · wk 1% ↻Tue 5:16pm`,
`Antigravity → not available for this account`.

### Epic 2 — Usage guard

Goal: declare a trip line per provider window ("Claude weekly 40%") and have every Claude Code and Codex agent stop at a turn boundary when it is crossed. Owned by the guard spec; this table only tracks its status.

- [ ] Review `docs/guard-spec.md` (draft)
- [ ] Implement v1 after review

## Blocked

- **Antigravity quota is unreadable on the current account.** Google refuses the signed-in account by location, and the quota backend answers `403 PERMISSION_DENIED`, so no quota exists to read. Nothing to configure. Unblocks with an eligible account or a VPN. Until then the `agy` tab-bar slot stays blank and the dashboard states the reason.

## Ideas

Nothing here is committed to. Each carries the trigger that would make it worth building.

- **pi usage reader** — parked. Trigger: pi usage stops being free to me, the LiteLLM key gains budget read access, or I start checking provider dashboards by hand.
  Design: spend from pi's own session logs, which record `provider`, `model`, `usage.cost` and a timestamp per assistant turn. Tab bar shows today's total; dashboard shows per-model rows; an optional daily budget turns it into `percent ↻midnight` using the existing renderer. Verified: no duplicate records across 83 session files, so resume and fork do not double count; full-corpus scan is 0.14s. Caveats: pi's price-table estimate rather than the invoice, and plan-covered models record `$0.00`.
- **Antigravity offline spend** — token counts live in `~/.gemini/antigravity*/conversations/*.db` as protobuf blobs. Heavy to decode; only worth it if quota stays unavailable.
- **Direct quota read for Antigravity** — call the Code Assist `retrieveUserQuotaSummary` endpoint with the CLI's own token instead of shelling out, which costs 2.6s per call.
- **Other harness adapters** — OpenCode Go usage API, Copilot SDK quota, Gemini CLI (activity only). Notes per provider in [`docs/usage-sources.md`](docs/usage-sources.md).
- **`doctor` command** — print the per-provider resolution table: which meter matched, which did not, and why.
- **Glyph instead of words** — `✳` or a per-agent mark in place of "Claude used". Dropped for now in favour of words.

## Shipped

- 2026-11-24 — Antigravity reader with failure states and cache-only tab bar (`d1948ec`)
- 2026-11-24 — focused-agent usage for Claude Code and Codex (`4711655`)
- 2026-11-24 — fork from upstream `herdr-claude-usage` 0.1.1 (`4711655`)
