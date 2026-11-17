import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reccap import config, frontmatter, gitops
from reccap.day import _block, _last_sync, _page, _read, _sessions


def main():
    settings = config.load_config(config.home())
    vault, git_bin = settings["vault_path"], settings["git_bin"]
    error = gitops.sync_remote(vault, git_bin, push=False)
    if error:
        print(f"warning: pull failed, using local data ({error})")
    dates = set()
    for path in glob.glob(os.path.join(vault, "sessions", "*", "*", "*.md")):
        with open(path, encoding="utf-8", errors="replace") as f:
            dates.update(frontmatter.parse(f.read(4096))[0].get("active_dates", []))
    last_sync = None
    written = 0
    for day in sorted(dates):
        sessions, machines = _sessions(vault, day)
        last_sync = last_sync or _last_sync(vault, git_bin, None, machines)
        target = os.path.join(vault, "daily", day + ".md")
        existing = _read(target)
        content = _page(existing, day, sessions, _block(sessions, day, last_sync))
        if content != existing:
            config.write_atomic(target, content)
            written += 1
    print(f"{len(dates)} dates, {written} pages written, vault {vault}")
    print(f'commit with: git -C {vault} add daily && git -C {vault} commit -m "reccap: day backfill"')


if __name__ == "__main__":
    main()
