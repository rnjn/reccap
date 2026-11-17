import argparse
import sys
from datetime import datetime

from reccap import config, schedule
from reccap.day import run_day
from reccap.doctor import run_doctor
from reccap.install import run_install
from reccap.sync import run_sync


def date_arg(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from None
    return value


def build_parser():
    parser = argparse.ArgumentParser(prog="reccap", description="Claude Code daily activity log")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="render and push changed sessions")
    sync.add_argument("--dry-run", action="store_true", help="print what would be written and change nothing")
    sync.add_argument("--no-push", action="store_true", help="commit without pushing")
    sync.add_argument("--since", type=date_arg, metavar="YYYY-MM-DD", help="reprocess transcripts modified on or after this date")
    day = commands.add_parser("day", help="build the day page")
    day.add_argument("date", nargs="?", type=date_arg, metavar="DATE", help="YYYY-MM-DD, defaults to yesterday")
    day.add_argument("--no-pull", action="store_true", help="do not pull the vault first")
    day.add_argument("--no-push", action="store_true", help="do not push the page")
    day.add_argument("--no-sync", action="store_true", help="do not sync this machine's sessions first")
    day.add_argument("--open", action="store_true", help="open the page in Obsidian")
    install = commands.add_parser("install", help="set up this machine and schedule sync")
    install.add_argument("--vault", required=True, help="path to the vault, a git repo")
    install.add_argument("--repo-url", help="clone the vault from this URL when the path does not exist")
    install.add_argument("--machine", help="unique name for this machine, defaults to the short hostname")
    install.add_argument("--force", action="store_true", help="proceed even if the machine name is already in the vault")
    commands.add_parser("doctor", help="check the setup")
    commands.add_parser("uninstall", help="remove the schedule, keeping the vault and local state")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    home_dir = config.home()
    if args.command == "sync":
        return run_sync(home_dir, dry_run=args.dry_run, no_push=args.no_push, since=args.since)
    if args.command == "day":
        return run_day(home_dir, args.date, no_pull=args.no_pull, no_push=args.no_push, no_sync=args.no_sync, open_page=args.open)
    if args.command == "install":
        return run_install(home_dir, args.vault, repo_url=args.repo_url, machine=args.machine, force=args.force)
    if args.command == "doctor":
        return run_doctor(home_dir)
    if args.command == "uninstall":
        schedule.uninstall()
        print("schedule removed")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
