# Reccap: Claude Code daily activity log — build spec

Nov 15, 2026 · @rnjn

## Purpose and scope

Reccap turns Claude Code sessions from several machines into one daily page in an Obsidian vault, with a link from each session to a readable transcript. It serves two uses:

- **Standup prep.** One page shows everything worked on yesterday, across all machines.
- **Remembering tasks.** With many sessions open, tasks get forgotten. A daily checkpoint lists every session, so none is lost and there is no need to hunt through terminal tabs.

### Goals

- One day page per calendar day, listing every session active that day, grouped by machine and repo.
- One markdown file per session that reads as a story: prompts, replies, and a one-line note per tool call.
- No server. Machines exchange data through a private GitHub repo, which is also the Obsidian vault.
- Each machine can be set up with one install command.

### Non-goals for this version

- Carrying unfinished items forward from one day to the next.
- Guessing whether a session's task is done or still open. The reader decides that.
- Any hosted service, database, or web UI.
- Capturing sessions that run in Claude Code on the web. Only local transcripts are in scope.

## Architecture

There are three parts: a leaf command that runs on every machine, a shared git repo, and a morning command that builds the day page. Both commands ship in one CLI called `reccap`.

1. **Leaf: `reccap sync`.** Runs on a schedule on every machine where Claude Code is used. It finds session transcripts that changed since the last run, renders each to a markdown file, and pushes them to the repo.
2. **Shared repo.** A private GitHub repo that is also the Obsidian vault. Each machine writes only inside its own folder, so pushes from different machines never touch the same file.
3. **Morning: `reccap day`.** Run by hand on whichever machine is opened first. It pulls the repo, reads the frontmatter of the session files, writes the day page, and pushes it.

All model calls happen at the leaves. Each leaf writes a one-line description into the session file's frontmatter, so `reccap day` only assembles files and makes no model calls.

### Implementation constraints

- Python 3.9 or later, standard library only. No third-party packages.
- External programs: `git` and the `claude` CLI, both already present on every leaf.
- macOS and Linux are supported. Windows is out of scope unless confirmed (see open questions).
- The reading machine is also a leaf and runs both commands. A machine with no Obsidian, such as a remote dev box, runs only `reccap sync`.

## Repository and vault layout

The vault root is the git repo root. Reccap owns two folders in it and touches nothing else, so other notes can live in the same vault.

```
<vault>/
  .gitignore
  daily/
    2026-11-14.md
  sessions/
    <machine>/
      2026-11/
        2026-11-14-550e8400.md
```

- **`daily/<YYYY-MM-DD>.md`** is the day page. Only `reccap day` writes here.
- **`sessions/<machine>/<YYYY-MM>/<start-date>-<id8>.md`** is one session. `<start-date>` is the local date of the session's first entry and `<id8>` is the first 8 characters of the session ID. The name never changes after creation, so links stay valid. Only `reccap sync` on that machine writes here.
- **`.gitignore`** must contain `.obsidian/workspace*.json` and `.trash/`. The installer adds these lines if they are missing.

Each machine also keeps local state outside the vault, in `~/.reccap/`:

| File | Contents |
| --- | --- |
| `config.json` | Settings for this machine (see Configuration) |
| `state.json` | Per transcript: path, size, modified time, and the description cache |
| `scratch/` | Empty working directory used when calling `claude -p` |
| `sync.log` | Rotating log of sync runs, capped at 1 MB |
| `sync.lock` | Lock file that prevents two sync runs at once |

## Leaf command: `reccap sync`

`reccap sync` is idempotent: running it twice with no new activity changes nothing and creates no commit. It runs these steps in order.

1. **Lock.** Take `~/.reccap/sync.lock`. If another run holds it, exit 0 without output.
2. **Discover.** List `*.jsonl` files one level under the transcript root, which defaults to `~/.claude/projects/`. Skip any file whose size and modified time match `state.json`. Skip subagent transcripts in nested folders. Skip the project folder that corresponds to `~/.reccap/scratch`.
3. **Parse.** Read the transcript line by line as JSON. Skip lines that fail to parse, since the last line may be half-written while a session is live. Skip entry types the parser does not know.
4. **Filter.** Drop sessions that contain no prompt typed by the user.
5. **Render.** Build the session markdown as described in the next section.
6. **Redact.** Apply the redaction rules below to the whole rendered file, frontmatter included.
7. **Describe.** Get a one-line description from `claude -p`, or reuse the cached one.
8. **Write.** Write the file through a temporary file and a rename. Skip the write if the content is byte-identical to what is on disk.
9. **Publish.** Commit and push as described under Git protocol.
10. **Save state.** Update `state.json` only for transcripts that were written successfully.

