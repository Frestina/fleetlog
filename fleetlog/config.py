"""Where fleetlog's machines, folders and identities come from.

Machines come from ~/.config/fleet/hosts, the list every Fleet tool shares
(https://github.com/Frestina/fleet/blob/main/HOSTS.md), then from [machines]
in fleetlog's own config, for machines only it reads. skip there leaves
listed machines out, by label. `fleetlog machines` opens the hosts file,
written first with this machine in it when there is none.

A line of the hosts file is <label> <ssh target> [<hostname>], and the line
whose hostname is this machine's (in full, or up to the first dot), or whose
target is "local", is this machine; in [machines], the one whose target is
"local". When none is, this machine is added under its hostname. With no
hosts file, the fleet is this machine and those in [machines].

The author's commits are the ones whose author email is in an [identity
"<name>"] section of the global git config (git-whoami's), in user.email, or
in [identity] emails here. The identity's name is the account the recap shows.

The config, ~/.config/fleet/log/config.toml, is optional TOML:

    [main]
    machine = "homeserver"

    [recap]
    when = "Fri 15:15"
    notify = ["laptop"]
    stays = true

    [folders]
    all = ["~/Projects", "~/dotfiles"]
    homeserver = ["~/srv"]

    [machines]
    nas = "nas"
    skip = ["pi"]

    [exclude]
    projects = ["scratch"]
    repos = ["~/Projects/scratch"]

    [identity]
    emails = ["me@example.org"]

`fleetlog config` writes TEMPLATE there when there is none, and opens it.
"""

import os
import shlex
import shutil
import socket
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FOLDERS = ("~/Projects", "~/dotfiles")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WHEN = (4, 15, 15)  # the weekly recap's default: Friday 15:15, as weekday, hour, minute
# Fleet doctor's runs, on the hour and every 5 minutes from :02, ssh into the
# machines too: the weekly run keeps off them.
DOCTOR = frozenset({0, *range(2, 60, 5)})

TEMPLATE = """\
# Settings for fleetlog. Every one is optional: remove the # in front of
# a setting to turn it on. Text goes in double quotes, lists in brackets. The
# panel reads every machine again when you save.

[exclude]
# Projects to leave out, by the name the recap and the panel show.
# projects = ["scratch", "old-experiment"]
# Or by folder, on every machine: that repo, and every repo under it.
# repos = ["~/Projects/scratch"]

[folders]
# Where repos are looked for, 4 levels deep. "all" is every machine and
# replaces the default, ["~/Projects", "~/dotfiles"]. A line for one machine,
# by its label, adds folders there. A folder can be a single repo.
# all = ["~/Projects", "~/dotfiles"]
# homeserver = ["~/srv", "~/notes"]

[main]
# The machine that builds the weekly recap and keeps the latest one.
# machine = "homeserver"

[recap]
# When the weekly recap of the 7 days before is built, a day and a time, or
# "off" for none. Not on the hour or at :02, :07, :12 and so on, when Fleet
# doctor reads the machines. After a change, run `fleetlog timers install`
# again on the machines that have its timers.
# when = "Fri 15:15"
# The machines that show it as a notification, by label, or "all": every
# machine where `fleetlog timers install viewer` was run.
# notify = "all"
# true: it stays on screen until it is clicked or dismissed. false: it goes
# away by itself, like other notifications.
# stays = true

[machines]
# Machines are listed in ~/.config/fleet/hosts, which every Fleet tool reads
# (`fleetlog machines`, or Machines in the panel). Here, more that only
# fleetlog reads: <label> = "<ssh target>", or "local" for this machine.
# nas = "nas"
# And the ones in the hosts file it leaves out, by label.
# skip = ["pi"]

[identity]
# Author emails whose commits count as yours, beyond those in your git
# config (user.email and git-whoami's [identity "<name>"] sections).
# emails = ["old-address@example.org"]
"""

# The header every Fleet tool writes into a new hosts file (HOSTS.md).
HOSTS_TEMPLATE = """\
# Your machines, one per line, read by every Fleet tool:
#
#   <label>  <ssh target>  [<hostname>]
#
# The target is whatever you would type after `ssh`. The line whose hostname
# is the machine a tool runs on is read there without ssh, so the same file
# works when copied to your other machines.
# Format: https://github.com/Frestina/fleet/blob/main/HOSTS.md
#
# For example:
#
#   desktop     desktop.lan      desktop
#   homeserver  me@192.0.2.10    homeserver

{short}  {short}  {name}
"""


