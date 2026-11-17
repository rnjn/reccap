import fcntl
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reccap import config
from reccap.render import one_line, render_session
from reccap.sync import _new_path, session_index
from reccap.transcript import Entry, _time

MACHINE = "claude-ai"
REPO = "chats"


def active_branch(messages):
    by_id = {m["uuid"]: m for m in messages}
    parents = {m.get("parent_message_uuid") for m in messages}
    leaves = [m for m in messages if m["uuid"] not in parents] or messages
    node = max(leaves, key=lambda m: m["created_at"])
    path, seen = [], set()
    while node and node["uuid"] not in seen:
        seen.add(node["uuid"])
        path.append(node)
        node = by_id.get(node.get("parent_message_uuid"))
    return list(reversed(path))


def entries_of(conversation):
    entries = []
    for message in active_branch(conversation["chat_messages"]):
        time = _time(message.get("created_at"))
        if time is None:
            continue
        blocks = message.get("content") or []
        if message["sender"] == "human":
            texts = [b["text"].strip() for b in blocks if b.get("type") == "text" and (b.get("text") or "").strip()]
            text = "\n\n".join(texts) or (message.get("text") or "").strip()
            attached = (message.get("attachments") or []) + (message.get("files") or [])
            pieces = [text] if text else []
            pieces += [f"[attachment: {a.get('file_name') or 'file'}]" for a in attached]
            if pieces:
                entries.append(Entry(kind="prompt", time=time, text="\n\n".join(pieces)))
            continue
        parts = []
        for block in blocks:
            if block.get("type") == "text" and (block.get("text") or "").strip():
                parts.append(("text", block["text"].strip()))
            elif block.get("type") == "tool_use":
                tool_input = block.get("input")
                parts.append(("tool", block.get("name") or "tool", tool_input if isinstance(tool_input, dict) else {}))
        entries.append(Entry(kind="assistant", time=time, parts=parts))
    return entries


def current(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def main(source):
    home_dir = config.home()
    vault = config.load_config(home_dir)["vault_path"]
    with open(source, encoding="utf-8") as f:
        conversations = json.load(f)
    written = skipped = 0
    with open(os.path.join(home_dir, "sync.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        index = session_index(vault)
        for conversation in sorted(conversations, key=lambda c: c["created_at"]):
            entries = entries_of(conversation) if conversation.get("chat_messages") else []
            prompts = [e for e in entries if e.kind == "prompt"]
            if not prompts:
                skipped += 1
                continue
            uuid = conversation["uuid"]
            title = one_line(conversation.get("name") or "") or one_line(prompts[0].text)[:60]
            url = "https://claude.ai/chat/" + uuid
            text = render_session(uuid, entries, MACHINE, REPO, None, title[:100], "title")
            text = text.replace(f"`claude --resume {uuid}`", f"[Open on claude.ai]({url})").replace(f"claude --resume {uuid}", url)
            relpath = (index.get(uuid) or (None,))[0] or _new_path(vault, uuid, entries, None, title)
            target = os.path.join(vault, relpath)
            if current(target) != text:
                config.write_atomic(target, text)
                written += 1
    print(f"written {written}, skipped {skipped}, vault {vault}")
    print(f'commit with: git -C {vault} add sessions && git -C {vault} commit -m "reccap: {MACHINE} import"')


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: import_claude_ai.py <path to conversations.json>")
    main(sys.argv[1])
