"""The systemd user timers.

On the main machine, two: the weekly recap, at [recap] when (Fridays at
15:15 by default), and the retry of machines not reached, hourly at :45 for
two more days. On a viewer, one: the notification, hourly at :50 from that
day for two more. The minutes keep clear of Fleet doctor's runs (on the hour
and every 5 minutes from :02), so the two never ssh into the same machine at
once; the config refuses a recap time on one of them.

The schedule is written into the units when they are installed. drift says
when the installed ones are no longer what the config would install, so a
changed [recap] does not go unnoticed: timers status, and every recap the
command shows, the panel's included, say what to run.

The main machine runs other scripts and bots, so its services run at the
lowest priority there is (Nice=19, idle CPU and IO scheduling), with a memory
limit and a time limit. Without lingering, user timers stop when the user
logs out; install says so and prints the command, and never turns it on
itself.

Every unit starts with MARK, so remove takes away only what install wrote.
"""

import datetime
import json
import os
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from fleetlog import COMMAND, config
from fleetlog.config import DAYS, WHEN, Config

MARK = "# Written by fleetlog timers install; fleetlog timers remove removes it."
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
WHAT = {"fleetlog-weekly": "the weekly recap",
        "fleetlog-retry": "the retry of machines not reached",
        "fleetlog-notify": "the weekly notification"}
# In the state folder: when the main machine builds the recap, as the last
# recap fetched from it said.
MAIN_WHEN = "main-when"
MAIN = ("fleetlog-weekly", "fleetlog-retry")
VIEWER = ("fleetlog-notify",)
ROLES = {"main": MAIN, "viewer": VIEWER}


def timers(role: str, when: tuple[int, int, int]) -> tuple[Timer, ...]:
    """The timers for that role, for the recap at when (weekday, hour, minute).
    Retries and the notification run hourly from then for two more days."""
    day, hour, minute = when
    if role == "main":
        retry = ([f"OnCalendar={DAYS[day]} *-*-* {hour + 1}..23:45:00"] if hour < 23 else [])
        retry.append(f"OnCalendar={_days(day + 1, day + 2)} *-*-* *:45:00")
        return (
            Timer("fleetlog-weekly", WHAT["fleetlog-weekly"], ("weekly",),
                  (f"OnCalendar={DAYS[day]} *-*-* {hour:02}:{minute:02}:00",
                   "Persistent=true"), QUIET),
            Timer("fleetlog-retry", WHAT["fleetlog-retry"], ("weekly", "--retry"),
                  tuple(retry), QUIET),
        )
    # No time limit: a notification that stays is up until it is clicked or
    # dismissed, and notify-send --wait has to be there to open the recap when
    # it is clicked. While it waits, the hourly timer starts nothing.
    return (
        Timer("fleetlog-notify", WHAT["fleetlog-notify"], ("notify",),
              (f"OnCalendar={_days(day, day + 2, span=True)} *-*-* *:50:00",),
              ("Nice=10", "TimeoutStartSec=infinity")),
    )


def _days(first: int, last: int, span: bool = False) -> str:
    """Weekdays first to last, as systemd writes them: a range only when it
    does not go past Sunday, which systemd ranges cannot."""
    if span and last <= 6:
        return f"{DAYS[first]}..{DAYS[last]}"
    return ",".join(DAYS[d % 7] for d in range(first, last + 1))


