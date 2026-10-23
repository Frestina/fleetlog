"""The systemd user timers.

On the main machine, two: the weekly recap, Fridays at 15:15, and the retry
of machines not reached, hourly at :45 until Sunday night. On a viewer, one:
the notification, hourly at :50 from Friday to Sunday. The minutes keep clear
of Fleet doctor's runs (on the hour and every 5 minutes from :02), so the
two never ssh into the same machine at once.

The main machine runs other scripts and bots, so its services run at the
lowest priority there is (Nice=19, idle CPU and IO scheduling), with a memory
limit and a time limit. Without lingering, user timers stop when the user
logs out; install says so and prints the command, and never turns it on
itself.

Every unit starts with MARK, so remove takes away only what install wrote.
"""

import os
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from fleetlog import config

MARK = "# Written by git-fleetlog timers install; git-fleetlog timers remove removes it."
COMMAND = Path(__file__).resolve().parent.parent / "bin" / "git-fleetlog"
TIMEOUT = 30
_PLAIN = frozenset(string.ascii_letters + string.digits + "/._-+,:@=~")


class TimersError(Exception):
    """The timers could not be installed, removed or read; says why."""


@dataclass(frozen=True)
class Timer:
    name: str
    what: str
    args: tuple[str, ...]
    schedule: tuple[str, ...]
    service: tuple[str, ...]


QUIET = ("Nice=19", "CPUSchedulingPolicy=idle", "IOSchedulingClass=idle", "MemoryMax=300M",
         "TimeoutStartSec=15min")
MAIN = (
    Timer("git-fleetlog-weekly", "the weekly recap", ("weekly",),
          ("OnCalendar=Fri *-*-* 15:15:00", "Persistent=true"), QUIET),
    Timer("git-fleetlog-retry", "the retry of machines not reached", ("weekly", "--retry"),
          ("OnCalendar=Fri *-*-* 16..23:45:00", "OnCalendar=Sat,Sun *-*-* *:45:00"), QUIET),
)
# No time limit: the notification stays until it is clicked or dismissed, and
# notify-send --wait has to be there to open the recap when it is clicked.
# While it waits, the hourly timer finds the service running and starts nothing.
VIEWER = (
    Timer("git-fleetlog-notify", "the weekly notification", ("notify",),
          ("OnCalendar=Fri..Sun *-*-* *:50:00",), ("Nice=10", "TimeoutStartSec=infinity")),
)
ALL = MAIN + VIEWER


def unit_dir() -> Path:
    return config.config_home() / "systemd" / "user"


def _word(w: str) -> str:
    odd = sorted(set(w) - _PLAIN)
    if not w or odd:
        raise TimersError(f"cannot write {w!r} into a unit file: systemd would read "
                          f"{''.join(odd) or 'an empty word'} differently")
    return w


def units(which: tuple[Timer, ...]) -> dict[str, str]:
    cmd = [os.path.abspath(sys.executable), str(COMMAND)]
    out = {}
    for t in which:
        out[f"{t.name}.service"] = "\n".join([
            MARK, "[Unit]", f"Description=git-fleetlog: {t.what}", "",
            "[Service]", "Type=oneshot",
            "ExecStart=" + " ".join(_word(w) for w in (*cmd, *t.args)),
            *t.service,
            "# 1 means a machine was not reached: a result, not a failure.",
            "SuccessExitStatus=1", "",
        ])
        out[f"{t.name}.timer"] = "\n".join([
            MARK, "[Unit]", f"Description=git-fleetlog: {t.what}", "",
            "[Timer]", *t.schedule, "",
            "[Install]", "WantedBy=timers.target", "",
        ])
    return out


def ours(path: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        with open(path) as f:
            return f.readline().rstrip("\n") == MARK
    except (OSError, UnicodeDecodeError):
        return False


def _run(*argv: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=TIMEOUT)
    except OSError as e:
        raise TimersError(f"cannot run {argv[0]}: {e.strerror}") from None
    except subprocess.TimeoutExpired:
        raise TimersError(f"{' '.join(argv)} gave no answer in {TIMEOUT}s") from None


def _systemctl(*args: str) -> str:
    done = _run("systemctl", "--user", *args)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        raise TimersError(f"systemctl --user {' '.join(args)}: "
                          f"{lines[-1] if lines else f'exit {done.returncode}'}")
    return done.stdout


def linger() -> bool | None:
    try:
        done = _run("loginctl", "show-user", str(os.getuid()), "--property=Linger", "--value")
    except TimersError:
        return None
    answer = done.stdout.strip()
    return {"yes": True, "no": False}.get(answer) if done.returncode == 0 else None


def install(role: str) -> int:
    which = MAIN if role == "main" else VIEWER
    texts = units(which)
    where = unit_dir()
    for name in texts:
        path = where / name
        if (path.exists() or path.is_symlink()) and not ours(path):
            raise TimersError(f"{path} is there and git-fleetlog did not write it; "
                              "nothing was installed")
    where.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        tmp = where / f".{name}.tmp"
        tmp.write_text(text)
        os.replace(tmp, where / name)
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", *(f"{t.name}.timer" for t in which))
    for t in which:
        print(f"installed {t.name}.timer: {t.what} ({'; '.join(t.schedule)})")
    if role == "main":
        on = linger()
        if on is False:
            print("lingering is off, so these timers stop when you log out. "
                  "Turn it on with: loginctl enable-linger")
        elif on is None:
            print("cannot tell whether lingering is on; without it these timers stop "
                  "when you log out")
    return 0


def remove() -> int:
    where = unit_dir()
    names = [n for t in ALL for n in (f"{t.name}.service", f"{t.name}.timer")]
    mine = [n for n in names if ours(where / n)]
    if timers := [n for n in mine if n.endswith(".timer")]:
        _systemctl("disable", "--now", *timers)
    for name in mine:
        (where / name).unlink()
        print(f"removed {where / name}")
    if mine:
        _systemctl("daemon-reload")
    else:
        print("no git-fleetlog timers installed; nothing removed")
    return 0


def status() -> int:
    where = unit_dir()
    found = False
    for t in ALL:
        if not ours(where / f"{t.name}.timer"):
            continue
        found = True
        out = _systemctl("show", "--property=ActiveState,NextElapseUSecRealtime",
                         f"{t.name}.timer")
        state = dict(line.partition("=")[::2] for line in out.splitlines())
        print(f"{t.name}.timer ({t.what}): {state.get('ActiveState') or 'unknown'}, "
              f"next {state.get('NextElapseUSecRealtime') or 'not scheduled'}")
    if not found:
        print("no git-fleetlog timers installed")
        return 1
    return 0