class ConfigError(Exception):
    """The config or the hosts file does not read; says why."""


@dataclass(frozen=True)
class Machine:
    label: str
    target: str
    local: bool = False


@dataclass(frozen=True)
class Config:
    machines: tuple[Machine, ...]
    main: str | None = None
    folders: dict[str, tuple[str, ...]] = field(default_factory=dict)
    exclude: tuple[str, ...] = ()
    exclude_projects: tuple[str, ...] = ()
    identities: dict[str, str] = field(default_factory=dict)  # email -> account
    when: tuple[int, int, int] | None = WHEN  # None: no weekly recap
    notify: tuple[str, ...] | None = None  # None: every machine with the timer
    stays: bool = True
    here: str = ""  # this machine's label, even when skip leaves it out of machines

    def notifies(self, label: str) -> bool:
        """Whether that machine shows the weekly recap."""
        return self.when is not None and (self.notify is None or label in self.notify)

    def folders_for(self, label: str) -> tuple[str, ...]:
        """The folders searched on that machine: all, then its own."""
        out = list(self.folders.get("all", FOLDERS))
        out += [f for f in self.folders.get(label, ()) if f not in out]
        return tuple(out)

    def machine(self, label: str) -> Machine | None:
        return next((m for m in self.machines if m.label == label), None)

    def main_machine(self) -> Machine | None:
        """The main machine, or None when the config names none."""
        if self.main is None:
            return None
        found = self.machine(self.main)
        if found is None:
            raise ConfigError(f"[main] machine = {self.main}, which is not one of the "
                              f"machines ({', '.join(m.label for m in self.machines)})")
        return found


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def fleet_dir() -> Path:
    """Where the Fleet tools keep the shared hosts file and their folders."""
    return config_home() / "fleet"


def hosts_path() -> Path:
    return fleet_dir() / "hosts"


def config_path() -> Path:
    return fleet_dir() / "log" / "config.toml"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "fleet" / "log"


def load() -> Config:
    path = config_path()
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        data = {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"{path} does not read: {e}") from None

    extra = _section(data, "machines")
    skip = set(_strings(extra, "machines", "skip"))
    machines = _hosts()
    for label, target in extra.items():
        if label == "skip":
            continue
        if not isinstance(target, str):
            raise ConfigError(f'{path}: [machines] {label} must be an ssh target in quotes, '
                              f'like {label} = "{label}"')
        machines.append(Machine(label, target.strip(), local=target.strip() == "local"))
    seen: set[str] = set()
    for m in machines:
        if m.label in seen:
            raise ConfigError(f"the machine {m.label} is listed twice")
        if not m.target or m.target.startswith("-"):
            raise ConfigError(f"the machine {m.label} has no usable ssh target")
        seen.add(m.label)
    if not any(m.local for m in machines):
        machines.insert(0, Machine(_hostname(), "local", local=True))
    labels = {m.label for m in machines}
    here = next(m.label for m in machines if m.local)
    machines = [m for m in machines if m.label not in skip]
    if not machines:
        raise ConfigError(f"{path}: [machines] skip leaves no machine to read")

    folders = _section(data, "folders")
    folders = {label: _strings(folders, "folders", label) for label in folders}
    main = _section(data, "main").get("machine")
    if main is not None and not isinstance(main, str):
        raise ConfigError(f'{path}: [main] machine must be a label in quotes, like '
                          f'machine = "homeserver"')
    exclude = _section(data, "exclude")
    recap = _section(data, "recap")
    return Config(
        machines=tuple(machines),
        main=main.strip() if main else None,
        folders=folders,
        exclude=_strings(exclude, "exclude", "repos"),
        exclude_projects=_strings(exclude, "exclude", "projects"),
        identities=identities(list(_strings(_section(data, "identity"), "identity", "emails"))),
        when=_when(recap.get("when", "Fri 15:15")),
        notify=_notify(recap.get("notify", "all"), labels),
        stays=_stays(recap.get("stays", True)),
        here=here,
    )


