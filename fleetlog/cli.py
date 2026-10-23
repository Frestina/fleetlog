"""The git-fleetlog command.

    git fleetlog [--since <when>] [--json]   the recap, read from every machine now
    git fleetlog status [--json]             only where each project was left
    git fleetlog latest [--json]             the last weekly recap, from the main machine
    git fleetlog weekly [--retry]            build the weekly recap (its timer runs this)
    git fleetlog notify                      the weekly notification (its timer runs this)
    git fleetlog timers install main|viewer
    git fleetlog timers remove | status

Exit codes: 0 everything was read, 1 a machine was not reached or not fully
read, 2 an error.
"""

import argparse
import datetime
import re
import sys
import time

from fleetlog import collect, config, notify, recap, timers, weekly

EXIT_OK, EXIT_GAPS, EXIT_ERROR = 0, 1, 2
_AGO = re.compile(r"(\d+)([dw])")


def since(text: str) -> int:
    """A date (2026-10-01, from its midnight) or a time ago (10d, 2w)."""
    m = _AGO.fullmatch(text)
    if m:
        days = int(m.group(1)) * (7 if m.group(2) == "w" else 1)
        return int(time.time()) - days * 24 * 3600
    try:
        return int(datetime.datetime.strptime(text, "%Y-%m-%d").timestamp())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} is neither a date like 2026-10-01 nor a time ago like 10d or 2w"
        ) from None


def parser() -> argparse.ArgumentParser:
    out = argparse.ArgumentParser(
        prog="git-fleetlog",
        description="git log for the whole fleet: your commits from every repo on every "
                    "machine, and where each project was left.")
    out.add_argument("--since", type=since, metavar="WHEN",
                     help="from a date (2026-10-01) or a time ago (10d, 2w); default 7d")
    out.add_argument("--json", action="store_true", help="exact data instead of Markdown")
    sub = out.add_subparsers(dest="cmd", metavar="COMMAND")
    for name, what in (("status", "only where each project was left"),
                       ("latest", "the last weekly recap, from the main machine")):
        p = sub.add_parser(name, help=what, description=what)
        p.add_argument("--json", action="store_true", help="exact data instead of Markdown")
    p = sub.add_parser("weekly", help="build the weekly recap (its timer runs this)")
    p.add_argument("--retry", action="store_true",
                   help="read again only the machines not reached last time")
    sub.add_parser("notify", help="the weekly notification (its timer runs this)")
    p = sub.add_parser("timers", help="install, remove or show the systemd timers")
    tsub = p.add_subparsers(dest="action", metavar="ACTION", required=True)
    i = tsub.add_parser("install", help="install the timers for this machine's role")
    i.add_argument("role", choices=("main", "viewer"))
    tsub.add_parser("remove", help="remove every timer install wrote")
    tsub.add_parser("status", help="show the installed timers")
    return out


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.cmd == "timers":
            if args.action == "install":
                return timers.install(args.role)
            return timers.remove() if args.action == "remove" else timers.status()
        cfg = config.load()
        if args.cmd == "weekly":
            return weekly.retry(cfg) if args.retry else weekly.weekly(cfg)
        if args.cmd == "notify":
            return notify.run(cfg)
        if args.cmd == "latest":
            data = weekly.fetch(cfg)
            return show(cfg, data["facts"], data["since"], data["until"], args.json)
        until = int(time.time())
        if args.cmd == "status":
            facts = collect.collect_all(cfg, until, until)
            return show(cfg, facts, until, until, args.json, status=True)
        start = args.since if args.since is not None else until - weekly.WEEK
        return show(cfg, collect.collect_all(cfg, start, until), start, until, args.json)
    except (config.ConfigError, weekly.NoRecap, weekly.Busy, timers.TimersError) as e:
        print(f"git-fleetlog: {e}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return 130


def show(cfg: config.Config, facts: list[dict], start: int, until: int, as_json: bool,
         status: bool = False) -> int:
    try:
        projects = recap.build(facts, cfg.identities, start, until, cfg.exclude)
        text = (recap.as_json if as_json else recap.markdown)(
            facts, projects, start, until, status)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        print(f"git-fleetlog: the facts do not read ({type(e).__name__}: {e})", file=sys.stderr)
        return EXIT_ERROR
    sys.stdout.write(text)
    if not cfg.identities and not as_json:
        print("note: no identities found in your git config, so no commit counts as yours",
              file=sys.stderr)
    return EXIT_OK if recap.all_read(facts) else EXIT_GAPS
