# reccap

A daily recap of your Claude Code sessions, across all your machines, as pages in an Obsidian vault.

Each machine renders its own sessions to markdown and pushes them to a private git repo that is also the vault. One command then builds a page per day that lists every session active that day, grouped by machine and repo, with a link to a readable transcript of each.

The command-line tool is called `worklog`.

## What you get

A day page, `daily/2026-11-14.md`:

```markdown
## laptop

### payments-api

- 09:12-17:40 · [Fix retry backoff in the webhook sender](../sessions/laptop/2026-11/2026-11-14-550e8400.md#2026-11-14) · `fix/retry-backoff` · 23 prompts

Last sync: devbox 2026-11-14 19:02 · laptop 2026-11-15 08:55
```

A session page, `sessions/laptop/2026-11/2026-11-14-550e8400.md`, with your prompts, Claude's replies, and one line per tool call. Tool output and thinking are left out.

## How it works

- `worklog sync` runs hourly on every machine. It reads the transcripts under `~/.claude/projects/`, renders the ones that changed, asks `claude -p` for a one-line description of each, and commits and pushes them.
- Each machine writes only inside `sessions/<machine>/`, so machines never edit the same file.
- `worklog day` is run by hand. It syncs this machine, pulls the vault, and writes `daily/<date>.md` from every machine's sessions. Notes you add to a day page outside the `worklog:start` and `worklog:end` markers survive a rerun.

There is no server and no database. Session content is pushed as written, with no redaction, so keep the vault repo private.

## Requirements

- Python 3.9 or later. No third-party packages.
- `git`, able to push to the vault repo without a prompt.
- The `claude` CLI, logged in.
- macOS or Linux.

## Install

Create a private git repo for the vault, once. Then on each machine:

```sh
git clone https://github.com/rnjn/reccap.git ~/src/reccap
~/src/reccap/bin/worklog install --vault ~/vaults/worklog --repo-url <vault repo url> --machine <unique-name>
ln -s ~/src/reccap/bin/worklog ~/.local/bin/worklog
```

`install` clones the vault if the path does not exist, writes `~/.worklog/config.json`, schedules the hourly sync, and runs `worklog doctor`. `--machine` defaults to the short hostname and must be unique across machines.

The schedule is a launchd user agent on macOS and a systemd user timer on Linux, with a crontab entry as the fallback.

## Commands

| Command | Purpose |
| --- | --- |
| `worklog install --vault <path> [--repo-url <url>] [--machine <name>] [--force]` | Set up this machine and schedule sync |
| `worklog sync [--dry-run] [--no-push] [--since YYYY-MM-DD]` | Render changed sessions and push them |
| `worklog day [DATE] [--open] [--no-sync] [--no-pull] [--no-push]` | Build the day page; `DATE` defaults to yesterday |
| `worklog doctor` | Check the setup, one pass or fail line per check |
| `worklog uninstall` | Remove the schedule; the vault and `~/.worklog/` stay |

`--since` reprocesses older transcripts, for backfill. `--open` opens the page in Obsidian.

## Configuration

Settings live in `~/.worklog/config.json`. `install` writes it, and keeps your edits when run again.

| Key | Meaning |
| --- | --- |
| `vault_path` | The vault, and so the output folder |
| `machine` | This machine's name; lowercase letters, digits, and hyphens |
| `transcript_root` | Where Claude Code keeps transcripts; default `~/.claude/projects` |
| `git_bin`, `claude_bin` | Absolute paths, resolved at install time |
| `sync_interval_minutes` | Default 60; run `install` again after changing it |
| `describe_model` | Model for the description call; `null` uses the CLI default |
| `describe_timeout_seconds` | Default 60 |
| `exclude_cwd_prefixes` | Directories whose sessions are never rendered or pushed |

Local state sits beside it: `state.json`, `sync.log`, and `scratch/`. Set `WORKLOG_HOME` to use a different folder.

## Development

```sh
make test
make lint
```

Tests use `unittest`, temporary git repos, and a fake `claude` script; they need no network. The build spec and the implementation plan, with the points where the code departs from the spec, are in `docs/`.