Flags: `--dry-run` prints what would be written and makes no changes. `--no-push` commits without pushing. `--since <YYYY-MM-DD>` ignores state and reprocesses transcripts modified on or after that date, for backfill.

### Transcript format

The transcript format is not a documented, stable interface. Before writing the parser, inspect several real transcripts on the build machine and confirm the field names. The fields below are what to expect, not a guarantee.

| Field | Expected meaning |
| --- | --- |
| `type` | Entry kind, such as `user`, `assistant`, or `summary` |
| `message.content` | A string, or a list of blocks of type `text`, `tool_use`, `tool_result`, or `thinking` |
| `timestamp` | ISO 8601 time in UTC |
| `sessionId` | Session ID, also the transcript file name |
| `cwd` | Working directory when the entry was written |
| `gitBranch` | Git branch when the entry was written |
| `isSidechain` | True for subagent entries, which are skipped |

Keep all knowledge of these field names in one module, so a format change needs a fix in one place. If a required field is missing from a whole transcript, log a warning with the file path and skip that transcript.

### Description step

- Build the input from the session's user prompts, each cut to 500 characters, plus the last assistant text, cut to 1,000 characters. Cap the total input at 8,000 characters, keeping the earliest and latest prompts.
- Ask for a single line of at most 100 characters that says what the session was working on, phrased as a task, with no trailing period.
- Run `claude -p` with `~/.reccap/scratch` as the working directory, a 60-second timeout, and no tools available. Check `claude --help` for the current flags to restrict tools and to avoid saving the call as a session. The scratch exclusion in step 2 must stay even if such a flag exists, or reccap will log its own description calls.
- Cache the result in `state.json`, keyed by a hash of the user prompts. Call the model again only when the session has new prompts.
- On timeout or error, use the first user prompt cut to 100 characters, set `description_source: fallback`, and try again on the next run.

### Redaction

Redaction is a best-effort pattern scrub and will miss secrets it has no pattern for. Replace each match with `[REDACTED:<kind>]`.

- Private key blocks, from the `BEGIN` line to the `END` line.
- Known token prefixes: AWS access key IDs, GitHub tokens, Slack tokens, and `sk-` style API keys.
- JSON Web Tokens and `Authorization: Bearer` values.
- Credentials embedded in URLs, as in `scheme://user:password@host`.
- Assignments where the name contains `SECRET`, `TOKEN`, `PASSWORD`, `PASSWD`, `API_KEY`, or `PRIVATE_KEY`. Redact the value and keep the name.
- Any extra regular expressions listed in `config.json`.

### Git protocol

- Stage only `sessions/<machine>/`. Never run `git add -A`, because the vault may hold unrelated uncommitted notes.
- If nothing is staged, stop here.
- Commit with the message `reccap: <machine> <UTC timestamp>`.
- Run `git pull --rebase --autostash`, then `git push`. If the push is rejected, repeat the pull and push up to 3 times.
- If the push still fails, or the network is down, leave the commit in place, log the error, and exit 0. The next run pushes it.

## Session file format

A session file is YAML frontmatter followed by the rendered story. Rendering must be deterministic: the same transcript always produces the same bytes, so the file carries no "generated at" time.

### Frontmatter

```yaml
---
session_id: 550e8400-e29b-41d4-a716-446655440000
machine: laptop
repo: payments-api
cwd: /Users/me/code/payments-api
branches: [fix/retry-backoff]
started: 2026-11-14T09:12:03+05:30
last_active: 2026-11-15T10:02:44+05:30
active_dates: [2026-11-14, 2026-11-15]
prompt_count: 23
description: Fix retry backoff in the webhook sender
description_source: model
resume: claude --resume 550e8400-e29b-41d4-a716-446655440000
---
```

