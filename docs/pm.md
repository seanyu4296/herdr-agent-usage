# Project management, locally

Files are the source of truth; git history is the log. No tracker service, no board, nothing to keep in sync.

## Layout

| Path | Holds |
| --- | --- |
| [`PLAN.md`](../PLAN.md) | The hub: epics table, per-epic task checklists, blocked, ideas, shipped |
| `docs/<name>-spec.md` | Design for one epic, when the design is non-trivial. "Status:" line at the top |
| `docs/<name>-findings.md` | The evidence log for that spec: what was executed on this machine, what remains unverified |
| `docs/usage-sources.md` | Reference: which provider exposes which meter, and how to read it |

A spec and its findings stay separate on purpose. The spec is the claim; the findings are the proof. A design statement that has not been executed is labelled **UNVERIFIED** rather than left to read as fact.

## Statuses

`idea` → `parked` → `draft` → `in progress` → `shipped`, plus `blocked` as an overlay. Only two of these need a place: shipped epics and blocked items are listed explicitly so neither rots silently.

- **idea** — a bullet under Ideas in `PLAN.md`, one line plus the trigger that would make it worth building
- **parked** — an idea with a design worked out but no reason to build it yet
- **draft** — an epic row plus a spec file, not implemented
- **in progress** — an epic row with unchecked tasks
- **shipped** — a line in Shipped with the commit hash; tasks stay checked for the record
- **blocked** — a Blocked entry stating what is blocking it and what would unblock it

## Adding things

**An idea.** One bullet under Ideas in `PLAN.md`, with the trigger. "Nice someday" is not a trigger; "when X becomes true" is.

**An epic.** Promote an idea: add a row to the Epics table, add a section with a short checklist, and write `docs/<name>-spec.md` if the design needs more than a few lines. Keep the checklist to roughly ten items — detail belongs in the spec.

**A task.** A checkbox under its epic. If it needs a paragraph of explanation, it is either a new epic or a spec section.

**A blocker.** A Blocked entry naming the blocker, the evidence for it, and what would clear it. Blocked items keep their epic row so the epic does not look finished.

**A ship.** A Shipped line with the date and commit hash, and tick the tasks it completes.

## Rules

- **Evidence is separated from design** and marked VERIFIED or UNVERIFIED. Quote the command output that establishes a claim, not a summary of it.
- **No secrets, tokens, personal email addresses, or internal hostnames.** This repo is public. Provider *names* are fine; endpoints that identify an employer's infrastructure are not.
- **Ideas cost nothing until they have a trigger.** The parked pi reader is the model: the design is recorded, the trigger is stated, no code exists.
- **Rejected options get recorded**, not deleted, so the same ground is not re-covered. The glyph-instead-of-words entry exists for that reason.

## Relationship to the skills

- `step-tracker` — for a multi-PR rollout with phases, owners and dependency gates; heavier than this, and worth it only then
- `create-sub-issues` — when an epic should also exist as GitHub sub-issues under a parent
- `quick-spec` — to turn a rough feature list into a spec file, which then slots in as an epic

## Optional tooling, not built

A `bin/pm` helper could add, list and close items from the shell (`pm idea "…"`, `pm task add <epic> "…"`, `pm blocked`, `pm ship <epic> <hash>`) by editing these files. Worth building only if editing markdown by hand becomes the friction — the files work today without it.
