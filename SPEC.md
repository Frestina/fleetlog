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
- `--json` on any of these: the same facts, exact, for scripts and agents.
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

## Where things come from

- **Machines**: the Fleetwatch hosts file (`~/.config/fleetwatch/hosts`), so
  the fleet is defined in one place. Its line whose hostname is this
  machine's, or whose target is `local`, is read locally. More machines can be
  added in git-fleetlog's own config, for someone without Fleetwatch or for a
  machine Fleetwatch should not watch.
- **Repos**: found by searching folders on each machine, `~/Projects` and
  `~/dotfiles` by default, 4 levels deep. The config can add folders for every
  machine or for one machine, and exclude repos.
- **The same repo on several machines** is one project, matched by its first
  commit, so a renamed folder or remote still matches.
- **Which commits are the author's**: author email matches one of the
  addresses in the git-whoami identity config (`[identity "<name>"] email =`)
  or `user.email`. The identity's name is the account shown in the recap. A
  commit Claude helped with counts, since it carries the author's email.
  Merge commits are left out.
- **Where a commit was made**: a commit on three machines is shown once, by
  hash, under the machine whose HEAD reflog says it was made there (a commit,
  cherry-pick, rebase or merge, not a pull). When no machine says so, for
  example a commit made on github.com, it is shown under none.

## Config

`~/.config/git-fleetlog/config`, optional. Without it the defaults above
apply.

```ini
[main]
machine = homeserver       # where the weekly recap is built

[folders]
all = ~/Projects ~/dotfiles
homeserver = ~/srv         # searched there as well as the folders for all

[machines]
# Extra machines beyond the Fleetwatch hosts file: <label> = <ssh target>
nas = nas

[exclude]
repos = ~/Projects/scratch

[identity]
emails = old-address@example.org
```

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
  its own state folder, `~/.local/state/git-fleetlog/`.
- Far-side commands run under `nice -n 19` and idle IO too, so a viewer being
  read does not slow down either.
- Machines not reached are tried again hourly at :45 until Sunday night, since
  a viewer may be asleep on Friday afternoon, with the same window. The stored
  recap is updated each time one answers.
- The minutes (:15, :45, :50) keep clear of Fleet doctor's runs, on the hour
  and every 5 minutes from :02, so the two never ssh into a machine at once.
- Only the latest recap is kept, as `latest.json`: the machines' facts, so a
  viewer renders it with its own identities and config.

### The notification on viewers

- A systemd user timer on each viewer, hourly at :50 from Friday to Sunday.
- It fetches the latest recap from the main machine with one ssh call (`cat`,
  nothing else). The first time a recap from the last 3 days is there and has
  not been shown on this viewer, it raises one notification: the commit and
  project count and the busiest projects. Clicking it opens the full recap in
  a terminal (`less`), from a copy written on the viewer.
- A recap counts as shown once the notification is up, not when it is
  clicked. When notify-send fails (no notification daemon, a locked session),
  the next hour tries again.
- If the main machine cannot be reached, a notification says so, once a day,
  and it keeps trying. It does not quietly read the machines itself instead.

## What must never happen

1. **It never changes a repo.** No fetch, pull, push, gc or checkout, and
   `GIT_OPTIONAL_LOCKS=0`, so `git status` never writes the index. It reads
   what is already on disk, so "not pushed" means "not on a remote as far as
   that machine last heard", and "behind" says when that was.
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
runs the command, plain bash on the far side. Tests with a fake `ssh` and
throwaway repos and homes, no second machine (`./tests/run`). Fictional
machine names and addresses in code, tests and docs; the author's machines
in this spec are the motivating case, not test data. Docs: sentence case
headings, straight quotes, no em dashes, no emoji.
