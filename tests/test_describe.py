import json
import os
import tempfile

from reccap import frontmatter
from reccap.describe import build_input, describe
from reccap.transcript import read_entries
from tests.helpers import assistant, text, user, write_transcript
from tests.sandbox import SESSION_PATH, SandboxTest, basic_lines

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_claude.py")
REPLY = "Fix retry backoff in the webhook sender"


def entries_of(*lines):
    return read_entries(write_transcript(lines))


class FakeClaudeTest(SandboxTest):
    def setUp(self):
        super().setUp()
        self.calls_path = os.path.join(self.root, "claude-calls.jsonl")
        self.set_env("FAKE_CLAUDE_LOG", self.calls_path)
        self.set_env("FAKE_CLAUDE_MODE", "ok")
        self.laptop.set_config(claude_bin=FAKE)

    def set_env(self, key, value):
        previous = os.environ.get(key)
        os.environ[key] = value
        self.addCleanup(self._restore, key, previous)

    def calls(self):
        if not os.path.exists(self.calls_path):
            return []
        with open(self.calls_path) as f:
            return [json.loads(line) for line in f]

    def meta(self):
        return frontmatter.parse(self.laptop.read(SESSION_PATH))[0]


class BuildInputTest(FakeClaudeTest):
    def test_prompts_and_last_reply_are_cut(self):
        entries = entries_of(
            user("2026-11-14T03:00:00Z", "p" * 600),
            assistant("2026-11-14T03:01:00Z", text("early reply")),
            assistant("2026-11-14T03:02:00Z", text("r" * 1500)),
        )
        built = build_input(entries)
        self.assertIn("p" * 500, built)
        self.assertNotIn("p" * 501, built)
        self.assertIn("r" * 1000, built)
        self.assertNotIn("r" * 1001, built)
        self.assertNotIn("early reply", built)

    def test_total_is_capped_keeping_earliest_and_latest_prompts(self):
        lines = [user(f"2026-11-14T03:{i:02d}:00Z", f"prompt-{i:02d} " + "x" * 480) for i in range(40)]
        built = build_input(entries_of(*lines))
        self.assertLessEqual(len(built), 8000)
        self.assertIn("prompt-00", built)
        self.assertIn("prompt-39", built)
        self.assertNotIn("prompt-20", built)


class DescribeTest(FakeClaudeTest):
    def describe(self, **overrides):
        settings = {"claude_bin": FAKE, "describe_model": None, "describe_timeout_seconds": 60}
        settings.update(overrides)
        self.scratch = os.path.realpath(tempfile.mkdtemp())
        return describe(entries_of(*basic_lines()), settings, self.scratch)

    def test_success_returns_the_model_line(self):
        self.assertEqual(self.describe(), (REPLY, "model"))
        call = self.calls()[0]
        self.assertEqual(call["argv"], ["-p", "--no-session-persistence", "--tools", ""])
        self.assertEqual(call["cwd"], self.scratch)
        self.assertIn("Add backoff.", call["stdin"])
        self.assertIn("at most 100 characters", call["stdin"])

    def test_model_flag_is_passed_when_configured(self):
        self.describe(describe_model="haiku")
        self.assertEqual(self.calls()[0]["argv"][-2:], ["--model", "haiku"])

    def test_reply_is_cleaned_to_one_plain_line(self):
        self.set_env("FAKE_CLAUDE_REPLY", '\n"Fix the `sender` retry bug."\nIt was about retries.')
        self.assertEqual(self.describe(), ("Fix the `sender` retry bug", "model"))

    def test_long_reply_is_cut_to_100_characters(self):
        self.set_env("FAKE_CLAUDE_REPLY", "w" * 150)
        self.assertEqual(self.describe(), ("w" * 100, "model"))

    def test_timeout_falls_back_to_the_first_prompt(self):
        self.set_env("FAKE_CLAUDE_MODE", "slow")
        self.assertEqual(self.describe(describe_timeout_seconds=0.5), ("Add backoff.", "fallback"))

    def test_error_exit_falls_back(self):
        self.set_env("FAKE_CLAUDE_MODE", "fail")
        self.assertEqual(self.describe(), ("Add backoff.", "fallback"))

    def test_missing_binary_falls_back(self):
        self.assertEqual(self.describe(claude_bin="/nonexistent/claude"), ("Add backoff.", "fallback"))

    def test_empty_reply_falls_back(self):
        self.set_env("FAKE_CLAUDE_REPLY", "  ")
        self.assertEqual(self.describe(), ("Add backoff.", "fallback"))


class SyncDescribeTest(FakeClaudeTest):
    def touch(self, lines, stamp):
        path = self.laptop.add_transcript(lines)
        os.utime(path, (stamp, stamp))

    def test_sync_writes_the_model_description(self):
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        meta = self.meta()
        self.assertEqual((meta["description"], meta["description_source"]), (REPLY, "model"))
        self.assertIn("# " + REPLY + "\n", self.laptop.read(SESSION_PATH))
        self.assertEqual(self.calls()[0]["cwd"], os.path.realpath(os.path.join(self.laptop.home, "scratch")))

    def test_description_is_cached_until_a_new_prompt_arrives(self):
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        self.touch([*basic_lines(), assistant("2026-11-14T03:50:00Z", text("One more thing."))], 2000000000)
        self.laptop.sync()
        self.assertIn("One more thing.", self.laptop.read(SESSION_PATH))
        self.assertEqual(len(self.calls()), 1)
        self.touch([*basic_lines(), user("2026-11-14T04:00:00Z", "Add jitter too.")], 2000000100)
        self.laptop.sync()
        self.assertEqual(len(self.calls()), 2)

    def test_fallback_is_retried_on_the_next_run(self):
        self.set_env("FAKE_CLAUDE_MODE", "fail")
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        self.assertEqual(self.meta()["description_source"], "fallback")
        self.assertIn(SESSION_PATH, self.origin_files())
        self.set_env("FAKE_CLAUDE_MODE", "ok")
        self.laptop.sync()
        self.assertEqual((self.meta()["description"], self.meta()["description_source"]), (REPLY, "model"))

    def test_model_description_is_not_requested_again_when_nothing_changed(self):
        self.laptop.add_transcript(basic_lines())
        self.laptop.sync()
        self.laptop.sync()
        self.assertEqual(len(self.calls()), 1)
