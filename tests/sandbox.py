import json
import os
import shutil
import subprocess
import tempfile
import unittest

from tests.helpers import CWD, IST, SID, assistant, text, user, write_transcript
from worklog import config
from worklog.sync import run_sync

GIT = shutil.which("git")
SESSION_PATH = "sessions/laptop/2026-11/2026-11-14-550e8400.md"


def git(cwd, *args):
    result = subprocess.run([GIT, *args], check=False, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result.stdout.strip()


def basic_lines(prompt="Add backoff."):
    return [user("2026-11-14T03:42:03Z", prompt), assistant("2026-11-14T03:43:00Z", text("Done."))]


class Machine:
    def __init__(self, root, name, origin):
        self.name = name
        self.home = os.path.join(root, name, "home")
        self.vault = os.path.join(root, name, "vault")
        self.transcripts = os.path.join(root, name, "projects")
        os.makedirs(self.home)
        os.makedirs(self.transcripts)
        git(root, "clone", "-q", origin, self.vault)
        self.set_config()

    def set_config(self, **overrides):
        settings = {
            "vault_path": self.vault,
            "machine": self.name,
            "transcript_root": self.transcripts,
            "git_bin": GIT,
            "claude_bin": None,
        }
        settings.update(overrides)
        with open(os.path.join(self.home, "config.json"), "w") as f:
            json.dump(settings, f)

    def add_transcript(self, lines, sid=SID, project="-Users-me-code-payments-api"):
        directory = os.path.join(self.transcripts, project)
        os.makedirs(directory, exist_ok=True)
        return write_transcript(lines, sid=sid, directory=directory)

    def sync(self, **kwargs):
        kwargs.setdefault("tz", IST)
        return run_sync(self.home, **kwargs)

    def state(self):
        return config.load_state(self.home)

    def path(self, relpath):
        return os.path.join(self.vault, relpath)

    def read(self, relpath):
        with open(self.path(relpath)) as f:
            return f.read()

    def commits(self):
        return int(git(self.vault, "rev-list", "--count", "HEAD"))


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        empty = os.path.join(self.root, "gitconfig")
        open(empty, "w").close()
        env = {
            "GIT_CONFIG_GLOBAL": empty,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        for key, value in env.items():
            previous = os.environ.get(key)
            os.environ[key] = value
            self.addCleanup(self._restore, key, previous)
        self.origin = os.path.join(self.root, "origin.git")
        git(self.root, "init", "-q", "--bare", "-b", "main", self.origin)
        seed = os.path.join(self.root, "seed")
        git(self.root, "clone", "-q", self.origin, seed)
        with open(os.path.join(seed, "README.md"), "w") as f:
            f.write("vault\n")
        git(seed, "add", "README.md")
        git(seed, "commit", "-q", "-m", "init")
        git(seed, "push", "-q", "origin", "HEAD:main")
        self.laptop = Machine(self.root, "laptop", self.origin)

    @staticmethod
    def _restore(key, previous):
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous

    def machine(self, name):
        return Machine(self.root, name, self.origin)

    def origin_files(self):
        return git(self.origin, "ls-tree", "-r", "--name-only", "main").splitlines()


__all__ = ["CWD", "SESSION_PATH", "SID", "Machine", "SandboxTest", "basic_lines", "git"]