| Field | Rule |
| --- | --- |
| `machine` | From `config.json`. Defaults to the short hostname, lowercased |
| `repo` | Folder name of the git root above the first `cwd`. If there is no git root, the folder name of `cwd` |
| `branches` | Every distinct branch seen in the session, in order of first appearance |
| `started`, `last_active` | First and last entry times, in the machine's local time zone with offset |
| `active_dates` | Every local calendar date on which the user sent a prompt |
| `prompt_count` | Number of prompts typed by the user |
| `description_source` | `model` or `fallback` |

Write the frontmatter by hand with fixed key order. Quote any string value that contains a colon, a hash, or a leading special character.

### Body

```markdown
# Fix retry backoff in the webhook sender

`claude --resume 550e8400-e29b-41d4-a716-446655440000`

## 2026-11-14

### 09:12 Prompt

The webhook sender retries instantly on 503. Add backoff.

### 09:12 Claude

I'll look at the sender first.

- `Read` src/webhooks/sender.py
- `Edit` src/webhooks/sender.py
- `Bash` pytest tests/webhooks -q

Backoff is in place and the tests pass.
```

- **Day headings.** Start a new `## <YYYY-MM-DD>` heading whenever the local date changes. The day page links to these headings.
- **Prompts.** Render the full text under a `### <HH:MM> Prompt` heading. Cut a prompt longer than 4,000 characters and append `[... N more characters]`. Show an attached image as `[image]`.
- **Replies.** Render assistant text in full under `### <HH:MM> Claude`. Merge consecutive assistant entries between two prompts under one heading.
- **Tool calls.** Render each as one bullet with the tool name and its most useful argument: the file path for file tools, the command for shell tools cut to 120 characters, the pattern for search tools, the URL for fetch tools. For any other tool, show the name only.
- **Omitted.** Tool results, thinking blocks, subagent entries, and system-injected text inside user entries are left out. A user entry that only carries tool results is not a prompt.
- **Slash commands.** Render as a prompt containing the command name and its arguments.
- **Compaction.** Render a compaction entry as the single line `*Context compacted*`.
- **Escaping.** A line in a prompt or reply that starts with `#` gets a leading backslash, so it cannot create a heading and break the day links.

## Morning command: `reccap day`

`reccap day [DATE]` writes the day page for `DATE`, which defaults to yesterday in the local time zone. It makes no model calls.

1. Run `git pull --rebase --autostash` in the vault. If the pull fails, print a warning and continue with local data.
2. Read every file under `sessions/` and keep those whose `active_dates` include `DATE`.
3. For each kept session, read the body section under the `## DATE` heading. Take the first and last `### HH:MM` times and count the `Prompt` headings in that section.
4. Write `daily/DATE.md`.
5. Stage only that file, commit as `reccap: day DATE`, and push with the same retry rule as sync.

Flags: `--no-pull` and `--no-push` skip the git steps. `--open` opens the page in Obsidian through an `obsidian://open` URL after writing it.

### Day page format

```markdown
---
date: 2026-11-14
session_count: 3
machines: [devbox, laptop]
---
# 2026-11-14 Saturday

<!-- reccap:start -->
## devbox

### infra

- 14:05-14:50 · [Rotate the staging database credentials](../sessions/devbox/2026-11/2026-11-14-9b1c22aa.md#2026-11-14) · `main` · 6 prompts

## laptop

### payments-api

- 09:12-17:40 · [Fix retry backoff in the webhook sender](../sessions/laptop/2026-11/2026-11-14-550e8400.md#2026-11-14) · `fix/retry-backoff` · 23 prompts
- 11:30-11:42 · [Explain the idempotency key design](../sessions/laptop/2026-11/2026-11-13-03fe7c10.md#2026-11-14) · `main` · 3 prompts · started 2026-11-13

Last sync: devbox 2026-11-14 19:02 · laptop 2026-11-15 08:55
<!-- reccap:end -->
```