def _when(value: object) -> tuple[int, int, int] | None:
    usage = f'{config_path()}: [recap] when must be a day and a time, like when = "Fri 15:15"'
    if value == "off":
        return None
    words = value.split() if isinstance(value, str) else []
    if len(words) != 2:
        raise ConfigError(f'{usage}, or "off"')
    day = next((i for i, d in enumerate(DAYS) if words[0].lower() in
                (d.lower(), DAY_NAMES[i])), None)
    hour, _, minute = words[1].partition(":")
    if (day is None or not hour.isdigit() or not minute.isdigit() or len(minute) != 2
            or int(hour) > 23 or int(minute) > 59):
        raise ConfigError(f'{usage}, on a 24-hour clock, or "off"')
    hour, minute = int(hour), int(minute)
    if minute in DOCTOR:
        at = hour * 60 + minute
        before = next((at - k) % 1440 for k in range(1, 60) if (at - k) % 60 not in DOCTOR)
        after = next((at + k) % 1440 for k in range(1, 60) if (at + k) % 60 not in DOCTOR)
        raise ConfigError(f'{config_path()}: [recap] when = "{value}" is when Fleet doctor '
                          f"reads the machines (on the hour and every 5 minutes from :02); "
                          f"take {before // 60:02}:{before % 60:02} or "
                          f"{after // 60:02}:{after % 60:02}")
    return day, hour, minute


def _notify(value: object, labels: set[str]) -> tuple[str, ...] | None:
    if value == "all":
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f'{config_path()}: [recap] notify must be "all" or a list of '
                          f'machines in brackets, like notify = ["laptop"]')
    if unknown := [v for v in value if v not in labels]:
        raise ConfigError(f"{config_path()}: [recap] notify names {', '.join(unknown)}, "
                          f"which {'is' if len(unknown) == 1 else 'are'} not one of the "
                          f"machines ({', '.join(sorted(labels))})")
    return tuple(value)


def _stays(value: object) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{config_path()}: [recap] stays must be true or false, "
                          f"without quotes")
    return value


def ensure() -> Path:
    """The config, written from TEMPLATE first when there is none."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x") as f:
            f.write(TEMPLATE)
    except FileExistsError:
        pass
    return path


def ensure_hosts() -> Path:
    """The shared hosts file, written first with this machine in it when there
    is none. One that is there, or a link to one, is never replaced."""
    path = hosts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    name = socket.gethostname()
    try:
        with open(path, "x") as f:
            f.write(HOSTS_TEMPLATE.format(short=name.split(".")[0], name=name))
    except FileExistsError:
        pass
    return path


def editor_command(path: Path, inline: bool) -> list[str]:
    """Omarchy's default editor, in this terminal when there is one."""
    if shutil.which("omarchy-launch-editor"):
        return ["omarchy-launch-editor", *(["--inline"] if inline else []), str(path)]
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    return [*shlex.split(editor), str(path)]


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{config_path()}: {name} must be a section, [{name}]")
    return value


def _strings(section: dict, name: str, key: str) -> tuple[str, ...]:
    value = section.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f'{config_path()}: [{name}] {key} must be a list in brackets, '
                          f'like {key} = ["one", "two"]')
    return tuple(value)


def _hostname() -> str:
    return socket.gethostname().split(".")[0]


def _hosts() -> list[Machine]:
    """The machines in the hosts file, none when there is no file."""
    path = hosts_path()
    try:
        text = path.read_text()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"{path} does not read: {e}") from None
    here = socket.gethostname()
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        words = line.split("#", 1)[0].split()
        if not words:
            continue
        if len(words) < 2:
            raise ConfigError(f"{path} line {n}: needs a label and an ssh target")
        label, target = words[:2]
        hostname = words[2] if len(words) > 2 else None
        out.append(Machine(label, target, local=target == "local"
                           or hostname in (here, here.split(".")[0])))
    return out


def identities(extra: list[str] = ()) -> dict[str, str]:
    """Email, lower case, to the account it belongs to, from the global git
    config: every [identity "<name>"] email, then user.email."""
    out: dict[str, str] = {}
    for line in _git_config("--get-regexp", r"^identity\..*\.email$").splitlines():
        key, _, email = line.partition(" ")
        name = key[len("identity."):-len(".email")]
        if email:
            out.setdefault(email.strip().lower(), name)
    user = _git_config("--get", "user.email").strip().lower()
    if user:
        out.setdefault(user, _git_config("--get", "user.name").strip() or user)
    for email in extra:
        out.setdefault(email.lower(), email)
    return out


def _git_config(*args: str) -> str:
    try:
        done = subprocess.run(["git", "config", "--global", *args], capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout if done.returncode == 0 else ""
