# git-fleetlog spec

This is the source of truth for git-fleetlog. Change this file when a
decision changes.

## The problem

The author works on several machines (a laptop, a desktop, an old laptop
that is always on, a small server) and under more than one GitHub account.
Work is spread across repos on all of them. After a few days away from a
project it is hard to remember where it stopped: which machine has the
newest commits, what was never pushed, and what was finished that week at
all.

## What git-fleetlog is

`git log` for the whole fleet. One command, `git-fleetlog` (also runnable as
`git fleetlog`), collects the author's commits from every git repo on every
machine for a period (a week by default) and prints them as a short recap
grouped by project.

Each project in the recap ends with where it was left: commits not pushed,
branches never pushed, uncommitted changes and stashes, on each machine. That
is the part a GitHub activity page cannot show.

Every Friday the recap is built on the main machine and shown as a
notification on the machine the author is using.

It is a command first: everything it does works from a terminal, on any
Linux machine with Python. On Omarchy it is also a shell plugin, installed
the way Fleetwatch is, and its panel shows the same facts. It works without
Fleetwatch, and reads the list of machines every
[Fleet](https://github.com/Frestina/fleet) tool shares.

### Terms

- **Main machine**: always on, builds the weekly recap and keeps the latest
  one. For the author, the old laptop.
- **Viewer**: a machine the author sits at (laptop, desktop). It shows the
  weekly notification and can run any command on demand.
- **Project**: one repo, however many machines it is cloned on.
- **Left off**: the state a project is in right now, across machines.

## Commands

- `git fleetlog`: the recap for the last 7 days, read now from every machine.
- `git fleetlog --since <when>`: the recap from a date (`2026-10-01`) or a
  time ago (`10d`, `2w`) until now. Any past week can be built again this way,
  so past recaps are not kept.
- `git fleetlog status`: only the left-off part, for every project, with no
  time window. For "where was I?" without a week of commits around it.
- `git fleetlog latest`: the last weekly recap the main machine built (one ssh
  call to it), instead of reading every machine again.
- `git fleetlog machines`: opens the shared hosts file in the same editor,
  written first with a commented guide and this machine when there is none.
  See [Where things come from](#where-things-come-from).
- `git fleetlog config`: opens the config in Omarchy's default editor (or
  `$VISUAL`, `$EDITOR`), after writing a commented guide there when there is
  no config yet. It never changes a config that is there.
- `git fleetlog uninstall`: removes git-fleetlog from this machine, after
  asking. See [Install and remove](#install-and-remove).
- `git fleetlog ask-agent [-- <machine> <folder> [<left-off line>...]]`:
  starts the user's coding agent, on the setup or in one repo. What the
  panel's agent buttons run; see [Your agent](#your-agent).
- `--json` on any of these: the same facts, exact, for scripts and agents.
- `git fleetlog --reuse-from <unix time>`: the last 7 days from the last read
  if it started at or after that time, else from a new read that is kept for
  the next caller. The bar icon's hourly read, shared by every monitor.
- `git fleetlog weekly [--retry]` and `git fleetlog notify`: what the timers
  run. `git fleetlog timers install main|viewer`, `timers remove` and
  `timers status` manage the timers.

Exit codes: 0 when every machine was read, 1 when one was not reached or not
fully read, 2 for an error. (`git fleetlog --help` asks git for a man page;
`git-fleetlog -h` prints the help.)

## Output

One recap, not one per account. Projects are sorted by most recent commit,
and each one names its account, so both humans and agents can read it top to
bottom without matching sections. The default output is plain Markdown: it
reads well in a terminal and can be pasted into a chat or a note unchanged.

```markdown
# Recap, Oct 16 to Oct 23

Read from laptop, desktop and homeserver. Not reached: pi.

## weather-widget (personal), 12 commits

- Oct 22 laptop: Show tomorrow's frost warning
- Oct 22 laptop: Cache the forecast for an hour
- ...
- and 2 more

Left off:
- laptop: no remote, so none of it is pushed anywhere

## garden-planner (personal), 6 commits

- Oct 21 desktop: Draw beds to scale
- ...

Left off: all pushed and committed on laptop and desktop.

## Also left off

### dotfiles (personal)

Left off:
- desktop: 6 commits on main not pushed
- desktop: uncommitted changes (9 changed files)

## Not reached

- pi: ssh: connect to host pi port 22: No route to host, tried 4 times since Fri 15:15
```

A project lists at most 10 commits; `--json` has all of them. "Also left off"
holds projects with no commits in the window but something left on a
machine. `status` lists every project with something left, then the rest
under "All pushed and committed", each with the machines it was read on.

`--json` carries the same facts, and adds hashes, full times, paths, counts
and the time each machine was read.

## The panel

The Markdown recap reads top to bottom, and a long week is a lot to take in.
On an Omarchy machine the same facts are also a panel in the desktop shell,
sorted by what needs doing.

- **Opening it**: a bar icon, and a keybinding the author adds to Hyprland
  (`omarchy-shell shell toggle io.github.frestina.fleetlog`, Super+Ctrl+G
  for the author, next to Omarchy's own Super+Ctrl panels). Both toggle the
  same panel. A right click on the icon opens the full recap in a terminal.
- **The count**: the icon shows how many projects need attention, on a
  horizontal bar; the tooltip says it on a vertical one.
- **What it reads**: the last 7 days from every machine, once an hour at :20
  (`--json --reuse-from <the latest :20>`), and on the refresh button. Each
  monitor has an icon of its own, and they share one read: the command keeps
  the last read in `~/.cache/fleet/log/read.json` and answers from it when
  it started at or after the time asked for, and a lock makes callers that
  come together wait for one read. A suspend over a :20 catches up within a
  minute of the resume. Opening the panel shows the last read and asks no
  machine anything. The header says when it was: "Read at 14:20", or
  "Read Tue 14:20" on another day. The weekly recap stays what the
  notification shows and `latest` prints.
- **What it shows**, top to bottom:
  - Machines not reached or not fully read, first, as in the recap. A short
    panel never just means missing data.
  - **Needs attention**: every project with something left off, with its
    left-off lines and its commit count in the window.
  - **This week**: projects with commits and nothing left off, newest first.
  - A click on a project shows its commits, newest first, and the machines
    it is on.
  - A button opens the full Markdown recap of the same read in a terminal
    (`less`), from the cache.
  - When the list of machines holds only this one, a line says so, as in
    Fleetwatch: add the others, or let the agent find them.
  - The footer is Fleetwatch's, button for button. **Machines** (`m`) runs
    `git fleetlog machines` and **Settings** (`s`) `git fleetlog config`;
    saving the config or the hosts file reads every machine again, once
    for all monitors, so the panel shows it without a refresh.
    **Uninstall** runs `git fleetlog uninstall` in a floating terminal, since
    it asks first. **Ask agent** (`a`) is **Set up with agent**, and
    outlined, while only this machine is listed: see
    [Your agent](#your-agent). Under them, the keys: a click on a project,
    `r` refresh, `t` the full recap.
  - An agent button on the first left-off line of each machine in a
    project: see [Your agent](#your-agent).
- **Its parts**: `manifest.json` and `panel/` make this repo an Omarchy shell
  plugin, `io.github.frestina.fleetlog`: one bar widget with its own panel,
  as Omarchy's audio and Bluetooth icons are. The panel runs the plugin's own
  `bin/git-fleetlog`. See [Install and remove](#install-and-remove).
- **Its rules**: the panel only displays. Which commits count, what is left
  off and how machines are read stay in the command and its JSON. It runs the
  command with an argument list, never a shell string, and shows every text
  from the JSON as plain text, never as markup, since commit subjects and
  branch names come from other machines.

### Your agent

The panel can hand what it shows to the user's default coding agent
(Omarchy's `omarchy agent`), the way Fleetwatch does for its issues.

- **Ask agent**, in the footer: the agent starts with
  [a setup guide](docs/AGENT_SETUP.md), to go through the config, machines,
  folders, excludes and timers, or explain what the panel shows. It starts
  even when the config does not read, so it can help fix it. While only this
  machine is listed the button says **Set up with agent**, and the guide
  starts with finding the other machines and filling in the list with the
  user, as Fleetwatch's does.
- **The agent button** on a project needing attention, one per machine with
  something left off, on that machine's first line: the agent starts in the
  repo's folder on that machine, with [a guide](docs/AGENT_REPO.md) and the
  left-off lines, to work on them with the user. On this machine it opens
  as `omarchy agent` does; on another, a terminal here runs
  `ssh -t <target>` and starts that machine's own default agent inline, in
  the folder, where the work was left. A machine with no agent picked, or
  no Omarchy, gets a shell in the folder instead. The folder is the one with
  a left-off line naming it, else the project's first on that machine.
- **What it may do**: Omarchy starts agents with approvals switched off, so
  the repo guide holds the agent to looking freely and changing nothing
  (commit, push, pull, reset, dropping a stash, deleting a branch) until the
  user says yes, and never force-pushing. git-fleetlog itself still changes
  no repo: the agent does, in a session the user started and sits in.
- **Its ssh**: an interactive session the user asked for, not a run, so the
  user's own ssh config applies, agent forwarding included where it is set,
  which a push from the far side may need. The rules for runs (batch mode,
  no agent) are unchanged.
- **Far-side text**: the folder and the left-off lines came from the
  machine. They go into the prompt quoted as data, with control characters
  stripped, and to the far side as base64 arguments of a fixed script, so no
  shell ever reads them as code.
- With no default agent picked here, Omarchy's agent picker opens instead,
  with a notification saying why.

## Where things come from

- **Machines**: the hosts file every Fleet tool shares,
  `~/.config/fleet/hosts`, one machine a line as
  `<label> <ssh target> [<hostname>]`, in the format of the Fleet repo's
  [HOSTS.md](https://github.com/Frestina/fleet/blob/main/HOSTS.md). The line
  whose hostname is this machine's (in full, or up to the first dot), or
  whose target is `local`, is read locally, so the same file works copied to
  every machine. Anything after the hostname is ignored.
  - `git fleetlog machines` (the panel's Machines button) writes it the first
    time, with the header HOSTS.md gives and this machine. It never writes to
    a file that is there, or to a link to one.
  - Without it, the fleet is this machine and those in the config.
  - `[machines]` in the config adds machines only git-fleetlog should read,
    and `skip` there leaves machines in the hosts file out, by label. A label
    in both the hosts file and `[machines]` is an error.
- **Repos**: found by searching folders on each machine, `~/Projects` and
  `~/dotfiles` by default, 4 levels deep. The config can add folders for every
  machine or for one machine, and exclude repos by folder or projects by name.
- **The same repo on several machines** is one project, matched by its first
  commit, so a renamed folder or remote still matches.
- **Which commits are the author's**: author email matches one of the
  addresses in the git-whoami identity config (`[identity "<name>"] email =`)
  or `user.email`. The identity's name is the account shown in the recap. A
  commit Claude helped with counts, since it carries the author's email.
  Merge commits are left out.
- **Where a commit was made**: a commit on three machines is shown once, by
  hash, under the machine whose HEAD reflog says it was made there (a commit,
  cherry-pick, rebase, pull --rebase or merge, not a plain pull or a
  fast-forward). When no machine says so, for example a commit made on
  github.com, it is shown under none.

## Config

`~/.config/fleet/log/config.toml`, optional, in TOML. Without it the
defaults above apply. `git fleetlog config`, and the panel's settings button, open it, and
write a guide there first when there is none: every setting commented out,
so it changes nothing until one is turned on.

```toml
[main]
machine = "homeserver"            # where the weekly recap is built

[folders]
all = ["~/Projects", "~/dotfiles"]
homeserver = ["~/srv"]            # searched there as well as the folders for all

[machines]
# Machines only git-fleetlog reads, beyond the hosts file: <label> = "<ssh target>"
nas = "nas"
skip = ["pi"]                     # in the hosts file, but not read

[exclude]
projects = ["scratch"]            # by the name the recap shows, on every machine
repos = ["~/Projects/scratch"]    # that repo, and every repo under it

[identity]
emails = ["old-address@example.org"]
```

A value of the wrong kind (text where a list goes, or the other way round)
is an error that names the setting, as is a file that is not TOML.

## Install and remove

- **On Omarchy**, as a plugin, like Fleetwatch:
  `omarchy plugin add https://github.com/Frestina/fleetlog --enable`.
  Omarchy clones the repo into `~/.config/omarchy/plugins/io.github.frestina.fleetlog`
  and updates it with `omarchy plugin update`. The command comes with it;
  the plugin's `install.sh` links it into `~/.local/bin`, so `git fleetlog`
  works in a terminal too. The setup agent offers to do this.
- **Anywhere else**, such as an always-on main machine without Omarchy: a
  clone, and `install.sh` in it. Everything but the panel works the same.
- **For development**, the checkout is linked into the plugins folder
  instead, so a pull rolls it out. The shell does not reload a linked plugin
  by itself: `omarchy restart shell` after a pull that changes `panel/`.
- The timers run the command where it was when they were installed. The
  plugin's folder keeps its path across updates, so they keep working.
- **`git fleetlog uninstall`**, or Uninstall in the panel, lists what
  git-fleetlog and its setup added on this machine: the timers, its
  `fleet/log` folders for config, cache and state, the shared hosts file
  when no other Fleet tool's folder is left in `~/.config/fleet/`, and the
  `~/.local/bin/git-fleetlog` link when it points at this command. It asks
  whether to remove the plugin and all of that, only the plugin, or nothing,
  and only in a terminal. The plugin goes first (`omarchy plugin remove`),
  so a running panel cannot write its cache again; if it stays, nothing else
  goes. A folder that is a link, into dotfiles say, loses only the link, and
  a linked plugin only its link, never the checkout.
- It never removes what another tool still needs, or what it did not write:
  the hosts file stays while another Fleet tool's folder is there, and a
  Hyprland binding for the panel is pointed out for the user to remove.
  Without the plugin, the clone stays for the user to delete. It acts on
  this machine only.

## How it runs

- It reaches other machines over ssh with **one call per machine per run**
  (a common firewall rule, ufw's `limit`, refuses more than 6 ssh
  connections in 30 seconds from one source), all machines at once. On the
  far side it needs only bash, git and coreutils. Nothing is installed
  there: the script goes over stdin.
- Every ssh call is batch mode with no agent: `BatchMode=yes`,
  `ForwardAgent=no`, `IdentityAgent=none`. On the author's machines a
  forwarded login repoints the far side's agent socket and cuts off
  sessions there, and an unattended run must never pop a password
  manager's prompt.
- Each machine has 90 seconds. A machine that cannot be reached is listed
  under "Not reached", and one whose output stops early under "Not fully
  read", never left out.

### The weekly run on the main machine

The main machine runs other scripts and bots, and the author never sits at
it. The weekly run must not be noticed there:

- A systemd user timer, Fridays at 15:15, persistent, so a run missed while
  the machine was off happens when it is back. It works with nobody logged in
  only with lingering; `timers install main` says when it is off and prints
  the command, and never turns it on itself.
- The service runs at the lowest priority: `Nice=19`, idle CPU and IO
  scheduling, a 300 MB memory limit and a 15 minute time limit.
- Only one run at a time, by a lock. A run that finds the lock taken exits.
- It never starts, stops, restarts or signals anything, and only writes in
  its own state folder, `~/.local/state/fleet/log/`.
- Far-side commands run under `nice -n 19` and idle IO too, so a viewer being
  read does not slow down either.
- Machines not reached are tried again hourly at :45 until Sunday night, since
  a viewer may be asleep on Friday afternoon, with the same window. The stored
  recap is updated each time one answers.
- The minutes (:15, :45, :50, and :20 for the bar icon's read on viewers)
  keep clear of Fleet doctor's runs, on the hour and every 5 minutes from
  :02, so the two never ssh into a machine at once.
- Only the latest recap is kept, as `latest.json`: the machines' facts, so a
  viewer renders it with its own identities and config.

### The notification on viewers

- A systemd user timer on each viewer, hourly at :50 from Friday to Sunday.
- It fetches the latest recap from the main machine with one ssh call (`cat`,
  nothing else). The first time a recap from the last 3 days is there and has
  not been shown on this viewer, it raises one notification: the commit and
  project count and the busiest projects. Clicking it opens the full recap in
  a terminal (`less`), from a copy written on the viewer.
- It is critical, so it stays on screen until it is clicked or dismissed: the
  author is often away from the machine when it comes. The service waits for
  the click with no time limit. Do Not Disturb still holds it back.
- A recap counts as shown once the notification is up, not when it is
  clicked. When notify-send fails (no notification daemon, a locked session),
  the next hour tries again.
- Once the recap due last Friday at 15:15 has been shown on a viewer, it asks
  the main machine nothing until the next one is due. A timer whose time
  passed while the machine slept runs on resume, on any day, and that run
  has nothing to show.
- If the main machine cannot be reached, a notification says so, once a day,
  and it keeps trying. It does not quietly read the machines itself instead.
  When the viewer itself is offline (no network, as just after a resume) it
  says nothing and tries again the next hour: that is not the main machine
  being down.

## What must never happen

1. **It never changes a repo.** No fetch, pull, push, gc or checkout, and
   `GIT_OPTIONAL_LOCKS=0`, so `git status` never writes the index. It reads
   what is already on disk, so "not pushed" means "not on a remote as far as
   that machine last heard", and "behind" says when that was. The agent the
   user starts from the panel may change one, on the user's yes.
2. **It never hides a gap.** A machine that timed out or a repo that could not
   be read is shown as such. A short recap never just means missing data, and
   "all pushed and committed" names the machines it is true for.
3. **It never disturbs a machine.** Read-only git, lowest priority, no agent
   forwarding, no prompts during unattended runs, and nothing on the main
   machine that its other scripts and bots could notice.

Text from other machines (paths, branch names, commit subjects) is only
parsed, never run, and is stripped of control characters before it is
printed.

## Not in the first version

Reading GitHub (work done outside the machines, such as merged pull
requests), commit statistics or graphs, other people's commits, a web UI,
sending the recap anywhere by itself.

## Conventions

Same as fleetdoctor: Python 3.11+ standard library only on the machine that
runs the command, plain bash on the far side, and QML in the Omarchy shell
for the panel. Tests with a fake `ssh` and
throwaway repos and homes, no second machine (`./tests/run`). Fictional
machine names and addresses in code, tests and docs; the author's machines
in this spec are the motivating case, not test data. Docs: sentence case
headings, straight quotes, no em dashes, no emoji.
