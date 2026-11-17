import json
import os
import socket

from reccap.doctor import run_doctor
from reccap.install import default_machine, run_install
from tests.sandbox import GIT, SESSION_PATH, SandboxTest, basic_lines, git
from tests.test_describe import FAKE


class FakeScheduler:
    def __init__(self, ok=True):
        self.installed = []
        self.ok = ok

    def install(self, home_dir, minutes):
        self.installed.append((home_dir, minutes))
        return "fake schedule"

    def status(self):
        return (self.ok, "last run exited 0" if self.ok else "last run exited 1")


def which(name):
    return {"git": GIT, "claude": FAKE}.get(name)


class InstallTest(SandboxTest):
    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.root, "fresh-home")
        self.lines = []
        self.scheduler = FakeScheduler()
        self.laptop.add_transcript(basic_lines())

    def install(self, vault=None, **kwargs):
        kwargs.setdefault("machine", "newbox")
        kwargs.setdefault("which", which)
        kwargs.setdefault("transcript_root", self.laptop.transcripts)
        return run_install(self.home, vault or self.laptop.vault, out=self.lines.append, scheduler=self.scheduler, **kwargs)

    def config(self):
        with open(os.path.join(self.home, "config.json")) as f:
            return json.load(f)

    def test_install_writes_config_scratch_gitignore_and_schedule(self):
        self.assertEqual(self.install(), 0, self.lines)
        settings = self.config()
        self.assertEqual((settings["vault_path"], settings["machine"]), (self.laptop.vault, "newbox"))
        self.assertEqual((settings["git_bin"], settings["claude_bin"]), (GIT, FAKE))
        self.assertTrue(os.path.isdir(os.path.join(self.home, "scratch")))
        self.assertEqual(self.laptop.read(".gitignore"), ".obsidian/workspace*.json\n.trash/\n")
        self.assertEqual(self.scheduler.installed, [(self.home, 60)])
        self.assertTrue(any(line.startswith("PASS") for line in self.lines))

    def test_gitignore_lines_are_added_once_and_existing_lines_kept(self):
        with open(self.laptop.path(".gitignore"), "w") as f:
            f.write("*.tmp\n.trash/")
        self.install()
        self.install()
        self.assertEqual(self.laptop.read(".gitignore"), "*.tmp\n.trash/\n.obsidian/workspace*.json\n")

    def test_reinstall_keeps_existing_settings(self):
        self.install()
        settings = self.config()
        settings["exclude_cwd_prefixes"] = ["/private"]
        with open(os.path.join(self.home, "config.json"), "w") as f:
            json.dump(settings, f)
        self.install()
        self.assertEqual(self.config()["exclude_cwd_prefixes"], ["/private"])

    def test_missing_vault_is_cloned_from_the_repo_url(self):
        vault = os.path.join(self.root, "cloned-vault")
        self.assertEqual(self.install(vault, repo_url=self.origin), 0, self.lines)
        self.assertEqual(git(vault, "remote", "get-url", "origin"), self.origin)

    def test_missing_vault_without_a_url_fails(self):
        self.assertEqual(self.install(os.path.join(self.root, "nowhere")), 1)
        self.assertFalse(os.path.exists(os.path.join(self.home, "config.json")))

    def test_vault_without_a_remote_fails(self):
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        git(plain, "init", "-q", "-b", "main")
        self.assertEqual(self.install(plain), 1)
        self.assertIn("remote", " ".join(self.lines))

    def test_missing_claude_fails(self):
        self.assertEqual(self.install(which=lambda name: GIT if name == "git" else None), 1)
        self.assertIn("claude", " ".join(self.lines))

    def test_taken_machine_name_needs_force(self):
        self.laptop.sync()
        self.assertEqual(self.install(machine="laptop"), 1)
        self.assertIn("already exists", " ".join(self.lines))
        self.assertEqual(self.install(machine="laptop", force=True), 0, self.lines)

    def test_taken_name_is_seen_even_when_the_local_clone_is_behind(self):
        other = self.machine("other")
        other.add_transcript(basic_lines())
        other.sync()
        self.assertEqual(self.install(machine="other"), 1)

    def test_invalid_machine_name_fails(self):
        self.assertEqual(self.install(machine="My_Laptop"), 1)

    def test_default_machine_is_the_short_hostname(self):
        expected = socket.gethostname().split(".")[0].lower()
        self.assertEqual(default_machine(), "".join(c if c.isalnum() else "-" for c in expected).strip("-"))


class DoctorTest(SandboxTest):
    def setUp(self):
        super().setUp()
        self.laptop.set_config(claude_bin=FAKE)
        self.laptop.add_transcript(basic_lines())
        self.lines = []

    def doctor(self, scheduler=None):
        return run_doctor(self.laptop.home, out=self.lines.append, scheduler=scheduler or FakeScheduler())

    def failures(self):
        return [line for line in self.lines if line.startswith("FAIL")]

    def test_all_checks_pass_on_a_working_setup(self):
        self.assertEqual(self.doctor(), 0, self.lines)
        self.assertEqual(len(self.lines), 5)
        self.assertTrue(all(line.startswith("PASS ") for line in self.lines))

    def test_unreachable_remote_is_named(self):
        git(self.laptop.vault, "remote", "set-url", "origin", os.path.join(self.root, "missing.git"))
        self.assertEqual(self.doctor(), 1)
        self.assertEqual(len(self.failures()), 1)
        self.assertTrue(self.failures()[0].startswith("FAIL vault remote"))

    def test_failing_claude_is_named(self):
        os.environ["FAKE_CLAUDE_MODE"] = "fail"
        self.addCleanup(os.environ.pop, "FAKE_CLAUDE_MODE", None)
        self.assertEqual(self.doctor(), 1)
        self.assertTrue(self.failures()[0].startswith("FAIL claude"))

    def test_empty_transcript_root_is_named(self):
        self.laptop.set_config(claude_bin=FAKE, transcript_root=os.path.join(self.root, "empty"))
        self.assertEqual(self.doctor(), 1)
        self.assertTrue(self.failures()[0].startswith("FAIL transcripts"))

    def test_failing_schedule_is_named(self):
        self.assertEqual(self.doctor(FakeScheduler(ok=False)), 1)
        self.assertEqual(self.failures(), ["FAIL schedule: last run exited 1"])

    def test_old_unpushed_reccap_commit_is_named(self):
        os.makedirs(os.path.dirname(self.laptop.path(SESSION_PATH)))
        with open(self.laptop.path(SESSION_PATH), "w") as f:
            f.write("x\n")
        git(self.laptop.vault, "add", ".")
        os.environ["GIT_COMMITTER_DATE"] = "2020-01-01T00:00:00+00:00"
        self.addCleanup(os.environ.pop, "GIT_COMMITTER_DATE", None)
        git(self.laptop.vault, "commit", "-q", "-m", "reccap: laptop 2020-01-01T00:00:00Z")
        self.assertEqual(self.doctor(), 1)
        self.assertTrue(self.failures()[0].startswith("FAIL unpushed commits"))

    def test_fresh_unpushed_commit_passes(self):
        self.laptop.sync(no_push=True)
        self.assertEqual(self.doctor(), 0, self.lines)