- **Grouping and order.** Machines in alphabetical order, then repos in alphabetical order, then sessions by first activity time on that date.
- **Links.** Use relative markdown links with a heading anchor, not wikilinks. They work in Obsidian and in GitHub's web view.
- **Carried sessions.** A session that started on an earlier date gets a trailing `started <date>` note.
- **Last sync line.** For each machine folder, show the time of the latest commit that touched it, from `git log -1`. This makes a machine that has stopped syncing visible on the page.
- **Empty day.** If no session matches, write the page with the line `No sessions recorded.` and the last sync line.
- **Hand edits.** Replace only the text between the `reccap:start` and `reccap:end` markers. Keep everything outside them, so notes added to the page by hand survive a rerun. If the file is new, write the frontmatter, the title, and the marked block.

## Configuration, installation and scheduling

Reccap's source lives in its own repo, separate from the vault. Each machine clones it and runs the installer once.

### Commands

| Command | Purpose |
| --- | --- |
| `reccap install --vault <path> [--repo-url <url>] [--machine <name>]` | Set up this machine and schedule sync |
| `reccap sync` | Render and push changed sessions |
| `reccap day [DATE]` | Build the day page |
| `reccap doctor` | Check the setup and print one pass or fail line per check |
| `reccap uninstall` | Remove the schedule. Leaves the vault and `~/.reccap/` in place |

### `config.json`

```json
{
  "vault_path": "/Users/me/vaults/reccap",
  "machine": "laptop",
  "transcript_root": "/Users/me/.claude/projects",
  "git_bin": "/usr/bin/git",
  "claude_bin": "/Users/me/.local/bin/claude",
  "sync_interval_minutes": 60,
  "describe_model": null,
  "describe_timeout_seconds": 60,
  "exclude_cwd_prefixes": [],
  "extra_redaction_patterns": []
}
```

- `git_bin` and `claude_bin` are absolute paths resolved at install time. Scheduled jobs run with a minimal `PATH`, so bare command names will fail there.
- `describe_model`, when set, is passed to `claude -p` as the model. When null, the CLI default is used.
- `exclude_cwd_prefixes` lists directories whose sessions are never rendered or pushed, for work that should stay off the log.
- `machine` must be unique across machines. It may contain only lowercase letters, digits, and hyphens.

### What `reccap install` does

1. Confirm `git` and `claude` exist and record their absolute paths.
2. If `vault_path` does not exist and `--repo-url` is given, clone it. Otherwise confirm the path is a git repo with a remote.
3. Create `~/.reccap/` with `config.json` and `scratch/`.
4. Add the required `.gitignore` lines to the vault if missing.
5. Fail with a clear message if `sessions/<machine>/` already exists in the repo while this machine has no `state.json`, which suggests the machine name is taken. Proceed only with `--force`.
6. Install the schedule for `reccap sync`.
7. Run `reccap doctor`.

### Scheduling

| Platform | Mechanism | Details |
| --- | --- | --- |
| macOS | launchd user agent in `~/Library/LaunchAgents/` | `StartInterval` from config, `RunAtLoad` true. Must be a user agent, not a system daemon, so the job can reach the login keychain |
| Linux | systemd user timer | Hourly by default, `Persistent=true` so a missed run fires after boot |
| Linux fallback | crontab entry | Used when systemd user services are unavailable |

`reccap day` is not scheduled. It is run by hand each morning.

### `reccap doctor` checks

- The vault is a git repo, has a remote, and `git ls-remote` succeeds with `GIT_TERMINAL_PROMPT=0`. This proves a scheduled push will not hang on a credential prompt.
- `claude -p` returns a reply from the scratch directory within the timeout.
- The transcript root exists and holds at least one transcript.
- The schedule is installed and its last run exited 0.
- No unpushed reccap commits are older than 24 hours.

## Edge cases and failure handling

The general rule is that sync never blocks, never prompts, and never deletes anything in the vault. A failed step is logged and retried on the next run.

