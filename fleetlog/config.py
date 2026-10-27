"""Where git-fleetlog's machines, folders and identities come from.

Machines come from the Fleetwatch hosts file and from [machines] in
git-fleetlog's own config, in that order. A line of the hosts file is
<label> <ssh target> [<hostname>], and the line whose hostname is this
machine's, or whose target is "local", is this machine; in [machines], the
one whose target is "local". When none is, this machine is added under its
hostname. With neither file, the fleet is this machine alone.

The author's commits are the ones whose author email is in an [identity
"<name>"] section of the global git config (git-whoami's), in user.email, or
in [identity] emails here. The identity's name is the account the recap shows.

The config, ~/.config/git-fleetlog/config, is optional:

    [main]
    machine = homeserver

    [folders]
    all = ~/Projects ~/dotfiles
    homeserver = ~/srv

    [machines]
    nas = nas
    laptop = local

    [exclude]
    projects = scratch
    repos = ~/Projects/scratch

    [identity]
    emails = me@example.org

`git fleetlog config` writes TEMPLATE there when there is none, and opens it.
"""

import configparser
import os
import shlex
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

FOLDERS = ("~/Projects", "~/dotfiles")

TEMPLATE = """\
# Settings for git-fleetlog. Every one is optional: remove the # in front of
# a setting to turn it on. The panel reads every machine again when you save.

[exclude]
# Projects to leave out, by the name the recap and the panel show.
# projects = scratch old-experiment
# Or by folder, on every machine: that repo, and every repo under it.
# repos = ~/Projects/scratch

[folders]
# Where repos are looked for, 4 levels deep. "all" is every machine and
# replaces the default, ~/Projects ~/dotfiles. A line for one machine, by its
# label, adds folders there. A folder can be a single repo.
# all = ~/Projects ~/dotfiles
# homeserver = ~/srv ~/notes

[main]
# The machine that builds the weekly recap and keeps the latest one.
# machine = homeserver

[machines]
# Machines beyond the Fleetwatch hosts file: <label> = <ssh target>, or
# local for this machine.
# nas = nas

[identity]
# Author emails whose commits count as yours, beyond those in your git
# config (user.email and git-whoami's [identity "<name>"] sections).
# emails = old-address@example.org
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


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "git-fleetlog"


def config_path() -> Path:
    return config_home() / "git-fleetlog" / "config"


def hosts_path() -> Path:
    return config_home() / "fleetwatch" / "hosts"


def load() -> Config:
    parser = configparser.ConfigParser(interpolation=None, delimiters=("=",),
                                       inline_comment_prefixes=("#",))
    parser.optionxform = str  # labels keep their case
    path = config_path()
    try:
        parser.read_string(path.read_text(), source=str(path))
    except FileNotFoundError:
        pass
    except (OSError, UnicodeDecodeError, configparser.Error) as e:
        raise ConfigError(f"{path} does not read: {e}") from None

    machines = _hosts() + [Machine(label, target.strip(), local=target.strip() == "local")
                           for label, target in _section(parser, "machines").items()]
    seen: set[str] = set()
    for m in machines:
        if m.label in seen:
            raise ConfigError(f"the machine {m.label} is listed twice")
        if not m.target or m.target.startswith("-"):
            raise ConfigError(f"the machine {m.label} has no usable ssh target")
        seen.add(m.label)
    if not any(m.local for m in machines):
        machines.insert(0, Machine(_hostname(), "local", local=True))

    folders = {label: tuple(value.split())
               for label, value in _section(parser, "folders").items()}
    main = parser.get("main", "machine", fallback=None)
    return Config(
        machines=tuple(machines),
        main=main.strip() if main else None,
        folders=folders,
        exclude=tuple(parser.get("exclude", "repos", fallback="").split()),
        exclude_projects=tuple(parser.get("exclude", "projects", fallback="").split()),
        identities=identities(parser.get("identity", "emails", fallback="").split()),
    )


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


def editor_command(path: Path, inline: bool) -> list[str]:
    """Omarchy's default editor, in this terminal when there is one."""
    if shutil.which("omarchy-launch-editor"):
        return ["omarchy-launch-editor", *(["--inline"] if inline else []), str(path)]
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    return [*shlex.split(editor), str(path)]


def _section(parser: configparser.ConfigParser, name: str) -> dict[str, str]:
    return dict(parser.items(name)) if parser.has_section(name) else {}


def _hostname() -> str:
    return socket.gethostname().split(".")[0]


def _hosts() -> list[Machine]:
    path = hosts_path()
    try:
        text = path.read_text()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"{path} does not read: {e}") from None
    here = _hostname()
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        words = line.split("#", 1)[0].split()
        if not words:
            continue
        if len(words) < 2:
            raise ConfigError(f"{path} line {n}: needs a label and an ssh target")
        label, target = words[:2]
        hostname = words[2] if len(words) > 2 else None
        out.append(Machine(label, target, local=target == "local" or hostname == here))
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
