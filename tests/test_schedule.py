import os
import plistlib
import subprocess
import tempfile
import unittest

from worklog import schedule

COMMAND = ["/usr/bin/python3", "-m", "worklog", "sync"]
ENV = {"PYTHONPATH": "/src/worklog", "WORKLOG_HOME": "/home/me/.worklog"}


class Recorder:
    def __init__(self, failing=(), stdout=None):
        self.calls = []
        self.inputs = []
        self.failing = failing
        self.stdout = stdout or {}

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        self.inputs.append(kwargs.get("input"))
        line = " ".join(args)
        code = 1 if any(f in line for f in self.failing) else 0
        out = next((v for k, v in self.stdout.items() if k in line), "")
        return subprocess.CompletedProcess(args, code, out, "")


class TextTest(unittest.TestCase):
    def test_launchd_plist(self):
        plist = plistlib.loads(schedule.launchd_plist(COMMAND, ENV, 3600, "/home/me/.worklog/launchd.log").encode())
        self.assertEqual(plist["Label"], "com.worklog.sync")
        self.assertEqual(plist["ProgramArguments"], COMMAND)
        self.assertEqual(plist["EnvironmentVariables"], ENV)
        self.assertEqual(plist["StartInterval"], 3600)
        self.assertIs(plist["RunAtLoad"], True)
        self.assertEqual(plist["StandardErrorPath"], "/home/me/.worklog/launchd.log")

    def test_systemd_units(self):
        service = schedule.systemd_service(COMMAND, ENV)
        self.assertIn("Type=oneshot\n", service)
        self.assertIn("ExecStart=/usr/bin/python3 -m worklog sync\n", service)
        self.assertIn('Environment="PYTHONPATH=/src/worklog"\n', service)
        timer = schedule.systemd_timer(60)
        self.assertIn("OnCalendar=hourly\n", timer)
        self.assertIn("Persistent=true\n", timer)
        self.assertIn("WantedBy=timers.target\n", timer)
        self.assertIn("OnCalendar=*:0/15\n", schedule.systemd_timer(15))

    def test_cron_line(self):
        self.assertEqual(
            schedule.cron_line(COMMAND, ENV, 60),
            "0 * * * * PYTHONPATH=/src/worklog WORKLOG_HOME=/home/me/.worklog /usr/bin/python3 -m worklog sync # worklog-sync",
        )
        self.assertTrue(schedule.cron_line(COMMAND, ENV, 20).startswith("*/20 * * * * "))


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.user_home = tempfile.mkdtemp()
        self.home_dir = os.path.join(self.user_home, ".worklog")

    def test_macos_writes_a_user_agent_and_loads_it(self):
        run = Recorder()
        schedule.install(self.home_dir, 60, platform="darwin", user_home=self.user_home, run=run)
        path = os.path.join(self.user_home, "Library", "LaunchAgents", "com.worklog.sync.plist")
        with open(path, "rb") as f:
            plist = plistlib.load(f)
        self.assertEqual(plist["ProgramArguments"][1:], ["-m", "worklog", "sync"])
        self.assertEqual(plist["EnvironmentVariables"]["WORKLOG_HOME"], self.home_dir)
        self.assertEqual(run.calls[-1][:2], ["launchctl", "bootstrap"])
        self.assertEqual(run.calls[-1][-1], path)

    def test_linux_writes_and_enables_a_user_timer(self):
        run = Recorder()
        schedule.install(self.home_dir, 60, platform="linux", user_home=self.user_home, run=run)
        units = os.path.join(self.user_home, ".config", "systemd", "user")
        self.assertTrue(os.path.exists(os.path.join(units, "worklog-sync.service")))
        self.assertTrue(os.path.exists(os.path.join(units, "worklog-sync.timer")))
        self.assertIn(["systemctl", "--user", "enable", "--now", "worklog-sync.timer"], run.calls)

    def test_linux_without_user_systemd_falls_back_to_cron(self):
        run = Recorder(failing=["systemctl"], stdout={"crontab -l": "5 4 * * * backup\n0 * * * * stale-entry # worklog-sync\n"})
        schedule.install(self.home_dir, 60, platform="linux", user_home=self.user_home, run=run)
        self.assertEqual(run.calls[-1], ["crontab", "-"])
        written = run.inputs[-1]
        self.assertIn("5 4 * * * backup\n", written)
        self.assertNotIn("stale-entry", written)
        self.assertEqual(written.count("# worklog-sync"), 1)

    def test_uninstall_removes_the_macos_agent(self):
        schedule.install(self.home_dir, 60, platform="darwin", user_home=self.user_home, run=Recorder())
        run = Recorder()
        schedule.uninstall(platform="darwin", user_home=self.user_home, run=run)
        self.assertFalse(os.path.exists(os.path.join(self.user_home, "Library", "LaunchAgents", "com.worklog.sync.plist")))
        self.assertEqual(run.calls[0][:2], ["launchctl", "bootout"])

    def test_uninstall_removes_linux_units_and_cron_line(self):
        schedule.install(self.home_dir, 60, platform="linux", user_home=self.user_home, run=Recorder())
        run = Recorder(stdout={"crontab -l": "5 4 * * * backup\n0 * * * * x # worklog-sync\n"})
        schedule.uninstall(platform="linux", user_home=self.user_home, run=run)
        self.assertFalse(os.path.exists(os.path.join(self.user_home, ".config", "systemd", "user", "worklog-sync.timer")))
        self.assertEqual(run.inputs[-1], "5 4 * * * backup\n")

    def test_status_on_macos(self):
        ok = Recorder(stdout={"launchctl print": "state = waiting\n\tlast exit code = 0\n"})
        bad = Recorder(stdout={"launchctl print": "last exit code = 1\n"})
        never = Recorder(stdout={"launchctl print": "last exit code = (never exited)\n"})
        missing = Recorder(failing=["launchctl print"])
        self.assertTrue(schedule.status(platform="darwin", user_home=self.user_home, run=ok)[0])
        self.assertTrue(schedule.status(platform="darwin", user_home=self.user_home, run=never)[0])
        self.assertFalse(schedule.status(platform="darwin", user_home=self.user_home, run=bad)[0])
        self.assertFalse(schedule.status(platform="darwin", user_home=self.user_home, run=missing)[0])

    def test_status_on_linux(self):
        ok = Recorder(stdout={"show": "ExecMainStatus=0\n"})
        bad = Recorder(stdout={"show": "ExecMainStatus=1\n"})
        cron = Recorder(failing=["systemctl"], stdout={"crontab -l": "0 * * * * x # worklog-sync\n"})
        nothing = Recorder(failing=["systemctl"])
        self.assertTrue(schedule.status(platform="linux", user_home=self.user_home, run=ok)[0])
        self.assertFalse(schedule.status(platform="linux", user_home=self.user_home, run=bad)[0])
        self.assertTrue(schedule.status(platform="linux", user_home=self.user_home, run=cron)[0])
        self.assertFalse(schedule.status(platform="linux", user_home=self.user_home, run=nothing)[0])
