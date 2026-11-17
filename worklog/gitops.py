import os
import subprocess

PUSH_ATTEMPTS = 3
TIMEOUT_SECONDS = 120


def git(vault, git_bin, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        return subprocess.run(
            [git_bin, *args], check=False, cwd=vault, env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(args, 1, "", str(error))


def commit(vault, git_bin, paths, message):
    git(vault, git_bin, "add", "--", *paths)
    if git(vault, git_bin, "diff", "--cached", "--quiet", "--", *paths).returncode == 0:
        return False
    result = git(vault, git_bin, "commit", "-q", "-m", message, "--", *paths)
    if result.returncode:
        raise RuntimeError("commit failed: " + _reason(result))
    return True


def sync_remote(vault, git_bin, push=True):
    branch = git(vault, git_bin, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    remote = (git(vault, git_bin, "remote").stdout.split() or [None])[0]
    if not remote or branch in ("", "HEAD"):
        return "no remote or branch to sync with"
    error = "push rejected"
    for _ in range(PUSH_ATTEMPTS):
        fetch = git(vault, git_bin, "fetch", "-q", remote)
        if fetch.returncode:
            return "fetch failed: " + _reason(fetch)
        upstream = f"refs/remotes/{remote}/{branch}"
        if git(vault, git_bin, "rev-parse", "-q", "--verify", upstream).returncode == 0:
            rebase = git(vault, git_bin, "rebase", "-q", "--autostash", upstream)
            if rebase.returncode:
                git(vault, git_bin, "rebase", "--abort")
                return "rebase failed and was aborted: " + _reason(rebase)
        if not push:
            return None
        pushed = git(vault, git_bin, "push", "-q", "-u", remote, branch)
        if pushed.returncode == 0:
            return None
        error = "push failed: " + _reason(pushed)
    return error


def has_unpushed(vault, git_bin):
    if git(vault, git_bin, "rev-parse", "-q", "--verify", "HEAD").returncode:
        return False
    branch = git(vault, git_bin, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    remote = (git(vault, git_bin, "remote").stdout.split() or [None])[0]
    if not remote:
        return False
    upstream = f"refs/remotes/{remote}/{branch}"
    if git(vault, git_bin, "rev-parse", "-q", "--verify", upstream).returncode:
        return True
    count = git(vault, git_bin, "rev-list", "--count", f"{upstream}..HEAD").stdout.strip()
    return count not in ("", "0")


def _reason(result):
    lines = (result.stderr or result.stdout or "").strip().splitlines()
    return lines[-1] if lines else "unknown error"
