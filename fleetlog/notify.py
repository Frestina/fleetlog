"""The weekly notification on a viewer.

The viewer's timer runs notify every hour from Friday afternoon to Sunday.
It fetches the latest recap from the main machine and, the first time a
recap from the last 3 days is there and has not been shown here, raises one
notification. Clicking it opens the full recap in a terminal, from a copy
written here, so opening it needs no second ssh call.

It is raised as critical, so it stays on screen until it is clicked or
dismissed: the author is often away from the machine when it comes. Omarchy's
shell keeps any other notification for 30 seconds at most. Critical does not
get past Do Not Disturb there, which it only allows for plain notify-send.

A recap counts as shown once notify-send has put it up, not when it is
clicked: notify-send --wait only returns when the notification closes, so a
notify-send still running after a few seconds means it is up. One that exits
at once with an error (no notification daemon, a locked session) leaves the
recap unshown, and the next hour tries again.

When the main machine cannot be reached, it says so once a day, and keeps
trying every hour. It never collects on its own instead.
"""

import datetime
import html
import shutil
import subprocess
import sys
import time

from fleetlog import recap, weekly
from fleetlog.config import Config

APP = "git-fleetlog"
SHOW_FOR = 3 * 24 * 3600  # after the window ends
SHOWN = "shown"
SAID = "unreachable-said"
COPY = "recap.md"
UP = 5  # seconds after which a running notify-send means the notification is up
LINES = 4  # projects the notification names


def run(cfg: Config) -> int:
    try:
        data = weekly.fetch(cfg)
    except weekly.Unreachable as e:
        return _say_unreachable(str(e))
    except weekly.NoRecap as e:
        print(e, file=sys.stderr)
        return 0 if "has been built" in str(e) else 1
    weekly.state_file(SAID).unlink(missing_ok=True)

    if time.time() - data["until"] > SHOW_FOR:
        print("no recap from the last few days to show")
        return 0
    wid = weekly.window_id(data)
    if _read(SHOWN) == wid:
        print("this week's recap was shown here already")
        return 0

    projects = recap.build(data["facts"], cfg.identities, data["since"], data["until"],
                           cfg.exclude)
    copy = weekly.state_file(COPY)
    copy.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    copy.write_text(recap.markdown(data["facts"], projects, data["since"], data["until"]))
    summary, body = text(data, projects)

    # "default" is the action a click on the notification itself invokes;
    # Omarchy's shell invokes no other on a click.
    argv = ["notify-send", f"--app-name={APP}", "--urgency=critical",
            "--action=default=Open the recap", "--wait", "--", summary,
            html.escape(body, quote=False)]
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
    except OSError as e:
        print(f"cannot run notify-send: {e.strerror}", file=sys.stderr)
        return 1
    try:
        out, err = proc.communicate(timeout=UP)
    except subprocess.TimeoutExpired:
        _write(SHOWN, wid)
        out, err = proc.communicate()
    else:
        if proc.returncode != 0:
            print(f"notify-send exited {proc.returncode}: {err.strip()}", file=sys.stderr)
            return 1
        _write(SHOWN, wid)
    print(f"shown: {summary}")
    if out.strip() == "default":
        return open_terminal(str(copy))
    return 0


def text(data: dict, projects: list[recap.Project]) -> tuple[str, str]:
    worked = sorted((p for p in projects if p.commits), key=lambda p: p.latest, reverse=True)
    commits = sum(len(p.commits) for p in worked)
    summary = (f"Your week: {commits} commit{'s' if commits != 1 else ''} in "
               f"{len(worked)} project{'s' if len(worked) != 1 else ''}")
    lines = [f"{p.name}: {len(p.commits)}" + (", work left" if p.left else "")
             for p in worked[:LINES]]
    if len(worked) > LINES:
        lines.append(f"and {len(worked) - LINES} more")
    missed = [f["label"] for f in data["facts"] if not f.get("reached")]
    if missed:
        lines.append(f"Not reached: {', '.join(missed)}")
    return summary, "\n".join(lines) or "Nothing committed this week."


def open_terminal(path: str) -> int:
    """less on the copy, in a terminal of its own. Through systemd-run, so
    the terminal is not part of the timer's service and outlives it."""
    argv = ["xdg-terminal-exec", "less", "--", path]
    if shutil.which("systemd-run"):
        argv = ["systemd-run", "--user", "--collect", "--quiet", "--", *argv]
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"cannot open a terminal: {e}", file=sys.stderr)
        return 1
    if done.returncode != 0:
        print(f"cannot open a terminal: {done.stderr.strip()}", file=sys.stderr)
        return 1
    return 0


def _say_unreachable(why: str) -> int:
    today = datetime.date.today().isoformat()
    if _read(SAID) != today:
        try:
            done = subprocess.run(
                ["notify-send", f"--app-name={APP}", "--urgency=critical", "--",
                 "git-fleetlog: no weekly recap",
                 html.escape(f"{why}. Trying again every hour.", quote=False)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"cannot run notify-send: {e}", file=sys.stderr)
        else:
            if done.returncode == 0:
                _write(SAID, today)
    print(why, file=sys.stderr)
    return 1


def _read(name: str) -> str | None:
    try:
        return weekly.state_file(name).read_text().strip()
    except OSError:
        return None


def _write(name: str, value: str) -> None:
    path = weekly.state_file(name)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(value + "\n")

