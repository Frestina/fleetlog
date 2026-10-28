"""`fleetlog uninstall`: what fleetlog and its setup added on this
machine, removed after asking. The panel's Uninstall button runs it in a
terminal.

It lists what is there: the timers install wrote, fleetlog's config,
cache and state folders (fleet/log in each), the shared hosts file when no
other Fleet tool's folder is left beside it, and the
~/.local/bin/fleetlog and git-fleetlog links when they point at this
command. Then it asks whether to remove the plugin and all of that, or only
the plugin. The plugin goes first, so a running panel cannot
write its cache again. A folder that is a link, into dotfiles say, loses only
the link.

It never touches what it did not write, or what another tool still needs:
the hosts file while another Fleet tool uses it, or a Hyprland binding the
user added for the panel, which it only points out. A checkout that is not the plugin, as on a machine
without Omarchy, stays where it is: the user deletes the folder.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from fleetlog import cache, config, timers

PLUGIN_ID = "io.github.frestina.fleetlog"
COMMAND = Path(__file__).resolve().parent.parent / "bin" / "fleetlog"

Plan = list[tuple[str, Callable[[], object]]]


def plugin_dir() -> Path:
    return Path.home() / ".config" / "omarchy" / "plugins" / PLUGIN_ID


def link_paths() -> list[Path]:
    """The links install.sh makes: the command, and the one git runs."""
    return [Path.home() / ".local" / "bin" / name for name in ("fleetlog", "git-fleetlog")]


def tilde(path: Path) -> str:
    home = str(Path.home())
    return "~" + str(path)[len(home):] if str(path).startswith(home + "/") else str(path)


def our_link(link: Path) -> bool:
    """Whether link is a symlink to this command, or to the plugin's."""
    if not link.is_symlink():
        return False
    target = os.path.normpath(link.parent / os.readlink(link))
    return target in (str(COMMAND), str(plugin_dir() / "bin" / "fleetlog"))


def plan() -> Plan:
    """What fleetlog and its setup left outside the plugin folder, as
    (description, action) pairs."""
    out: Plan = []
    if units := timers.installed():
        names = sorted({n.rsplit(".", 1)[0] for n in units})
        out.append((f"the timers {', '.join(names)}", timers.remove))
    for folder in (config.config_path().parent, cache.cache_dir(), config.state_dir()):
        if folder.is_symlink():
            out.append((f"{tilde(folder)}, only the link to {tilde(folder.resolve())}",
                        folder.unlink))
        elif folder.exists():
            out.append((f"{tilde(folder)}/", lambda folder=folder: shutil.rmtree(folder)))
    # The hosts file is shared: only when no other Fleet tool's folder is left.
    hosts = config.hosts_path()
    if (hosts.exists() or hosts.is_symlink()) and not other_tools():
        what = (f"only the link to {tilde(hosts.resolve())}" if hosts.is_symlink()
                else "your list of machines")
        out.append((f"{tilde(hosts)}, {what} (no other Fleet tool uses it)", remove_hosts))
    for link in link_paths():
        if our_link(link):
            out.append((f"{tilde(link)}, a link to the fleetlog command", link.unlink))
    return out


def other_tools() -> list[Path]:
    """The other Fleet tools' folders beside the hosts file, such as fleet/watch."""
    d = config.fleet_dir()
    ours = config.config_path().parent
    return sorted(p for p in d.iterdir() if p.is_dir() and p != ours) if d.is_dir() else []


def remove_hosts() -> None:
    config.hosts_path().unlink()
    try:
        config.fleet_dir().rmdir()
    except OSError:
        pass


def bindings() -> list[str]:
    """Lines in the Hyprland config that name the plugin, as file:line."""
    out = []
    for path in sorted((config.config_home() / "hypr").glob("*.lua")):
        try:
            lines = path.read_text().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        out += [f"{tilde(path)}:{n}" for n, line in enumerate(lines, 1)
                if PLUGIN_ID in line and not line.lstrip().startswith("--")]
    return out


def ask(options: list[str]) -> str | None:
    """One of options, or None when cancelled."""
    if shutil.which("gum"):
        done = subprocess.run(["gum", "choose", *options], stdout=subprocess.PIPE, text=True)
        answer = done.stdout.strip()
        return answer if done.returncode == 0 and answer else None
    for n, option in enumerate(options, 1):
        print(f"  {n}) {option}")
    try:
        answer = input("> ").strip()
    except EOFError:
        return None
    return options[int(answer) - 1] if answer.isdigit() and 0 < int(answer) <= len(options) \
        else None


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def run() -> int:
    if not interactive():
        print("fleetlog: uninstall asks before removing anything; run it in a terminal",
              file=sys.stderr)
        return 2
    steps = plan()
    plugin = plugin_dir()
    has_plugin = plugin.exists() or plugin.is_symlink()
    everything = "Remove the plugin and all of this" if has_plugin else "Remove all of this"
    plugin_only = "Remove only the plugin"
    print("Uninstall fleetlog\n")
    if not steps and not has_plugin:
        print("Nothing to remove.")
        return 0
    if steps:
        print("Besides the plugin, fleetlog and its setup added:\n" if has_plugin
              else "fleetlog and its setup added:\n")
        for description, _ in steps:
            print(f"  - {description}")
        print()
        choice = ask([everything, plugin_only, "Cancel"] if has_plugin
                     else [everything, "Cancel"])
    else:
        print("Nothing besides the plugin needs removing.\n")
        choice = ask([plugin_only, "Cancel"])
    if choice not in (everything, plugin_only):
        print("Nothing removed.")
        return 1
    # The plugin goes first: a running panel would write its cache again.
    if has_plugin and subprocess.run(["omarchy-plugin-remove", PLUGIN_ID, "--yes"]).returncode:
        print("fleetlog: the plugin was not removed, so nothing else was either",
              file=sys.stderr)
        return 1
    status = 0
    if choice == everything:
        for description, action in steps:
            try:
                action()
                print(f"Removed {description}.")
            except (OSError, timers.TimersError) as e:
                print(f"fleetlog: could not remove {description}: "
                      f"{getattr(e, 'strerror', None) or e}", file=sys.stderr)
                status = 1
    notes(has_plugin, kept_timers=choice == plugin_only and bool(timers.installed()))
    return status


def notes(had_plugin: bool, kept_timers: bool) -> None:
    """What is left for the user to remove, or to keep."""
    print()
    if kept_timers and str(COMMAND).startswith(str(plugin_dir()) + "/"):
        print("The timers stay, but they ran the plugin's command, which is gone now. "
              "Install them again from a clone, or remove them with: systemctl --user "
              "disable --now fleetlog-weekly.timer fleetlog-retry.timer "
              "fleetlog-notify.timer")
    hosts = config.hosts_path()
    if (hosts.exists() or hosts.is_symlink()) and (others := other_tools()):
        print(f"{tilde(hosts)} stays, for the other Fleet tools here "
              f"({', '.join(tilde(p) for p in others)}).")
    if found := bindings():
        print(f"The panel's keybinding is yours to remove: {', '.join(found)}.")
    if not had_plugin:
        print(f"The command itself is in {tilde(COMMAND.parent.parent)}; delete that folder "
              "when you no longer want it.")
    print("This was this machine only; fleetlog on your other machines is untouched.")
