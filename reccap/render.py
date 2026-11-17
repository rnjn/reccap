import hashlib
import re

from reccap import frontmatter

PROMPT_LIMIT = 4000
ARGUMENT_LIMIT = 120
DESCRIPTION_LIMIT = 100
SLUG_LIMIT = 40
ARGUMENT_KEYS = ("file_path", "notebook_path", "command", "pattern", "url", "query", "skill", "description")
PATH_KEYS = ("file_path", "notebook_path")


def one_line(text):
    return " ".join(text.split())


def fallback_description(entries):
    prompts = [e for e in entries if e.kind == "prompt"]
    typed = [p for p in prompts if not p.slash]
    for prompt in typed or prompts:
        return one_line(prompt.text)[:DESCRIPTION_LIMIT].strip()
    return ""


def prompts_hash(entries):
    digest = hashlib.sha256()
    for entry in entries:
        if entry.kind == "prompt":
            digest.update(entry.text.encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def slug(title):
    words = re.sub(r"[^a-z0-9]+", " ", title.lower()).split()
    kept = ""
    for word in words:
        longer = (kept + "-" + word) if kept else word[:SLUG_LIMIT]
        if len(longer) > SLUG_LIMIT:
            break
        kept = longer
    return kept


def session_relpath(session_id, entries, tz, title):
    start = entries[0].time.astimezone(tz)
    name = slug(title) or session_id[:8]
    return f"sessions/{start.strftime('%Y-%m')}/{start.strftime('%d')}/{start.strftime('%H%M')}-{name}.md"


def render_session(session_id, entries, machine, repo, tz=None, description=None, description_source="fallback"):
    description = description or fallback_description(entries)
    prompts = [e for e in entries if e.kind == "prompt"]
    cwd = next((e.cwd for e in entries if e.cwd), "")
    branches = []
    for entry in entries:
        if entry.branch and entry.branch not in branches:
            branches.append(entry.branch)
    active_dates = []
    for prompt in prompts:
        date = prompt.time.astimezone(tz).strftime("%Y-%m-%d")
        if date not in active_dates:
            active_dates.append(date)
    resume = "claude --resume " + session_id
    head = frontmatter.dump(
        [
            ("session_id", session_id),
            ("machine", machine),
            ("repo", repo),
            ("cwd", cwd),
            ("branches", branches),
            ("started", _stamp(entries[0].time, tz)),
            ("last_active", _stamp(entries[-1].time, tz)),
            ("active_dates", active_dates),
            ("prompt_count", len(prompts)),
            ("description", description),
            ("description_source", description_source),
            ("resume", resume),
        ]
    )
    return head + "\n".join(_body(entries, description, resume, cwd, tz)) + "\n"


def _stamp(time, tz):
    return time.astimezone(tz).replace(microsecond=0).isoformat()


def _body(entries, description, resume, cwd, tz):
    lines = ["# " + description, "", "`" + resume + "`"]
    current_date = None
    in_reply = False
    after_tool = False
    for entry in entries:
        local = entry.time.astimezone(tz)
        date = local.strftime("%Y-%m-%d")
        clock = local.strftime("%H:%M")
        parts = entry.parts if entry.kind == "assistant" else None
        if entry.kind == "assistant" and not parts:
            continue
        if date != current_date:
            lines += ["", "## " + date]
            current_date = date
            in_reply = False
        if entry.kind == "prompt":
            lines += ["", "### " + clock + " Prompt", "", _prompt_text(entry.text)]
            in_reply = False
        elif entry.kind == "compaction":
            lines += ["", "*Context compacted*"]
            in_reply = False
        else:
            if not in_reply:
                lines += ["", "### " + clock + " Claude"]
                in_reply = True
                after_tool = False
            for part in parts:
                if part[0] == "text":
                    lines += ["", _safe(part[1])]
                    after_tool = False
                else:
                    if not after_tool:
                        lines.append("")
                    lines.append(_tool_line(part[1], part[2], entry.cwd or cwd))
                    after_tool = True
    return lines


def _prompt_text(text):
    if len(text) <= PROMPT_LIMIT:
        return _safe(text)
    kept = _safe(text[:PROMPT_LIMIT])
    return kept + f"\n\n[... {len(text) - PROMPT_LIMIT} more characters]"


def _safe(text):
    lines = ["\\" + line if line.startswith("#") else line for line in text.split("\n")]
    fences = sum(1 for line in lines if line.lstrip().startswith("```"))
    if fences % 2:
        lines.append("```")
    return "\n".join(lines)


def _tool_line(name, tool_input, cwd):
    for key in ARGUMENT_KEYS:
        value = tool_input.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        if key in PATH_KEYS and cwd and value.startswith(cwd.rstrip("/") + "/"):
            value = value[len(cwd.rstrip("/")) + 1 :]
        value = one_line(value)
        if len(value) > ARGUMENT_LIMIT:
            value = value[:ARGUMENT_LIMIT] + "…"
        return f"- `{name}` {value}"
    return f"- `{name}`"
