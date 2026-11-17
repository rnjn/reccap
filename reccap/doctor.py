import glob
import os
import time

from reccap import config, gitops, schedule
from reccap.describe import ask

DAY_SECONDS = 24 * 60 * 60


def run_doctor(home_dir, out=print, scheduler=schedule):
    settings = config.load_config(home_dir)
    checks = [
        ("vault remote", _vault(settings)),
        ("claude", _claude(settings, home_dir)),
        ("transcripts", _transcripts(settings)),
        ("schedule", scheduler.status()),
        ("unpushed commits", _unpushed(settings)),
    ]
    failed = 0
    for name, (ok, detail) in checks:
        out(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
        failed += not ok
    return 1 if failed else 0


def _vault(settings):
    vault, git_bin = settings["vault_path"], settings["git_bin"]
    if not vault or gitops.git(vault, git_bin, "rev-parse", "--git-dir").returncode:
        return False, f"{vault} is not a git repo"
    remote = gitops.first_remote(vault, git_bin)
    if not remote:
        return False, "the vault has no remote"
    listed = gitops.git(vault, git_bin, "ls-remote", "--heads", remote)
    if listed.returncode:
        return False, f"cannot reach {remote} without a prompt"
    return True, f"{remote} is reachable"


def _claude(settings, home_dir):
    if not settings["claude_bin"]:
        return False, "claude_bin is not set"
    os.makedirs(config.scratch(home_dir), exist_ok=True)
    reply, error = ask(settings, config.scratch(home_dir), "Reply with the single word ok")
    if reply is None or not reply.strip():
        return False, error or "empty reply"
    return True, "claude -p replied"


def _transcripts(settings):
    root = settings["transcript_root"]
    count = len(glob.glob(os.path.join(root, "*", "*.jsonl")))
    return count > 0, f"{count} transcripts under {root}"


def _unpushed(settings):
    vault, git_bin = settings["vault_path"], settings["git_bin"]
    if not vault or not os.path.isdir(vault):
        return False, "no vault"
    upstream = gitops.upstream_ref(vault, git_bin)
    span = f"{upstream}..HEAD" if upstream else "HEAD"
    log = gitops.git(vault, git_bin, "log", span, "--format=%ct %s").stdout
    cutoff = time.time() - DAY_SECONDS
    old = [line for line in log.splitlines() if line.partition(" ")[2].startswith("reccap:") and int(line.split()[0]) < cutoff]
    if old:
        return False, f"{len(old)} reccap commits have waited more than 24 hours"
    return True, "nothing older than 24 hours"
