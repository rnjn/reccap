import os
import plistlib
import re
import shlex
import subprocess
import sys

LABEL = "com.reccap.sync"
UNIT = "reccap-sync"
CRON_MARK = "# reccap-sync"


def command():
    return [sys.executable, "-m", "reccap", "sync"]


def environment(home_dir):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return {"PYTHONPATH": root, "RECCAP_HOME": home_dir}


def launchd_plist(args, env, interval_seconds, log_path):
    plist = {
        "Label": LABEL,
        "ProgramArguments": list(args),
        "EnvironmentVariables": dict(env),
        "StartInterval": interval_seconds,
        "RunAtLoad": True,
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
    }
    return plistlib.dumps(plist).decode()


def systemd_service(args, env):
    lines = ["[Unit]", "Description=Reccap sync", "", "[Service]", "Type=oneshot"]
    lines += [f'Environment="{key}={value}"' for key, value in env.items()]
    lines += ["ExecStart=" + " ".join(shlex.quote(a) for a in args), ""]
    return "\n".join(lines)


def systemd_timer(minutes):
    calendar = "hourly" if minutes == 60 else f"*:0/{minutes}"
    lines = ["[Unit]", "Description=Reccap sync timer", "", "[Timer]", f"OnCalendar={calendar}", "Persistent=true", ""]
    lines += ["[Install]", "WantedBy=timers.target", ""]
    return "\n".join(lines)


def cron_line(args, env, minutes):
    when = "0 * * * *" if minutes >= 60 else f"*/{minutes} * * * *"
    assignments = [f"{key}={shlex.quote(value)}" for key, value in env.items()]
    return " ".join([when, *assignments, *(shlex.quote(a) for a in args), CRON_MARK])


def install(home_dir, minutes, platform=sys.platform, user_home=None, run=subprocess.run):
    user_home = user_home or os.path.expanduser("~")
    args, env = command(), environment(home_dir)
    if platform == "darwin":
        path = _plist_path(user_home)
        _write(path, launchd_plist(args, env, minutes * 60, os.path.join(home_dir, "launchd.log")))
        _run(run, ["launchctl", "bootout", f"{_domain()}/{LABEL}"])
        result = _run(run, ["launchctl", "bootstrap", _domain(), path])
        if result.returncode:
            raise RuntimeError("launchctl bootstrap failed: " + (result.stderr or "").strip())
        return "launchd user agent " + path
    if _run(run, ["systemctl", "--user", "show-environment"]).returncode == 0:
        units = _units_dir(user_home)
        _write(os.path.join(units, UNIT + ".service"), systemd_service(args, env))
        _write(os.path.join(units, UNIT + ".timer"), systemd_timer(minutes))
        _run(run, ["systemctl", "--user", "daemon-reload"])
        result = _run(run, ["systemctl", "--user", "enable", "--now", UNIT + ".timer"])
        if result.returncode:
            raise RuntimeError("systemctl enable failed: " + (result.stderr or "").strip())
        return "systemd user timer " + UNIT + ".timer"
    _set_crontab(run, [*_other_cron_lines(run), cron_line(args, env, minutes)])
    return "crontab entry"


def uninstall(platform=sys.platform, user_home=None, run=subprocess.run):
    user_home = user_home or os.path.expanduser("~")
    if platform == "darwin":
        _run(run, ["launchctl", "bootout", f"{_domain()}/{LABEL}"])
        _remove(_plist_path(user_home))
        return
    _run(run, ["systemctl", "--user", "disable", "--now", UNIT + ".timer"])
    for suffix in (".service", ".timer"):
        _remove(os.path.join(_units_dir(user_home), UNIT + suffix))
    _run(run, ["systemctl", "--user", "daemon-reload"])
    current = _run(run, ["crontab", "-l"]).stdout or ""
    if CRON_MARK in current:
        _set_crontab(run, _other_cron_lines(run))


def status(platform=sys.platform, user_home=None, run=subprocess.run):
    if platform == "darwin":
        result = _run(run, ["launchctl", "print", f"{_domain()}/{LABEL}"])
        if result.returncode:
            return False, "launchd agent is not loaded"
        match = re.search(r"last exit code = (.+)", result.stdout or "")
        code = match.group(1).strip() if match else "unknown"
        return code in ("0", "(never exited)"), f"last exit code {code}"
    if _run(run, ["systemctl", "--user", "is-enabled", UNIT + ".timer"]).returncode == 0:
        shown = _run(run, ["systemctl", "--user", "show", UNIT + ".service", "-p", "ExecMainStatus"]).stdout or ""
        code = shown.strip().partition("=")[2] or "unknown"
        return code == "0", f"last exit code {code}"
    if CRON_MARK in (_run(run, ["crontab", "-l"]).stdout or ""):
        return True, "crontab entry present"
    return False, "no schedule installed"


def _run(run, args, text=None):
    try:
        return run(args, check=False, capture_output=True, text=True, input=text)
    except OSError as error:
        return subprocess.CompletedProcess(args, 127, "", str(error))


def _other_cron_lines(run):
    current = _run(run, ["crontab", "-l"]).stdout or ""
    return [line for line in current.splitlines() if CRON_MARK not in line]


def _set_crontab(run, lines):
    _run(run, ["crontab", "-"], text="".join(line + "\n" for line in lines))


def _domain():
    return f"gui/{os.getuid()}"


def _plist_path(user_home):
    return os.path.join(user_home, "Library", "LaunchAgents", LABEL + ".plist")


def _units_dir(user_home):
    return os.path.join(user_home, ".config", "systemd", "user")


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
