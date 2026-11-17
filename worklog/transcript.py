import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)


@dataclass
class Entry:
    kind: str
    time: datetime
    cwd: str = ""
    branch: str = ""
    text: str = ""
    slash: bool = False
    parts: list = field(default_factory=list)


def read_entries(path):
    session_id = os.path.basename(path)[: -len(".jsonl")]
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                raw = json.loads(line)
            except ValueError:
                continue
            if not isinstance(raw, dict):
                continue
            entry = _entry(raw, session_id)
            if entry:
                entries.append(entry)
    return entries


def is_loggable(entries):
    prompts = [e for e in entries if e.kind == "prompt"]
    if not prompts:
        return False
    if any(not p.slash for p in prompts):
        return True
    return any(e.kind == "assistant" for e in entries)


def _entry(raw, session_id):
    if raw.get("isSidechain") or raw.get("sessionId") not in (None, session_id):
        return None
    time = _time(raw.get("timestamp"))
    if time is None:
        return None
    common = {"time": time, "cwd": raw.get("cwd") or "", "branch": raw.get("gitBranch") or ""}
    kind = raw.get("type")
    if kind == "user":
        return _prompt(raw, common)
    if kind == "assistant":
        return _assistant(raw, common)
    if kind == "system" and raw.get("subtype") == "compact_boundary":
        return Entry(kind="compaction", **common)
    return None


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _content(raw):
    message = raw.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _prompt(raw, common):
    if raw.get("isMeta") or raw.get("isCompactSummary"):
        return None
    blocks = _content(raw)
    if any(b.get("type") == "tool_result" for b in blocks):
        return None
    origin = raw.get("origin")
    if origin and origin.get("kind") != "human":
        return None
    pieces = []
    for block in blocks:
        if block.get("type") == "text" and (block.get("text") or "").strip():
            pieces.append(block["text"].strip())
        elif block.get("type") == "image":
            pieces.append("[image]")
    text = "\n\n".join(pieces)
    if not text:
        return None
    if text.startswith("<command-"):
        name = COMMAND_NAME.search(text)
        if not name:
            return None
        args = COMMAND_ARGS.search(text)
        command = (name.group(1).strip() + " " + (args.group(1).strip() if args else "")).strip()
        return Entry(kind="prompt", text=command, slash=True, **common)
    if not origin and text.startswith(("<", "[Request interrupted")):
        return None
    return Entry(kind="prompt", text=text, **common)


def _assistant(raw, common):
    if raw.get("isApiErrorMessage"):
        return None
    parts = []
    for block in _content(raw):
        if block.get("type") == "text" and (block.get("text") or "").strip():
            parts.append(("text", block["text"].strip()))
        elif block.get("type") == "tool_use":
            tool_input = block.get("input")
            parts.append(("tool", block.get("name") or "tool", tool_input if isinstance(tool_input, dict) else {}))
    return Entry(kind="assistant", parts=parts, **common)