def last_weekly(now: float, when: tuple[int, int, int] = WHEN) -> int:
    """When the weekly recap was last due by now: the latest day and time
    when names."""
    day, hour, minute = when
    t = datetime.datetime.fromtimestamp(now)
    due = t.replace(hour=hour, minute=minute, second=0, microsecond=0)
    due -= datetime.timedelta(days=(t.weekday() - day) % 7)
    if due > t:
        due -= datetime.timedelta(days=7)
    return int(due.timestamp())


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
            MARK, "[Unit]", f"Description=fleetlog: {t.what}", "",
            "[Service]", "Type=oneshot",
            "ExecStart=" + " ".join(_word(w) for w in (*cmd, *t.args)),
            *t.service,
            "# 1 means a machine was not reached: a result, not a failure.",
            "SuccessExitStatus=1", "",
        ])
        out[f"{t.name}.timer"] = "\n".join([
            MARK, "[Unit]", f"Description=fleetlog: {t.what}", "",
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


def install(role: str, cfg: Config) -> int:
    if cfg.when is None:
        raise TimersError('the weekly recap is off in the config ([recap] when = "off"); '
                          "nothing was installed")
    here = cfg.here
    if role == "viewer" and not cfg.notifies(here):
        raise TimersError(f"{here} is not in [recap] notify, so it would show nothing; "
                          "nothing was installed")
    which = timers(role, cfg.when)
    texts = units(which)
    where = unit_dir()
    for name in texts:
        path = where / name
        if (path.exists() or path.is_symlink()) and not ours(path):
            raise TimersError(f"{path} is there and fleetlog did not write it; "
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


def installed() -> list[str]:
    """The unit files install wrote that are there now."""
    where = unit_dir()
    names = [n for t in (*MAIN, *VIEWER) for n in (f"{t}.service", f"{t}.timer")]
    return [n for n in names if ours(where / n)]


def remove() -> int:
    where = unit_dir()
    mine = installed()
    if timers := [n for n in mine if n.endswith(".timer")]:
        _systemctl("disable", "--now", *timers)
    for name in mine:
        (where / name).unlink()
        print(f"removed {where / name}")
    if mine:
        _systemctl("daemon-reload")
    else:
        print("no fleetlog timers installed; nothing removed")
    return 0


def status(cfg: Config | None) -> int:
    """The installed timers, then what drift says, unless the config does
    not read (cfg is None)."""
    where = unit_dir()
    found = False
    for name in (*MAIN, *VIEWER):
        if not ours(where / f"{name}.timer"):
            continue
        found = True
        out = _systemctl("show", "--property=ActiveState,NextElapseUSecRealtime",
                         f"{name}.timer")
        state = dict(line.partition("=")[::2] for line in out.splitlines())
        print(f"{name}.timer ({WHAT[name]}): {state.get('ActiveState') or 'unknown'}, "
              f"next {state.get('NextElapseUSecRealtime') or 'not scheduled'}")
    if not found:
        print("no fleetlog timers installed")
    notes = drift(cfg) if cfg is not None else []
    for note in notes:
        print(f"note: {note}")
    return 0 if found and not notes else 1


def drift(cfg: Config) -> list[str]:
    """Where this machine's timers are not what [recap] says, each with what
    to run. Only the timer files count: they hold the schedule, while the
    services hold the Python that ran install, which may differ from this one."""
    where = unit_dir()
    have = {role: [n for n in names if ours(where / f"{n}.timer")]
            for role, names in ROLES.items()}
    here = cfg.here
    if cfg.when is None:
        if have["main"] or have["viewer"]:
            return ['the weekly recap is off ([recap] when = "off"), but its timers are '
                    "still here: `fleetlog timers remove` removes them"]
        return []
    out = []
    for role, names in ROLES.items():
        if not have[role]:
            continue
        if role == "viewer" and not cfg.notifies(here):
            out.append(f"{here} is not in [recap] notify, so its notification timer shows "
                       "nothing" + ("" if have["main"] else
                                    ": `fleetlog timers remove` removes it"))
            continue
        want = units(timers(role, cfg.when))
        if any(_text(where / f"{n}.timer") != want[f"{n}.timer"] for n in names):
            out.append(f"the {'weekly' if role == 'main' else 'notification'} timers here "
                       f"are not as [recap] says: run `fleetlog timers install {role}`")
    if have["viewer"] and cfg.notifies(here):
        theirs = main_when()
        if theirs is not None and theirs != cfg.when:
            out.append(schedule_note(cfg, theirs))
    if not have["viewer"] and cfg.notify is not None and here in cfg.notify:
        out.append(f"{here} is in [recap] notify but has no notification timer: run "
                   "`fleetlog timers install viewer`")
    return out


def main_when() -> tuple[int, int, int] | None:
    """When the main machine builds the recap, as its last recap fetched here
    said, or None before one did."""
    try:
        text = (config.state_dir() / MAIN_WHEN).read_text()
        return config.stored_when(json.loads(text))
    except (OSError, ValueError):
        return None


def schedule_note(cfg: Config, theirs: tuple[int, int, int]) -> str:
    main = cfg.main or "the main machine"
    mine = config.when_text(cfg.when) if cfg.when else "off"
    return (f"{main} builds the recap {config.when_text(theirs)}, but [recap] when here is "
            f"{mine}: set it the same here, then run `fleetlog timers install viewer`")


def _text(path: Path) -> str | None:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
