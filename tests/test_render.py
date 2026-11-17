import os
import unittest

from reccap import frontmatter
from reccap.render import fallback_description, prompts_hash, render_session, session_relpath
from reccap.transcript import read_entries
from tests.helpers import CWD, FIXTURES, IST, SID, assistant, base, fixture, text, tool, user, write_transcript


def multiday_lines():
    on_main = user("2026-11-14T18:20:00Z", "Start on the backoff")
    on_main["gitBranch"] = "main"
    boundary = base("2026-11-14T18:40:00Z")
    boundary.update({"type": "system", "subtype": "compact_boundary"})
    return [
        on_main,
        assistant("2026-11-14T18:21:00Z", text("On it.")),
        assistant("2026-11-14T18:35:00Z", text("Done with the first pass.")),
        boundary,
        user("2026-11-15T04:30:00Z", "<command-name>/review</command-name><command-args>src</command-args>", human=False),
        user("2026-11-15T04:32:00Z", "Ship it"),
        assistant("2026-11-15T04:32:44Z", tool("Bash", command="git push")),
    ]


def render(lines, **kwargs):
    entries = read_entries(write_transcript(lines))
    options = {"machine": "laptop", "repo": "payments-api", "tz": IST}
    options.update(kwargs)
    return render_session(SID, entries, **options)


def body(lines, **kwargs):
    return frontmatter.parse(render(lines, **kwargs))[1]


class GoldenTest(unittest.TestCase):
    maxDiff = None

    def test_basic_session_matches_the_spec_example(self):
        out = render_session(
            SID,
            read_entries(_copy_as(SID, "basic.jsonl")),
            machine="laptop",
            repo="payments-api",
            tz=IST,
            description="Fix retry backoff in the webhook sender",
            description_source="model",
        )
        self.assertEqual(out, fixture("basic.md"))
        self.assertNotIn("SECRET FILE BODY", out)

    def test_session_crossing_midnight(self):
        self.assertEqual(render(multiday_lines()), fixture("multiday.md"))

    def test_rendering_twice_gives_the_same_bytes(self):
        self.assertEqual(render(multiday_lines()), render(multiday_lines()))


def _copy_as(sid, name):
    with open(os.path.join(FIXTURES, name)) as f:
        return write_transcript([line.rstrip("\n") for line in f], sid=sid)


class BodyTest(unittest.TestCase):
    def test_heading_lines_in_prompts_and_replies_are_escaped(self):
        out = body([user("2026-11-14T03:00:00Z", "# Title\n## 2026-11-14\nplain"), assistant("2026-11-14T03:01:00Z", text("### 09:00 Prompt"))])
        self.assertIn("\\# Title\n\\## 2026-11-14\nplain", out)
        self.assertIn("\\### 09:00 Prompt", out)
        self.assertEqual(out.count("\n## "), 1)
        self.assertEqual(out.count("\n### "), 2)

    def test_long_prompt_is_cut(self):
        out = body([user("2026-11-14T03:00:00Z", "x" * 4500)])
        self.assertIn("x" * 4000 + "\n\n[... 500 more characters]", out)
        self.assertNotIn("x" * 4001, out)

    def test_cut_inside_a_code_fence_closes_the_fence(self):
        out = body([user("2026-11-14T03:00:00Z", "```\n" + "y" * 5000 + "\n```")])
        self.assertIn("y\n```\n\n[... ", out)

    def test_long_command_is_cut_to_120_characters_on_one_line(self):
        out = body([user("2026-11-14T03:00:00Z", "go"), assistant("2026-11-14T03:01:00Z", tool("Bash", command="echo a\necho " + "b" * 200))])
        line = next(x for x in out.splitlines() if x.startswith("- `Bash`"))
        self.assertEqual(line, "- `Bash` " + ("echo a echo " + "b" * 200)[:120] + "…")

    def test_tool_arguments(self):
        out = body(
            [
                user("2026-11-14T03:00:00Z", "go"),
                assistant(
                    "2026-11-14T03:01:00Z",
                    tool("Read", file_path="/etc/hosts"),
                    tool("Read", file_path=CWD + "/a.py"),
                    tool("Grep", pattern="retry", path=CWD),
                    tool("WebFetch", url="https://example.com", prompt="summarise"),
                    tool("WebSearch", query="backoff jitter"),
                    tool("Agent", description="Find callers", prompt="long"),
                    tool("Skill", skill="code-review"),
                    tool("AskUserQuestion", questions=[]),
                ),
            ]
        )
        self.assertIn(
            "- `Read` /etc/hosts\n- `Read` a.py\n- `Grep` retry\n- `WebFetch` https://example.com\n"
            "- `WebSearch` backoff jitter\n- `Agent` Find callers\n- `Skill` code-review\n- `AskUserQuestion`\n",
            out,
        )

    def test_assistant_entry_with_only_thinking_makes_no_heading(self):
        out = body([user("2026-11-14T03:00:00Z", "go"), assistant("2026-11-14T03:01:00Z", {"type": "thinking", "thinking": "x"})])
        self.assertNotIn("Claude", out)


class FrontmatterTest(unittest.TestCase):
    def test_values_that_need_quotes_are_quoted_and_read_back(self):
        out = render([user("2026-11-14T03:00:00Z", "go")], repo="#notes", description='Fix: the "retry" bug')
        self.assertIn('repo: "#notes"\n', out)
        self.assertIn('description: "Fix: the \\"retry\\" bug"\n', out)
        meta, _ = frontmatter.parse(out)
        self.assertEqual(meta["repo"], "#notes")
        self.assertEqual(meta["description"], 'Fix: the "retry" bug')
        self.assertEqual(meta["active_dates"], ["2026-11-14"])
        self.assertEqual(meta["prompt_count"], "1")

    def test_parse_without_frontmatter(self):
        self.assertEqual(frontmatter.parse("# Title\n"), ({}, "# Title\n"))


class HelpersTest(unittest.TestCase):
    def entries(self, *lines):
        return read_entries(write_transcript(lines))

    def test_fallback_description_is_first_prompt_on_one_line_cut_to_100(self):
        entries = self.entries(user("2026-11-14T03:00:00Z", "fix\nthe " + "z" * 200))
        self.assertEqual(fallback_description(entries), ("fix the " + "z" * 200)[:100])

    def test_fallback_description_prefers_a_typed_prompt_over_a_slash_command(self):
        slash = user("2026-11-14T03:00:00Z", "<command-name>/login</command-name>", human=False)
        self.assertEqual(fallback_description(self.entries(slash, user("2026-11-14T03:01:00Z", "fix the cert"))), "fix the cert")
        self.assertEqual(fallback_description(self.entries(slash)), "/login")

    def test_prompts_hash_changes_only_with_prompts(self):
        one = self.entries(user("2026-11-14T03:00:00Z", "a"))
        same = self.entries(user("2026-11-14T03:00:00Z", "a"), assistant("2026-11-14T03:01:00Z", text("r")))
        more = self.entries(user("2026-11-14T03:00:00Z", "a"), user("2026-11-14T03:02:00Z", "b"))
        self.assertEqual(prompts_hash(one), prompts_hash(same))
        self.assertNotEqual(prompts_hash(one), prompts_hash(more))

    def test_session_relpath_uses_local_start_date(self):
        entries = self.entries(user("2026-11-30T20:00:00Z", "a"))
        self.assertEqual(session_relpath("laptop", SID, entries, IST), "sessions/laptop/2026-12/2026-12-01-550e8400.md")


if __name__ == "__main__":
    unittest.main()
