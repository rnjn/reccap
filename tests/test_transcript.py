import unittest
from datetime import datetime, timezone

from reccap.transcript import is_loggable, read_entries
from tests.helpers import CWD, assistant, base, text, tool, user, write_transcript

T1 = "2026-11-14T03:42:03.120Z"
T2 = "2026-11-14T03:42:10.000Z"


class ReadEntriesTest(unittest.TestCase):
    def read(self, *lines):
        return read_entries(write_transcript(lines))

    def test_typed_prompt(self):
        entries = self.read(user(T1, "Add backoff."))
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual((e.kind, e.text, e.cwd, e.branch), ("prompt", "Add backoff.", CWD, "fix/retry-backoff"))
        self.assertEqual(e.time, datetime(2026, 11, 14, 3, 42, 3, 120000, tzinfo=timezone.utc))
        self.assertFalse(e.slash)

    def test_prompt_without_origin_field_is_kept(self):
        entries = self.read(user(T1, "Add backoff.", human=False))
        self.assertEqual([e.text for e in entries], ["Add backoff."])

    def test_slash_command(self):
        raw = "<command-name>/review</command-name>\n  <command-message>review</command-message>\n  <command-args>src main</command-args>"
        entries = self.read(user(T1, raw, human=False))
        self.assertEqual([(e.kind, e.text, e.slash) for e in entries], [("prompt", "/review src main", True)])

    def test_tool_result_is_not_a_prompt(self):
        result = user(T1, [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}], human=False)
        self.assertEqual(self.read(result), [])

    def test_injected_entries_are_skipped(self):
        entries = self.read(
            user(T1, "caveat", human=False, isMeta=True),
            user(T1, "sub", isSidechain=True),
            user(T1, "summary", human=False, isCompactSummary=True),
            user(T1, "<task-notification>done</task-notification>", human=False, origin={"kind": "task-notification"}),
            user(T1, "report", human=False, origin={"kind": "peer"}),
            user(T1, "<local-command-stdout>ok</local-command-stdout>", human=False),
            user(T1, [text("[Request interrupted by user]")], human=False),
        )
        self.assertEqual(entries, [])

    def test_half_written_last_line_is_skipped(self):
        entries = self.read(user(T1, "Add backoff."), '{"type": "user", "mess')
        self.assertEqual(len(entries), 1)

    def test_unknown_types_and_missing_timestamps_are_skipped(self):
        no_time = user(T1, "x")
        del no_time["timestamp"]
        entries = self.read({"type": "ai-title", "aiTitle": "t"}, no_time, user(T1, "kept"))
        self.assertEqual([e.text for e in entries], ["kept"])

    def test_entries_from_a_parent_session_are_skipped(self):
        parent = user(T1, "old prompt")
        parent["sessionId"] = "eb32cb4b-bb1c-40ad-945d-1a241d0f4888"
        entries = self.read(parent, user(T2, "new prompt"))
        self.assertEqual([e.text for e in entries], ["new prompt"])

    def test_image_block(self):
        entries = self.read(user(T1, [text("why this?"), {"type": "image", "source": {}}]))
        self.assertEqual(entries[0].text, "why this?\n\n[image]")

    def test_assistant_parts_keep_order_and_drop_thinking(self):
        entries = self.read(
            assistant(T2, {"type": "thinking", "thinking": "hmm"}, text("Looking."), tool("Read", file_path="/a/b.py"), text("Done."))
        )
        self.assertEqual(entries[0].kind, "assistant")
        self.assertEqual(entries[0].parts, [("text", "Looking."), ("tool", "Read", {"file_path": "/a/b.py"}), ("text", "Done.")])

    def test_assistant_error_and_sidechain_entries_are_skipped(self):
        entries = self.read(assistant(T2, text("API Error"), isApiErrorMessage=True), assistant(T2, text("sub"), isSidechain=True))
        self.assertEqual(entries, [])

    def test_compaction(self):
        boundary = base(T2)
        boundary.update({"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"})
        other = base(T2)
        other.update({"type": "system", "subtype": "turn_duration"})
        self.assertEqual([e.kind for e in self.read(boundary, other)], ["compaction"])


class IsLoggableTest(unittest.TestCase):
    def read(self, *lines):
        return read_entries(write_transcript(lines))

    def test_session_without_prompts_is_not_loggable(self):
        self.assertFalse(is_loggable(self.read(assistant(T2, text("hi")))))

    def test_lone_slash_command_is_not_loggable(self):
        raw = "<command-name>/exit</command-name>"
        self.assertFalse(is_loggable(self.read(user(T1, raw, human=False))))

    def test_slash_command_with_a_reply_is_loggable(self):
        raw = "<command-name>/review</command-name>"
        self.assertTrue(is_loggable(self.read(user(T1, raw, human=False), assistant(T2, text("Reviewing.")))))

    def test_typed_prompt_is_loggable(self):
        self.assertTrue(is_loggable(self.read(user(T1, "hello"))))


if __name__ == "__main__":
    unittest.main()
