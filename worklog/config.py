import json
import os

DEFAULTS = {
    "vault_path": None,
    "machine": None,
    "transcript_root": os.path.join("~", ".claude", "projects"),
    "git_bin": "git",
    "claude_bin": "claude",
    "sync_interval_minutes": 60,
    "describe_model": None,
    "describe_timeout_seconds": 60,
    "exclude_cwd_prefixes": [],
}


def home():
    return os.environ.get("WORKLOG_HOME") or os.path.join(os.path.expanduser("~"), ".worklog")


def scratch(home_dir):
    return os.path.join(home_dir, "scratch")


def load_config(home_dir):
    settings = dict(DEFAULTS)
    settings.update(_read(os.path.join(home_dir, "config.json"), {}))
    for key in ("vault_path", "transcript_root"):
        if settings[key]:
            settings[key] = os.path.expanduser(settings[key])
    return settings


def save_config(home_dir, settings):
    write_atomic(os.path.join(home_dir, "config.json"), json.dumps(settings, indent=2) + "\n")


def load_state(home_dir):
    state = _read(os.path.join(home_dir, "state.json"), {})
    state.setdefault("transcripts", {})
    return state


def save_state(home_dir, state):
    write_atomic(os.path.join(home_dir, "state.json"), json.dumps(state, indent=1, sort_keys=True) + "\n")


def write_atomic(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(temporary, path)


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
