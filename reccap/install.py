import os
import re
import shutil
import socket

from reccap import config, gitops, schedule
from reccap.doctor import run_doctor

IGNORE_LINES = [".obsidian/workspace*.json", ".trash/"]
MACHINE_NAME = re.compile(r"^[a-z0-9-]+$")


def default_machine():
    short = socket.gethostname().split(".")[0].lower()
    return re.sub(r"[^a-z0-9]", "-", short).strip("-")


def run_install(
    home_dir, vault, repo_url=None, machine=None, force=False, out=print, scheduler=schedule, which=shutil.which, transcript_root=None
):
    machine = machine or default_machine()
    vault = os.path.abspath(os.path.expanduser(vault))
    git_bin, claude_bin = which("git"), which("claude")
    if not git_bin or not claude_bin:
        out("git and claude must both be on PATH; missing: " + ("git" if not git_bin else "claude"))
        return 1
    if not MACHINE_NAME.match(machine):
        out(f"machine name {machine!r} may contain only lowercase letters, digits, and hyphens")
        return 1
    if not os.path.exists(vault):
        if not repo_url:
            out(f"{vault} does not exist; pass --repo-url to clone it")
            return 1
        cloned = gitops.git(os.path.dirname(vault) or ".", git_bin, "clone", "-q", repo_url, vault)
        if cloned.returncode:
            out("clone failed: " + cloned.stderr.strip())
            return 1
    if gitops.git(vault, git_bin, "rev-parse", "--git-dir").returncode or not gitops.first_remote(vault, git_bin):
        out(f"{vault} must be a git repo with a remote")
        return 1
    gitops.sync_remote(vault, git_bin, push=False)
    taken = os.path.isdir(os.path.join(vault, "sessions", machine)) and not os.path.exists(os.path.join(home_dir, "state.json"))
    if taken and not force:
        out(f"sessions/{machine}/ already exists in the vault; pick another --machine or pass --force")
        return 1
    os.makedirs(config.scratch(home_dir), exist_ok=True)
    settings = config.load_config(home_dir)
    settings.update({"vault_path": vault, "machine": machine, "git_bin": git_bin, "claude_bin": claude_bin})
    if transcript_root:
        settings["transcript_root"] = transcript_root
    config.save_config(home_dir, settings)
    _ignore(vault, git_bin)
    try:
        out("schedule: " + scheduler.install(home_dir, settings["sync_interval_minutes"]))
    except (OSError, RuntimeError) as error:
        out(f"schedule: could not install ({error})")
    return run_doctor(home_dir, out=out, scheduler=scheduler)


def _ignore(vault, git_bin):
    path = os.path.join(vault, ".gitignore")
    try:
        with open(path, encoding="utf-8") as f:
            current = f.read()
    except OSError:
        current = ""
    missing = [line for line in IGNORE_LINES if line not in current.splitlines()]
    if not missing:
        return
    if current and not current.endswith("\n"):
        current += "\n"
    config.write_atomic(path, current + "".join(line + "\n" for line in missing))
    gitops.commit(vault, git_bin, [".gitignore"], "reccap: gitignore")
