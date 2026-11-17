import json
import os
import tempfile
from datetime import timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
SID = "550e8400-e29b-41d4-a716-446655440000"
CWD = "/Users/me/code/payments-api"
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def base(ts, sid=SID, cwd=CWD, branch="fix/retry-backoff"):
    return {"timestamp": ts, "sessionId": sid, "cwd": cwd, "gitBranch": branch, "isSidechain": False}


def user(ts, content, human=True, **extra):
    d = base(ts)
    d.update({"type": "user", "message": {"role": "user", "content": content}})
    if human:
        d["origin"] = {"kind": "human"}
    d.update(extra)
    return d


def assistant(ts, *blocks, **extra):
    d = base(ts)
    d.update({"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}})
    d.update(extra)
    return d


def text(value):
    return {"type": "text", "text": value}


def tool(name, **tool_input):
    return {"type": "tool_use", "name": name, "input": tool_input}


def write_transcript(lines, sid=SID, directory=None):
    directory = directory or tempfile.mkdtemp()
    path = os.path.join(directory, sid + ".jsonl")
    with open(path, "w") as f:
        for line in lines:
            f.write(line if isinstance(line, str) else json.dumps(line))
            f.write("\n")
    return path


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()
