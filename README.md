# herdr-agent-usage

Subscription usage for the coding agent in the **focused** Herdr pane, in one tab-bar entry. Claude Code and Codex are supported; both are shown as percent **used**, the direction the providers report.

```text
Claude used · 5h 39% ↻2:30pm · wk 18% ↻Mon 5:00pm
Codex used · 5h 24% ↻3:11pm · wk 1% ↻Fri 3:36pm
```

## Features

- **Follows the focused pane.** Herdr exposes the active pane to custom commands as `HERDR_ACTIVE_PANE_ID`; the plugin resolves it with `herdr pane get` and picks the reader for the agent that pane runs (`claude` or `codex`). No focused agent, or an agent without a reader, renders nothing.
- **Tab-bar summary**, always visible: session window and weekly window with their reset times; further windows (per-model weeklies, extra-usage credits) as percent only, so the bar keeps its width. A percentage above 80 gets a `!!` suffix; a trailing `⁺` means another signed-in Claude profile is also active.
- **Popup dashboard** on a keybinding: severity-colored bars with a threshold tick, reset countdowns (`↻ 33m · 2:30pm`), extra-usage spend with amounts, active session count, one compact line per other signed-in Claude profile. Any key refreshes, auto every 30s, `q` closes.
- **No credentials for the core data.** Claude data is pushed by Claude Code's own `statusLine` hook; Codex data comes from the local `codex app-server` over stdio. An optional macOS-only Claude usage-API fetch adds per-model windows and spend.
- **Reversible install**: the statusLine wrapper chains to whatever was installed before and restores it on uninstall; every `config.toml` line it writes carries a `# herdr-agent-usage` marker.

## Requirements

Herdr 0.8+, `bash`, `jq`, `curl`. Codex support additionally needs `python3` and the `codex` CLI on `PATH`. macOS or Linux; the optional Claude usage API is macOS-only.

## Installation

```sh
herdr plugin install seanyu4296/herdr-agent-usage
herdr plugin action invoke herdr-agent-usage.configure
```

That is the whole setup. `configure` wraps the `statusLine` in `~/.claude/settings.json` (backing it up and chaining to whatever was there), writes the tab-bar entry and the `prefix+u` dashboard keybinding into Herdr's `config.toml` (backed up; rolled back automatically if Herdr rejects the result), and reloads the server. Claude data appears within a minute of any Claude Code session running. Codex data needs no setup; it is read on demand.

Herdr's plugin manifest cannot declare tab-bar entries or keybindings, which is why a configure step exists at all. If you prefer to manage `config.toml` yourself, skip the parts you own; `configure` never touches an existing `tab_bar_right` and prints the entry to add instead.

<details>
<summary>Manual setup (what configure writes)</summary>

```toml
[ui]
tab_bar_right = [
  { type = "command", command = "bash /path/to/herdr-agent-usage/bin/herdr-agent-usage bar", interval_seconds = 2, timeout_seconds = 8 },
]

[[keys.command]]
key = "prefix+u"
type = "popup"
command = "bash /path/to/herdr-agent-usage/bin/herdr-agent-usage dashboard"
width = 64
height = 20
```

Then `herdr server reload-config`.
</details>

## Usage

Focus a Claude Code or Codex pane and the tab bar shows that agent's usage. `prefix+u` opens the dashboard:

```text
  ✳ Claude usage (% used)   12s ago · 8 session(s) · Europe/Prague

  Session (5h)                ↻ 33m · 2:30pm
  ████████████████████████░░░┊░░░░░░  71%

  Week · all models     ↻ 1d22h · Mon 5:00pm
  ███████████░░░░░░░░░░░░░░░░┊░░░░░░  33%

  Week · Fable          ↻ 1d22h · Mon 5:00pm
  ████████████░░░░░░░░░░░░░░░┊░░░░░░  38%

  Extra usage                €260 of €300
  █████████████████████████████░░░░░  87%

  ◦ 5h 4% · wk 54% · other profile (1 session(s) · rover)

  q close · any key refresh · auto 30s
```

Bars are lavender below 50%, amber from 50%, red from 80%; the faint `┊` tick marks where red begins.

## Configuration

Optional `config` file in the plugin config dir (`herdr plugin config-dir herdr-agent-usage`), shell syntax. The same variables work as environment overrides.

