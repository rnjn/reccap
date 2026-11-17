import glob
import os
import re
import subprocess
import sys
from datetime import date as date_type
from datetime import datetime, timedelta
from urllib.parse import quote

from reccap import config, frontmatter, gitops
from reccap.sync import run_sync

START = "<!-- reccap:start -->"
END = "<!-- reccap:end -->"
HEADING = re.compile(r"^### (\d\d:\d\d) (Prompt|Claude)$")


def run_day(home_dir, day=None, no_pull=False, no_push=False, no_sync=False, open_page=False, tz=None, out=print, opener=None, today=None):
    settings = config.load_config(home_dir)
    vault, git_bin = settings["vault_path"], settings["git_bin"]
    if not vault or not os.path.isdir(vault):
        out("vault_path is not configured; run reccap install")
        return 1
    if day is None:
        today = today or datetime.now(tz).date()
        day = (today - timedelta(days=1)).isoformat()
    if not no_sync:
        run_sync(home_dir, no_push=no_push, tz=tz)
    if not no_pull:
        error = gitops.sync_remote(vault, git_bin, push=False)
        if error:
            out(f"warning: pull failed, using local data ({error})")
    sessions, machines = _sessions(vault, day)
    relpath = f"daily/{day}.md"
    target = os.path.join(vault, relpath)
    existing = _read(target)
    content = _page(existing, day, sessions, _block(sessions, day, _last_sync(vault, git_bin, tz, machines)))
    if content != existing:
        config.write_atomic(target, content)
    committed = gitops.commit(vault, git_bin, [relpath], f"reccap: day {day}")
    if not no_push and (committed or gitops.has_unpushed(vault, git_bin)):
        error = gitops.sync_remote(vault, git_bin)
        if error:
            out(f"warning: push failed ({error})")
    out(target)
    if open_page:
        (opener or _open)("obsidian://open?path=" + quote(target, safe=""))
    return 0


def _sessions(vault, day):
    found = []
    machines = set()
    for path in sorted(glob.glob(os.path.join(vault, "sessions", "*", "*", "*.md"))):
        meta, body = frontmatter.parse(_read(path) or "")
        machines.add(meta.get("machine") or "unknown")
        if day not in meta.get("active_dates", []):
            continue
        times, prompts = _section(body, day)
        if not times:
            continue
        found.append(
            {
                "machine": meta.get("machine") or "unknown",
                "repo": meta.get("repo") or "unknown",
                "first": times[0],
                "last": times[-1],
                "prompts": prompts,
                "description": meta.get("description") or "Untitled session",
                "branches": meta.get("branches") or [],
                "started": (meta.get("started") or "")[:10],
                "link": "../" + "/".join(os.path.relpath(path, vault).split(os.sep)) + "#" + day,
            }
        )
    return sorted(found, key=lambda s: (s["machine"], s["repo"], s["first"], s["link"])), sorted(machines)


def _section(body, day):
    times, prompts, inside = [], 0, False
    for line in body.split("\n"):
        if line.startswith("## "):
            inside = line == "## " + day
            continue
        match = HEADING.match(line) if inside else None
        if match:
            times.append(match.group(1))
            prompts += match.group(2) == "Prompt"
    return times, prompts


def _block(sessions, day, last_sync):
    lines = []
    machine = repo = None
    for session in sessions:
        if session["machine"] != machine:
            machine, repo = session["machine"], None
            lines += ["## " + machine, ""]
        if session["repo"] != repo:
            repo = session["repo"]
            lines += ["### " + repo, ""]
        elif lines[-1] == "":
            lines.pop()
        title = session["description"].replace("[", "\\[").replace("]", "\\]")
        fields = [f"{session['first']}-{session['last']}", f"[{title}]({session['link']})"]
        if session["branches"]:
            fields.append(" ".join(f"`{b}`" for b in session["branches"]))
        fields.append("1 prompt" if session["prompts"] == 1 else f"{session['prompts']} prompts")
        if session["started"] and session["started"] < day:
            fields.append("started " + session["started"])
        lines += ["- " + " · ".join(fields), ""]
    if not sessions:
        lines += ["No sessions recorded.", ""]
    if last_sync:
        lines.append("Last sync: " + " · ".join(last_sync))
    elif lines:
        lines.pop()
    return "\n".join([START, *lines, END])


def _last_sync(vault, git_bin, tz, machines):
    entries = []
    for machine in machines:
        stamp = gitops.git(vault, git_bin, "log", "-1", "--format=%cI", f"--grep=^reccap: {machine} ").stdout.strip()
        if stamp:
            local = datetime.fromisoformat(stamp).astimezone(tz)
            entries.append(f"{machine} {local.strftime('%Y-%m-%d %H:%M')}")
    return entries


def _page(existing, day, sessions, block):
    machines = sorted({s["machine"] for s in sessions})
    values = [("date", day), ("session_count", len(sessions)), ("machines", machines)]
    if existing is None:
        weekday = date_type.fromisoformat(day).strftime("%A")
        return frontmatter.dump(values) + f"# {day} {weekday}\n\n{block}\n"
    page = existing
    if page.startswith("---\n") and "\n---\n" in page[3:]:
        end = page.index("\n---\n", 3)
        head = page[:end]
        for line in frontmatter.dump(values).split("\n")[1:-2]:
            key = line.split(":")[0]
            head = re.sub(rf"(?m)^{key}: .*$", lambda _, line=line: line, head)
        page = head + page[end:]
    start, end = page.find(START), page.find(END)
    if start >= 0 and end > start:
        return page[:start] + block + page[end + len(END) :]
    return page.rstrip("\n") + "\n\n" + block + "\n"


def _open(url):
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.run([opener, url], check=False)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None
