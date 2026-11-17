import os
from datetime import date

from tests.helpers import IST, fixture
from tests.sandbox import SandboxTest, basic_lines, git
from worklog import frontmatter
from worklog.day import run_day

DAY = "daily/2026-11-14.md"


def session_text(machine, repo, sid, branch, description, days):
    dates = list(days)
    head = frontmatter.dump(
        [
            ("session_id", sid),
            ("machine", machine),
            ("repo", repo),
            ("branches", [branch]),
            ("started", dates[0] + "T00:00:00+05:30"),
            ("active_dates", dates),
            ("description", description),
        ]
    )
    lines = ["# " + description]
    for day, (first, last, prompts) in days.items():
        lines += ["", "## " + day, "", f"### {first} Prompt", "", "\\### 23:59 Prompt"]
        lines += ["", "### 12:00 Prompt"] * (prompts - 1)
        lines += ["", f"### {last} Claude", "", "ok"]
    return head + "\n".join(lines) + "\n"


class DayTest(SandboxTest):
    def setUp(self):
        super().setUp()
        self.devbox = self.machine("devbox")

    def add_session(self, machine, when, repo, sid, branch, description, days):
        start = next(iter(days))
        relpath = f"sessions/{machine.name}/{start[:7]}/{start}-{sid[:8]}.md"
        os.makedirs(os.path.dirname(machine.path(relpath)), exist_ok=True)
        with open(machine.path(relpath), "w") as f:
            f.write(session_text(machine.name, repo, sid, branch, description, days))
        git(machine.vault, "add", "sessions")
        os.environ["GIT_COMMITTER_DATE"] = when
        self.addCleanup(os.environ.pop, "GIT_COMMITTER_DATE", None)
        git(machine.vault, "commit", "-q", "-m", "sessions")
        git(machine.vault, "pull", "-q", "--rebase", "origin", "main")
        git(machine.vault, "push", "-q", "origin", "main")
        os.environ.pop("GIT_COMMITTER_DATE")

    def spec_sessions(self):
        self.add_session(
            self.devbox,
            "2026-11-14T19:02:10+05:30",
            "infra",
            "9b1c22aa-0000-0000-0000-000000000000",
            "main",
            "Rotate the staging database credentials",
            {"2026-11-14": ("14:05", "14:50", 6)},
        )
        self.add_session(
            self.laptop,
            "2026-11-14T08:00:00+05:30",
            "payments-api",
            "03fe7c10-0000-0000-0000-000000000000",
            "main",
            "Explain the idempotency key design",
            {"2026-11-13": ("16:00", "16:30", 2), "2026-11-14": ("11:30", "11:42", 3)},
        )
        self.add_session(
            self.laptop,
            "2026-11-15T08:55:00+05:30",
            "payments-api",
            "550e8400-0000-0000-0000-000000000000",
            "fix/retry-backoff",
            "Fix retry backoff in the webhook sender",
            {"2026-11-14": ("09:12", "17:40", 23), "2026-11-15": ("10:00", "10:02", 1)},
        )

    def day(self, day="2026-11-14", **kwargs):
        kwargs.setdefault("no_sync", True)
        kwargs.setdefault("tz", IST)
        kwargs.setdefault("out", lambda line: None)
        return run_day(self.laptop.home, day, **kwargs)

    def test_day_page_matches_the_spec_example(self):
        self.spec_sessions()
        self.assertEqual(self.day(), 0)
        self.maxDiff = None
        self.assertEqual(self.laptop.read(DAY), fixture("day.md"))
        self.assertIn(DAY, self.origin_files())
        self.assertEqual(git(self.laptop.vault, "log", "-1", "--format=%s"), "worklog: day 2026-11-14")

    def test_multi_day_session_shows_each_days_own_times(self):
        self.spec_sessions()
        self.day("2026-11-15")
        page = self.laptop.read("daily/2026-11-15.md")
        self.assertIn(
            "- 10:00-10:02 · [Fix retry backoff in the webhook sender](../sessions/laptop/2026-11/2026-11-14-550e8400.md#2026-11-15)"
            " · `fix/retry-backoff` · 1 prompt · started 2026-11-14\n",
            page,
        )
        self.assertIn("# 2026-11-15 Sunday\n", page)
        self.assertIn("session_count: 1\n", page)

    def test_empty_day(self):
        self.spec_sessions()
        self.day("2026-11-10")
        page = self.laptop.read("daily/2026-11-10.md")
        self.assertIn("session_count: 0\nmachines: []\n", page)
        self.assertIn(
            "<!-- worklog:start -->\nNo sessions recorded.\n\nLast sync: devbox 2026-11-14 19:02 · laptop 2026-11-15 08:55\n<!-- worklog:end -->\n",
            page,
        )

    def test_hand_edits_outside_the_markers_survive_a_rerun(self):
        self.spec_sessions()
        self.day("2026-11-10")
        page = self.laptop.read("daily/2026-11-10.md")
        edited = page.replace("# 2026-11-10 Tuesday\n", "# 2026-11-10 Tuesday\n\nStandup: ask about the deploy.\n") + "\n## Notes\n\nmine\n"
        edited = edited.replace("date: 2026-11-10\n", "date: 2026-11-10\ntags: [standup]\n")
        with open(self.laptop.path("daily/2026-11-10.md"), "w") as f:
            f.write(edited)
        self.add_session(self.devbox, "2026-11-16T09:00:00+05:30", "infra", "aaaa1111-0000-0000-0000-000000000000", "main", "Late", {"2026-11-10": ("08:00", "08:05", 1)})
        self.day("2026-11-10")
        page = self.laptop.read("daily/2026-11-10.md")
        self.assertIn("Standup: ask about the deploy.\n", page)
        self.assertTrue(page.endswith("<!-- worklog:end -->\n\n## Notes\n\nmine\n"))
        self.assertIn("tags: [standup]\n", page)
        self.assertIn("session_count: 1\nmachines: [devbox]\n", page)
        self.assertIn("- 08:00-08:05 · [Late]", page)
        self.assertNotIn("No sessions recorded.", page)

    def test_page_without_markers_gets_the_block_appended(self):
        os.makedirs(self.laptop.path("daily"))
        with open(self.laptop.path(DAY), "w") as f:
            f.write("my own notes\n")
        self.day()
        page = self.laptop.read(DAY)
        self.assertTrue(page.startswith("my own notes\n\n<!-- worklog:start -->\n"))

    def test_rerun_with_no_change_makes_no_commit(self):
        self.spec_sessions()
        self.day()
        before = self.laptop.commits()
        self.day()
        self.assertEqual(self.laptop.commits(), before)

    def test_no_push_and_no_pull(self):
        self.spec_sessions()
        git(self.laptop.vault, "reset", "-q", "--hard", "HEAD~1")
        self.day(no_pull=True, no_push=True)
        self.assertNotIn("550e8400", self.laptop.read(DAY))
        self.assertNotIn(DAY, self.origin_files())

    def test_pull_failure_warns_and_uses_local_data(self):
        self.spec_sessions()
        git(self.laptop.vault, "remote", "set-url", "origin", os.path.join(self.root, "missing.git"))
        warnings = []
        self.assertEqual(self.day(out=warnings.append), 0)
        self.assertTrue(any("pull failed" in w for w in warnings))
        self.assertIn("550e8400", self.laptop.read(DAY))

    def test_default_date_is_yesterday(self):
        self.spec_sessions()
        run_day(self.laptop.home, None, no_sync=True, tz=IST, today=date(2026, 11, 15), out=lambda line: None)
        self.assertTrue(os.path.exists(self.laptop.path(DAY)))

    def test_day_syncs_this_machine_first(self):
        self.laptop.add_transcript(basic_lines())
        self.day(no_sync=False)
        self.assertIn("[Add backoff.](../sessions/laptop/2026-11/2026-11-14-550e8400.md#2026-11-14)", self.laptop.read(DAY))

    def test_open_uses_an_obsidian_url(self):
        opened = []
        self.day(open_page=True, opener=opened.append)
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].startswith("obsidian://open?path="))
        self.assertTrue(opened[0].endswith("daily%2F2026-11-14.md"))

    def test_brackets_in_descriptions_are_escaped(self):
        self.add_session(self.devbox, "2026-11-14T19:00:00+05:30", "infra", "bbbb2222-0000-0000-0000-000000000000", "main", "Fix [urgent] bug", {"2026-11-14": ("08:00", "08:05", 2)})
        self.day()
        self.assertIn("[Fix \\[urgent\\] bug](", self.laptop.read(DAY))
