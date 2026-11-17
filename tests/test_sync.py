import fcntl
import os
import re
import tempfile
import unittest

from reccap.sync import find_repo
from tests.helpers import SID, assistant, text, user
from tests.sandbox import SESSION_PATH, SandboxTest, basic_lines, git


class SyncTest(SandboxTest):
    def test_sync_writes_the_session_and_pushes_it(self):
        self.laptop.add_transcript(basic_lines())
        self.assertEqual(self.laptop.sync(), 0)
        self.assertIn("### 09:12 Prompt\n\nAdd backoff.", self.laptop.read(SESSION_PATH))
        self.assertIn(SESSION_PATH, self.origin_files())
        self.assertRegex(git(self.laptop.vault, "log", "-1", "--format=%s"), r"^reccap: laptop \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_second_sync_with_no_activity_makes_no_commit(self):
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        before = self.laptop.commits()
        self.laptop.sync()
        self.assertEqual(self.laptop.commits(), before)

    def test_new_prompt_updates_the_same_file(self):
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        path = self.laptop.add_transcript([*basic_lines(), user("2026-11-15T04:00:00Z", "Now add jitter.")])
        os.utime(path, (2000000000, 2000000000))
        self.laptop.sync()
        self.assertIn("## 2026-11-15", self.laptop.read(SESSION_PATH))
        self.assertEqual(len([f for f in self.origin_files() if f.startswith("sessions/")]), 1)

    def test_two_machines_both_reach_the_repo(self):
        devbox = self.machine("devbox")
        self.laptop.add_transcript(basic_lines())
        devbox.add_transcript(basic_lines("Rotate credentials."))
        self.assertEqual(self.laptop.sync(), 0)
        self.assertEqual(devbox.sync(), 0)
        files = self.origin_files()
        self.assertIn(SESSION_PATH, files)
        self.assertIn("sessions/2026-11/14/0912-rotate-credentials.md", files)

    def test_unrelated_notes_stay_uncommitted_and_intact(self):
        devbox = self.machine("devbox")
        devbox.add_transcript(basic_lines())
        devbox.sync()
        with open(self.laptop.path("README.md"), "a") as f:
            f.write("draft line\n")
        with open(self.laptop.path("idea.md"), "w") as f:
            f.write("an idea\n")
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        self.assertIn(SESSION_PATH, self.origin_files())
        self.assertEqual(self.laptop.read("README.md"), "vault\ndraft line\n")
        self.assertEqual(self.laptop.read("idea.md"), "an idea\n")
        self.assertNotIn("idea.md", self.origin_files())
        self.assertEqual(git(self.origin, "show", "main:README.md"), "vault")

    def test_push_failure_keeps_the_commit_and_the_next_run_pushes(self):
        self.laptop.add_transcript(basic_lines())
        git(self.laptop.vault, "remote", "set-url", "origin", os.path.join(self.root, "missing.git"))
        self.assertEqual(self.laptop.sync(), 0)
        self.assertEqual(self.laptop.commits(), 2)
        self.assertNotIn(SESSION_PATH, self.origin_files())
        git(self.laptop.vault, "remote", "set-url", "origin", self.origin)
        self.assertEqual(self.laptop.sync(), 0)
        self.assertIn(SESSION_PATH, self.origin_files())

    def test_rebase_conflict_is_aborted(self):
        other = self.machine("other")
        os.makedirs(os.path.dirname(other.path(SESSION_PATH)))
        with open(other.path(SESSION_PATH), "w") as f:
            f.write("conflicting content\n")
        git(other.vault, "add", ".")
        git(other.vault, "commit", "-q", "-m", "clash")
        git(other.vault, "push", "-q", "origin", "main")
        self.laptop.add_transcript(basic_lines())
        self.assertEqual(self.laptop.sync(), 0)
        git_dir = os.path.join(self.laptop.vault, ".git")
        self.assertFalse(os.path.exists(os.path.join(git_dir, "rebase-merge")))
        self.assertFalse(os.path.exists(os.path.join(git_dir, "rebase-apply")))
        self.assertIn("Add backoff.", self.laptop.read(SESSION_PATH))

    def test_overlapping_run_exits_at_once(self):
        self.laptop.add_transcript(basic_lines())
        with open(os.path.join(self.laptop.home, "sync.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertEqual(self.laptop.sync(), 0)
        self.assertFalse(os.path.exists(self.laptop.path(SESSION_PATH)))

    def test_dry_run_changes_nothing(self):
        self.laptop.add_transcript(basic_lines())
        printed = []
        self.assertEqual(self.laptop.sync(dry_run=True, out=printed.append), 0)
        self.assertEqual(printed, [SESSION_PATH])
        self.assertFalse(os.path.exists(self.laptop.path(SESSION_PATH)))
        self.assertEqual(self.laptop.state()["transcripts"], {})

    def test_no_push_commits_without_pushing(self):
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync(no_push=True)
        self.assertEqual(self.laptop.commits(), 2)
        self.assertNotIn(SESSION_PATH, self.origin_files())

    def test_since_reprocesses_transcripts_that_state_would_skip(self):
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        os.remove(self.laptop.path(SESSION_PATH))
        self.laptop.sync()
        self.assertFalse(os.path.exists(self.laptop.path(SESSION_PATH)))
        self.laptop.sync(since="2000-01-01")
        self.assertTrue(os.path.exists(self.laptop.path(SESSION_PATH)))

    def test_since_ignores_older_transcripts(self):
        path = self.laptop.add_transcript(basic_lines())
        os.utime(path, (946684800, 946684800))
        self.laptop.sync(since="2026-01-01")
        self.assertFalse(os.path.exists(self.laptop.path(SESSION_PATH)))

    def test_excluded_cwd_is_never_written(self):
        self.laptop.set_config(exclude_cwd_prefixes=["/Users/me/code"])
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        self.assertFalse(os.path.exists(self.laptop.path("sessions")))

    def test_scratch_project_and_nested_transcripts_are_skipped(self):
        scratch = os.path.realpath(os.path.join(self.laptop.home, "scratch"))
        self.laptop.add_transcript(basic_lines(), project=re.sub(r"[^A-Za-z0-9]", "-", scratch))
        self.laptop.add_transcript(basic_lines(), project="-Users-me-code-payments-api/" + SID + "/subagents")
        self.laptop.sync()
        self.assertFalse(os.path.exists(self.laptop.path("sessions")))

    def test_session_without_a_prompt_is_dropped(self):
        self.laptop.add_transcript([assistant("2026-11-14T03:43:00Z", text("hello"))])
        self.laptop.sync()
        self.assertFalse(os.path.exists(self.laptop.path("sessions")))

    def test_existing_file_is_reused_when_state_is_lost(self):
        old = "sessions/2026-10/31/2350-an-older-name.md"
        os.makedirs(os.path.dirname(self.laptop.path(old)))
        with open(self.laptop.path(old), "w") as f:
            f.write("---\nsession_id: " + SID + "\n---\nold\n")
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        self.assertIn("Add backoff.", self.laptop.read(old))
        self.assertFalse(os.path.exists(self.laptop.path(SESSION_PATH)))

    def test_two_sessions_with_the_same_start_and_title_get_distinct_files(self):
        self.laptop.add_transcript(basic_lines())
        other = "99999999-0000-0000-0000-000000000000"
        self.laptop.add_transcript([dict(line, sessionId=other) for line in basic_lines()], sid=other)
        self.laptop.sync()
        files = sorted(f for f in self.origin_files() if f.startswith("sessions/"))
        self.assertEqual(files, [SESSION_PATH[:-3] + "-99999999.md", SESSION_PATH])

    def test_session_name_is_used_for_the_file_name(self):
        named = [{"type": "ai-title", "aiTitle": "Retry backoff fix", "sessionId": SID}, *basic_lines()]
        self.laptop.add_transcript(named)
        self.laptop.sync()
        self.assertIn("sessions/2026-11/14/0912-retry-backoff-fix.md", self.origin_files())

    def test_file_name_stays_when_the_session_name_changes(self):
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        path = self.laptop.add_transcript([*basic_lines(), {"type": "custom-title", "customTitle": "renamed", "sessionId": SID}])
        os.utime(path, (2000000000, 2000000000))
        self.laptop.sync()
        self.assertEqual([f for f in self.origin_files() if f.startswith("sessions/")], [SESSION_PATH])

    def test_files_written_by_another_machine_are_left_alone(self):
        devbox = self.machine("devbox")
        devbox.add_transcript(basic_lines("Rotate credentials."))
        devbox.sync()
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        self.assertIn("machine: devbox\n", self.laptop.read("sessions/2026-11/14/0912-rotate-credentials.md"))
        self.assertIn("machine: laptop\n", self.laptop.read(SESSION_PATH))

    def test_a_broken_transcript_does_not_stop_the_others(self):
        self.laptop.add_transcript(["not json", "[1, 2]"], sid="11111111-0000-0000-0000-000000000000")
        self.laptop.add_transcript(basic_lines())
        self.assertEqual(self.laptop.sync(), 0)
        self.assertTrue(os.path.exists(self.laptop.path(SESSION_PATH)))

    def test_sync_log_is_written(self):
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        with open(os.path.join(self.laptop.home, "sync.log")) as f:
            self.assertIn("wrote 1", f.read())


class FindRepoTest(unittest.TestCase):
    def test_git_root_above_cwd(self):
        root = os.path.realpath(tempfile.mkdtemp())
        nested = os.path.join(root, "payments-api", "src", "webhooks")
        os.makedirs(nested)
        os.makedirs(os.path.join(root, "payments-api", ".git"))
        self.assertEqual(find_repo(nested), "payments-api")

    def test_worktree_inside_a_repo_reports_the_main_repo(self):
        root = os.path.realpath(tempfile.mkdtemp())
        worktree = os.path.join(root, "payments-api", ".claude", "worktrees", "fix")
        os.makedirs(worktree)
        os.makedirs(os.path.join(root, "payments-api", ".git"))
        open(os.path.join(worktree, ".git"), "w").close()
        self.assertEqual(find_repo(worktree), "payments-api")

    def test_no_git_root_uses_the_folder_name(self):
        self.assertEqual(find_repo("/nonexistent/path/scratchpad"), "scratchpad")


if __name__ == "__main__":
    unittest.main()
