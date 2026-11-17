import fcntl
import glob
import logging
import logging.handlers
import os
import re
from datetime import datetime, timezone

from worklog import config, frontmatter, gitops
from worklog.render import fallback_description, prompts_hash, render_session, session_relpath
from worklog.transcript import is_loggable, read_entries

LOG_BYTES = 1024 * 1024


def run_sync(home_dir, dry_run=False, no_push=False, since=None, out=print, tz=None, describe=None):
    os.makedirs(config.scratch(home_dir), exist_ok=True)
    with open(os.path.join(home_dir, "sync.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
        log = _logger(home_dir)
        try:
            _sync(home_dir, dry_run, no_push, since, out, tz, describe, log)
        except Exception:
            log.exception("sync failed")
        finally:
            for handler in list(log.handlers):
                handler.close()
                log.removeHandler(handler)
    return 0


def find_repo(cwd):
    folder = cwd.rstrip("/")
    while folder and folder != "/":
        if os.path.isdir(os.path.join(folder, ".git")):
            return os.path.basename(folder)
        folder = os.path.dirname(folder)
    return os.path.basename(cwd.rstrip("/")) or "unknown"


def project_folder(path):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


def _logger(home_dir):
    log = logging.getLogger("worklog.sync." + home_dir)
    log.setLevel(logging.INFO)
    log.propagate = False
    handler = logging.handlers.RotatingFileHandler(os.path.join(home_dir, "sync.log"), maxBytes=LOG_BYTES, backupCount=1)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    return log


def _sync(home_dir, dry_run, no_push, since, out, tz, describe, log):
    settings = config.load_config(home_dir)
    vault, machine, git_bin = settings["vault_path"], settings["machine"], settings["git_bin"]
    if not vault or not machine or not os.path.isdir(vault):
        log.error("vault_path or machine is not configured")
        return
    state = config.load_state(home_dir)
    records = state["transcripts"]
    since_time = datetime.strptime(since, "%Y-%m-%d").timestamp() if since else None
    scratch_folder = project_folder(config.scratch(home_dir))
    written = 0
    for path in sorted(glob.glob(os.path.join(settings["transcript_root"], "*", "*.jsonl"))):
        if os.path.basename(os.path.dirname(path)) == scratch_folder:
            continue
        try:
            stat = os.stat(path)
            record = records.get(path, {})
            if since_time is not None:
                if stat.st_mtime < since_time:
                    continue
            elif _unchanged(record, stat, describe):
                continue
            record = _process(path, record, settings, vault, machine, tz, describe, dry_run, out)
            if dry_run:
                continue
            written += record.pop("wrote", 0)
            record.update({"size": stat.st_size, "mtime": stat.st_mtime})
            records[path] = record
        except Exception:
            log.exception("could not process %s", path)
    if dry_run:
        return
    config.save_state(home_dir, state)
    folder = f"sessions/{machine}"
    committed = False
    if os.path.isdir(os.path.join(vault, folder)):
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        committed = gitops.commit(vault, git_bin, [folder], f"worklog: {machine} {stamp}")
    log.info("wrote %d session files, committed=%s", written, committed)
    if no_push or not (committed or gitops.has_unpushed(vault, git_bin)):
        return
    error = gitops.sync_remote(vault, git_bin)
    if error:
        log.error("%s", error)
    else:
        log.info("pushed")


def _unchanged(record, stat, describe):
    if record.get("size") != stat.st_size or record.get("mtime") != stat.st_mtime:
        return False
    return describe is None or record.get("description_source") != "fallback"


def _process(path, record, settings, vault, machine, tz, describe, dry_run, out):
    entries = read_entries(path)
    cwd = next((e.cwd for e in entries if e.cwd), "")
    excluded = any(cwd == p or cwd.startswith(p.rstrip("/") + "/") for p in settings["exclude_cwd_prefixes"])
    if not is_loggable(entries) or excluded:
        return {"skipped": True}
    session_id = os.path.basename(path)[: -len(".jsonl")]
    relpath = record.get("relpath") or _existing(vault, machine, session_id) or session_relpath(machine, session_id, entries, tz)
    if dry_run:
        out(relpath)
        return {}
    digest = prompts_hash(entries)
    if record.get("prompts_hash") == digest and record.get("description_source") == "model":
        description, source = record["description"], "model"
    elif describe:
        description, source = describe(entries)
    else:
        description, source = fallback_description(entries), "fallback"
    content = render_session(session_id, entries, machine, find_repo(cwd), tz, description, source)
    target = os.path.join(vault, relpath)
    wrote = 0
    if _read(target) != content:
        config.write_atomic(target, content)
        wrote = 1
    return {"relpath": relpath, "prompts_hash": digest, "description": description, "description_source": source, "wrote": wrote}


def _existing(vault, machine, session_id):
    pattern = os.path.join(vault, "sessions", machine, "*", f"*-{session_id[:8]}.md")
    for candidate in sorted(glob.glob(pattern)):
        meta, _ = frontmatter.parse(_read(candidate) or "")
        if meta.get("session_id") == session_id:
            return os.path.relpath(candidate, vault)
    return None


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None
