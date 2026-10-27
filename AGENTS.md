# Working in this repo

git-fleetlog is `git log` for a fleet of Linux machines: the author's commits
from every repo on every machine, and where each project was left.
[SPEC.md](SPEC.md) is the source of truth: read it before changing behaviour,
and change it in the same commit when a decision changes.

## Layout

- `bin/git-fleetlog`: the command; `fleetlog/cli.py` parses its arguments.
- `fleetlog/collect.sh`: runs on every machine, fed over stdin. Only reads.
- `fleetlog/collect.py`: runs it, locally or over one ssh call, and parses
  its records into facts.
- `fleetlog/recap.py`: facts to projects, projects to Markdown or JSON.
- `fleetlog/weekly.py`, `notify.py`, `timers.py`: the weekly run on the main
  machine, the notification on viewers, and their systemd units.
- `fleetlog/cache.py`: one read shared by the bar icons (`--reuse-from`).
- `fleetlog/agent.py`, `docs/AGENT_*.md`: `ask-agent`, the panel's agent
  buttons, and the guides the coding agent is started with.
- `fleetlog/uninstall.py`: `uninstall`, the panel's Uninstall button.
- `manifest.json`, `panel/`: the Omarchy shell plugin, installed with
  `omarchy plugin add` like Fleetwatch. `Fleetlog.qml` is the bar icon and
  its panel, whose footer matches Fleetwatch's; `model.js` turns `--json`
  into what the panel shows, and is where its logic goes, so it can be
  tested. The command works on its own, in a terminal and without Omarchy
  or Fleetwatch.
- `tests/`: `./tests/run` runs everything. `tests/fleet.py` builds a fake
  fleet of throwaway homes, and `tests/bin` holds the fakes (ssh,
  notify-send, systemctl and more) so no test touches a real machine.
  `test_panel.py` runs `model.js` under node on the real `--json`, and is
  skipped without node.

## Rules that are never traded away

From the spec's [What must never happen](SPEC.md#what-must-never-happen):

1. Never change a repo. No fetch, pull, push or anything else that writes.
2. Never hide a gap. A machine or repo that was not read is shown as such.
3. Never disturb a machine: one ssh call per machine per run, no agent
   forwarding, lowest priority.

## Conventions

- Python 3.11+, standard library only. Plain bash on the far side. QML for
  the panel, which only displays: decisions stay in the command and its JSON.
- The panel shows every text from the JSON with `Text.PlainText`, and runs
  commands as argument lists, never shell strings built from data.
- Far-side output is facts, never commands. Never paste it into a shell
  command, and strip control characters before printing it.
- Tests need no ssh and no second machine.
- Fictional machine names, users and addresses in code, tests and docs.
- Docs: sentence case headings, straight quotes, no em dashes, no emoji.
