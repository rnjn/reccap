import argparse
import sys
from datetime import datetime

from worklog import config
from worklog.day import run_day
from worklog.sync import run_sync


def date_arg(value):
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from None
    return value


def build_parser():
    parser = argparse.ArgumentParser(prog="worklog", description="Claude Code daily activity log")
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
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    home_dir = config.home()
    if args.command == "sync":
        return run_sync(home_dir, dry_run=args.dry_run, no_push=args.no_push, since=args.since)
    if args.command == "day":
        return run_day(home_dir, args.date, no_pull=args.no_pull, no_push=args.no_push, no_sync=args.no_sync, open_page=args.open)
    return 2


if __name__ == "__main__":
    sys.exit(main())
