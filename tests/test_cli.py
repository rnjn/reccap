import os
import subprocess
import sys

from tests.sandbox import SESSION_PATH, SandboxTest, basic_lines

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CliTest(SandboxTest):
    def run_cli(self, *args, command=None):
        env = dict(os.environ, WORKLOG_HOME=self.laptop.home, PYTHONPATH=ROOT, TZ="Asia/Kolkata")
        command = command or [sys.executable, "-m", "worklog"]
        return subprocess.run([*command, *args], check=False, capture_output=True, text=True, env=env, cwd=self.root)

    def test_sync_dry_run_prints_the_target_path(self):
        self.laptop.add_transcript(basic_lines())
        result = self.run_cli("sync", "--dry-run")
        self.assertEqual((result.returncode, result.stdout), (0, SESSION_PATH + "\n"))

    def test_sync_no_push_through_the_wrapper_script(self):
        self.laptop.add_transcript(basic_lines())
        result = self.run_cli("sync", "--no-push", command=[os.path.join(ROOT, "bin", "worklog")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.laptop.commits(), 2)
        self.assertNotIn(SESSION_PATH, self.origin_files())

    def test_invalid_since_is_rejected(self):
        result = self.run_cli("sync", "--since", "yesterday")
        self.assertEqual(result.returncode, 2)

    def test_no_command_prints_usage(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: worklog", result.stderr)
