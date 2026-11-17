import subprocess

from worklog.render import DESCRIPTION_LIMIT, fallback_description

PROMPT_CUT = 500
REPLY_CUT = 1000
INPUT_LIMIT = 8000
SEPARATOR = "\n---\n"
GAP = "[... prompts omitted ...]"
INSTRUCTION = (
    "Below are the user's prompts from one coding session, followed by the assistant's last reply. "
    "Write a single line of at most 100 characters that says what the session was working on, "
    "phrased as a task, for example: Fix retry backoff in the webhook sender. "
    "No trailing period, no quotes, no preamble. Output only that line."
)


def build_input(entries):
    prompts = [e.text[:PROMPT_CUT] for e in entries if e.kind == "prompt"]
    reply = ""
    for entry in reversed(entries):
        texts = [p[1] for p in entry.parts if p[0] == "text"]
        if texts:
            reply = "Last reply:\n" + texts[-1][:REPLY_CUT]
            break
    budget = INPUT_LIMIT - len(reply) - len(SEPARATOR) - len(GAP) - len(SEPARATOR)
    head, tail = [], []
    take_head = True
    while prompts:
        candidate = prompts[0] if take_head else prompts[-1]
        if len(candidate) + len(SEPARATOR) > budget:
            break
        budget -= len(candidate) + len(SEPARATOR)
        if take_head:
            head.append(prompts.pop(0))
        else:
            tail.insert(0, prompts.pop())
        take_head = not take_head
    pieces = head + ([GAP] if prompts else []) + tail + ([reply] if reply else [])
    return SEPARATOR.join(pieces)


def describe(entries, settings, scratch_dir):
    fallback = (fallback_description(entries), "fallback")
    command = [settings["claude_bin"], "-p", "--no-session-persistence", "--tools", ""]
    if settings.get("describe_model"):
        command += ["--model", settings["describe_model"]]
    try:
        result = subprocess.run(
            command,
            check=False,
            input=INSTRUCTION + "\n\n<session>\n" + build_input(entries) + "\n</session>\n",
            cwd=scratch_dir,
            capture_output=True,
            text=True,
            timeout=settings.get("describe_timeout_seconds") or 60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return fallback
    if result.returncode:
        return fallback
    line = clean(result.stdout)
    return (line, "model") if line else fallback


def clean(reply):
    for line in reply.splitlines():
        line = line.strip().strip("\"'").strip()
        if line:
            return line.rstrip(".")[:DESCRIPTION_LIMIT].strip()
    return ""
