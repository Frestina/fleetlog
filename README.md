# git-fleetlog

`git log` for all your machines. It collects your commits from every repo on
every machine you list, groups them by project, and ends each project with
where you left it: commits not pushed, branches never pushed, uncommitted
changes and stashes.

```
git fleetlog              # the last 7 days
git fleetlog --since 2w   # or a date: --since 2026-10-01
git fleetlog status       # only where each project was left
git fleetlog --json       # exact data, for scripts and agents
```

It reads machines over ssh, one call per machine, and changes nothing: no
fetch, no pull, no push. The other machines need only bash and git.

## Install

```
./install.sh              # links git-fleetlog into ~/.local/bin
```

Needs Python 3.11 or newer on the machine you run it from.

Machines come from Fleetwatch's hosts file, `~/.config/fleetwatch/hosts`, one
per line as `<label> <ssh target> [<hostname>]`. Without it, git-fleetlog
reads only this machine, unless you list machines in its config. Your commits
are the ones whose author email is in your global git config: `user.email`
and every `[identity "<name>"] email`.

## Weekly recap

On a machine that is always on:

```
git fleetlog timers install main
```

It builds the recap Fridays at 15:15 at the lowest priority, and tries
machines it could not reach again every hour until Sunday. On the machines
you sit at, with `[main] machine = <its label>` in the config:

```
git fleetlog timers install viewer
git fleetlog latest       # the last weekly recap, any time
```

They show a notification once the week's recap is ready. It stays until you
click it away, and clicking it opens the recap in a terminal.

## Panel

On Omarchy the recap is also a panel in the bar, sorted by what needs doing:
projects with work left off first, then the ones all pushed. It opens on the
latest weekly recap; its refresh button reads every machine now. Click a
project for its commits; right-click the icon for the full recap in a
terminal.

```
ln -s "$PWD" ~/.config/omarchy/plugins/io.github.frestina.fleetlog
omarchy plugin enable io.github.frestina.fleetlog
```

To open it from the keyboard too, add to `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + CTRL + G", "Fleetlog", "omarchy-shell shell toggle io.github.frestina.fleetlog")
```

The shell does not reload a linked plugin by itself: run `omarchy restart
shell` after pulling a change to `panel/`.

## Config

`~/.config/git-fleetlog/config`, optional:

```ini
[main]
machine = homeserver

[folders]
all = ~/Projects ~/dotfiles
homeserver = ~/srv

[machines]
nas = nas
homeserver = local   # this machine, when it has no hosts file

[exclude]
repos = ~/Projects/scratch
```

[SPEC.md](SPEC.md) has every decision behind it.
