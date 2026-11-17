import os
import subprocess
import sys

from tests.sandbox import SESSION_PATH, SandboxTest, basic_lines

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CliTest(SandboxTest):
    def run_cli(self, *args, command=None):
        env = dict(os.environ, RECCAP_HOME=self.laptop.home, PYTHONPATH=ROOT, TZ="Asia/Kolkata")
        command = command or [sys.executable, "-m", "reccap"]
        return subprocess.run([*command, *args], check=False, capture_output=True, text=True, env=env, cwd=self.root)

    def test_sync_dry_run_prints_the_target_path(self):
        self.laptop.add_transcript(basic_lines())
        result = self.run_cli("sync", "--dry-run")
        self.assertEqual((result.returncode, result.stdout), (0, SESSION_PATH + "\n"))

    def test_sync_no_push_through_the_wrapper_script(self):
        self.laptop.add_transcript(basic_lines())
        result = self.run_cli("sync", "--no-push", command=[os.path.join(ROOT, "bin", "reccap")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.laptop.commits(), 2)
        self.assertNotIn(SESSION_PATH, self.origin_files())

    def test_invalid_since_is_rejected(self):
        result = self.run_cli("sync", "--since", "yesterday")
        self.assertEqual(result.returncode, 2)

    def test_no_command_prints_usage(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: reccap", result.stderr)

    def test_day_writes_the_page_for_the_given_date(self):
        self.laptop.add_transcript(basic_lines())
        result = self.run_cli("day", "2026-11-14", "--no-push")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), self.laptop.path("daily/2026-11-14.md"))
        self.assertIn("- 09:12-09:13 · [Add backoff.]", self.laptop.read("daily/2026-11-14.md"))

    def test_day_rejects_a_bad_date(self):
        self.assertEqual(self.run_cli("day", "14-11-2026").returncode, 2)

    def test_doctor_names_the_failing_checks_and_exits_non_zero(self):
        result = self.run_cli("doctor")
        self.assertEqual(result.returncode, 1)
        self.assertIn("PASS vault remote", result.stdout)
        self.assertIn("FAIL claude", result.stdout)

    def test_install_requires_a_vault(self):
        self.assertEqual(self.run_cli("install").returncode, 2)

    def test_help_lists_every_command(self):
        result = self.run_cli("--help")
        for name in ("install", "sync", "day", "doctor", "uninstall"):
            self.assertIn(name, result.stdout)