| Situation | Required behaviour |
| --- | --- |
| Session is live and the last line is half-written | Skip that line. The next run picks it up |
| Session continues on a later day | Update the same file, add a new date heading, and add the date to `active_dates`. It appears on both day pages |
| Transcript is removed by Claude Code's own retention cleanup | Keep the session file in the vault. A missing transcript is never a reason to delete |
| Machine is offline | Commits pile up locally and are pushed by a later run |
| A session arrives after its day page was built | Rerun `reccap day DATE`. The page is rebuilt from current data |
| Vault has unrelated uncommitted notes | `--autostash` protects them, and only reccap's own paths are staged |
| Rebase reports a conflict | Run `git rebase --abort`, log the error, and exit. Do not attempt to resolve it |
| `claude` is missing, logged out, or times out | Use the fallback description and continue. Rendering and pushing do not depend on the model call |
| Transcript is very large | Read it as a stream, line by line. Never load the whole file into memory |
| Session's `cwd` is under an excluded prefix | Skip it entirely and record nothing about it in the vault |
| Session moves between directories | Use the first `cwd` for `repo` and `cwd`. Do not split the session |
| Machine changes time zone | Dates follow the machine's zone at render time. A rerender may move entries across a date boundary, which is accepted |
| Two sync runs overlap | The lock makes the second exit at once |

## Testing and acceptance criteria

Tests use the standard library `unittest` module and run with no network and no real `claude` binary.

### Test approach

- **Fixtures.** Hand-written synthetic transcripts that mirror the real field names. Never commit real transcripts to the source repo.
- **Renderer.** Golden-file tests: each fixture transcript has an expected markdown file, compared byte for byte.
- **Redaction.** One test per pattern, plus a test that a redacted file contains none of the fixture secrets.
- **Model call.** A fake `claude` script on a temporary path returns a fixed line, sleeps past the timeout, or exits non-zero, to cover success, timeout, and failure.
- **Git.** Create a bare repo and two clones in a temporary directory to stand in for two machines. Run sync from both and check that neither run conflicts.
- **Day page.** Build from fixture session files and compare with a golden file. Include a multi-day session and an empty day.

### Suggested build order

1. Transcript parser and renderer, with golden tests.
2. Redaction.
3. `reccap sync` without the description step, including state and the git protocol.
4. Description step with cache and fallback.
5. `reccap day`.
6. `reccap install`, scheduling, and `reccap doctor`.

### Acceptance criteria

- [ ] On a fresh machine, `reccap install` followed by one `reccap sync` puts rendered sessions in the GitHub repo.
- [ ] A second `reccap sync` with no new activity creates no commit.
- [ ] Two machines syncing in the same minute both succeed, and both sets of files reach the repo.
- [ ] A session file opens in Obsidian with readable prompts, replies, and one-line tool calls, and contains no tool output.
- [ ] A fixture secret of each supported kind is absent from the rendered file.
- [ ] `reccap day` lists every session active on the date across all machines, and each link opens the session at that date's heading.
- [ ] A session spanning two days appears on both day pages with the correct times for each day.
- [ ] Text added by hand outside the markers on a day page survives a rerun of `reccap day`.
- [ ] Reccap's own `claude -p` calls never appear as sessions.
- [ ] With the network down, `reccap sync` exits 0, and the next run with the network up pushes the backlog.
- [ ] `reccap doctor` passes on a correctly installed machine and names the failing check on a broken one.

## Deferred features and open questions

### Deferred

These were discussed and left out of this version on purpose. Do not build them, but do not make design choices that block them.

- Carrying unfinished sessions forward onto later day pages until dismissed.
- Marking a session as done or open, whether inferred or by hand.
- Obsidian queries over the session frontmatter, such as all sessions in one repo this week.
- A Claude Code hook that triggers a sync when a session ends, for faster updates than the hourly schedule.
- Sessions run in Claude Code on the web.

### Open questions

- **Operating systems.** Which systems do the machines run? This spec assumes macOS and Linux. Windows would need a Task Scheduler entry and path handling.
- **Resumed sessions.** Does resuming a session write a new transcript that repeats the earlier entries? Check on a real machine during the build. If it does, drop entries already rendered in the earlier session, matched by entry ID, so the story is not duplicated.
- **CLI flags.** Which flags in the installed `claude` version turn off tools and stop a `-p` call from being saved as a session? Confirm with `claude --help`.
- **Other vault sync.** Is the vault also synced by another route, such as iCloud or Obsidian Sync? If so, the `.git` folder must be kept out of that sync.
- **Sync interval.** Is hourly often enough, given that a laptop may be closed before the next run?

### References

- [Claude Code documentation](https://docs.claude.com/en/docs/claude-code/overview), for the current CLI flags and settings.
- [Running Claude Code programmatically](https://code.claude.com/docs/en/headless), for `claude -p`, output formats, and `--resume`.
