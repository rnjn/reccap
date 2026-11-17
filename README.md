# worklog

Turns Claude Code sessions from several machines into one daily page in an Obsidian vault. The vault is a private git repo; each machine pushes its own sessions into it.

Requires Python 3.9 or later, `git`, and the `claude` CLI. No other packages.

## Set up a machine

```sh
git clone <this repo> ~/src/worklog
~/src/worklog/bin/worklog install --vault ~/vaults/worklog --repo-url <private vault repo url>
```

`install` writes `~/.worklog/config.json`, schedules an hourly `worklog sync`, and runs `worklog doctor`. Each machine needs a unique `--machine` name; it defaults to the short hostname.

## Commands

| Command | Purpose |
| --- | --- |
| `worklog sync [--dry-run] [--no-push] [--since YYYY-MM-DD]` | Render changed sessions into `sessions/<machine>/` and push |
| `worklog day [DATE] [--open] [--no-sync] [--no-pull] [--no-push]` | Build `daily/DATE.md`, defaulting to yesterday |
| `worklog doctor` | Check the setup, one pass or fail line per check |
| `worklog uninstall` | Remove the schedule; the vault and `~/.worklog/` stay |

## Development

```sh
make test
make lint
```

The design is in `docs/`. Session content is pushed as written, with no redaction, so keep the vault repo private.