```sh
USE_API=1        # 0 disables the Claude OAuth usage API fetch
BAR_HOT=80       # tab-bar '!!' suffix and dashboard red above this
BAR_WARN=50      # dashboard amber from this
STALE_SECS=1800  # how long a Claude profile counts as fresh
CODEX_BIN=codex  # codex binary used for the rate-limits read
```

## How it works

Three independent pieces:

1. **Focused-pane dispatch.** The tab-bar command gets `HERDR_ACTIVE_PANE_ID`, and `herdr pane get <pane_id>` returns the agent Herdr detects in that pane. `bar` and `dashboard` switch readers on that value.
2. **Claude: statusLine push (no credentials).** Claude Code invokes the configured `statusLine` command with a JSON payload on stdin that includes `rate_limits`. This plugin's `collect` captures it and chains to whatever statusLine command was installed before, passing stdin and stdout through untouched. Percentages come from `used_percentage`; reset times from `resets_at`.
3. **Codex: local app-server read.** `bin/codex-limits.py` starts `codex app-server --listen stdio://`, sends `initialize`, `initialized`, then `account/rateLimits/read`, and reads `usedPercent` plus `resetsAt` from each bucket's primary and secondary window. The window label comes from `windowDurationMins` (300 → `5h`, 10080 → `wk`). Results are cached for 15 minutes, with a refresh at most every 2 minutes; a failed read leaves the last good cache in place.

**Claude: several accounts.** Sessions signed into different accounts or organizations report different limits, so payloads are clustered into profiles keyed by their weekly reset time. The profile whose weekly reset matches the usage API response is the logged-in account and is shown as primary; without API data, the profile with the most active sessions wins. Profiles quiet for 30 minutes are dropped from the display.

**Claude: the 5h reading never disappears.** Claude Code sometimes omits the `five_hour` window from a payload; the previous unexpired window is kept. When the window has genuinely expired, the displays show `5h 0%`.

**Claude: optional OAuth usage API (macOS only).** Per-model weekly windows (e.g. Fable) and extra-usage credits exist only in the official usage endpoint. The plugin reads your own Claude Code OAuth token from the macOS keychain (first use triggers a keychain permission prompt) and fetches at most every 5 minutes, backing off failures for the same window. The token never leaves the process; only the usage JSON is cached. On Linux the Claude side runs on statusLine data alone.

## Commands

| Command | Purpose |
| --- | --- |
| `collect` | statusLine hook (invoked by Claude Code; captures payload, chains onward) |
| `bar` | one-line tab-bar summary for the focused pane's agent |
| `dashboard` | interactive popup with bars |
| `draw [claude\|codex]` | one-shot render (debugging; defaults to the focused pane) |
| `configure` / `uninstall` | install/remove the statusLine wrapper and config entries, reversibly |

## Troubleshooting

- **Tab bar is empty**: the focused pane runs no agent Herdr recognizes, or one without a reader. Focus a Claude Code or Codex pane.
- **Tab bar shows `Claude —`**: no Claude Code session has reported for 30 minutes. Open or use any session; data lands within a minute.
- **Dashboard says rate limits are unavailable**: Codex returned no bucket, usually a sign-in problem. Run `codex` once and check the account, then reopen the dashboard.
- **No Fable / extra-usage entries**: the Claude usage API needs the macOS keychain. Approve the keychain prompt on first fetch, or check `USE_API` is not `0`. On Linux these entries are unavailable.
- **A keychain dialog appeared**: that is the first usage-API fetch reading your own Claude Code OAuth token. "Always Allow" stops it from asking again.
- **Percentages look uncolored in the tab bar**: expected. The tab bar renders no ANSI colors; `!!` above 80 is the only marker there. The dashboard has the colors.

## Uninstall

```sh
herdr plugin action invoke herdr-agent-usage.uninstall
herdr plugin uninstall herdr-agent-usage
```

The uninstall action restores the previous statusLine and removes every `config.toml` line it added (they all carry a `# herdr-agent-usage` marker).

## Credits

Derived from [anyaachan/herdr-claude-usage](https://github.com/anyaachan/herdr-claude-usage) (MIT), which provides the Claude statusLine collector, profile clustering, dashboard rendering, and install/uninstall flow. This fork adds focused-pane dispatch, the Codex app-server reader, and percent-used labelling. See `docs/usage-sources.md` for the vendor sources behind each meter and notes on other harnesses.
