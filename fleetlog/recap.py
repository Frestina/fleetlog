"""From the machines' facts to projects, and from projects to text.

A project is one repo however many machines it is cloned on, matched by its
first commit (its root), so a renamed folder or remote still matches. A repo
with no commits yet has no root and is a project on its own.

Only the author's commits count: those whose author email is one of the
identities. A commit on three machines is shown once, under the machines
whose HEAD reflog says it was made there (a commit, cherry-pick, rebase,
pull --rebase or merge, not a plain pull or a fast-forward), or under no
machine when none says so.

Left off is a project's state now, on every machine that has it: commits not
pushed, branches never pushed, the checked-out branch behind its upstream as
of the last sync, uncommitted files and stashes. A project with none of that
is "all pushed and committed" on the machines that were read, and only those.

Text from far-side machines (paths, branch names, subjects) is stripped of
control characters before it is printed, so a commit subject cannot move the
cursor or retitle the terminal.
"""

import datetime
import json
import os
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

SCHEMA = 1
SHOWN = 10  # commits a project lists in the Markdown recap
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_BEHIND = re.compile(r"behind (\d+)")


@dataclass
class Project:
    key: str
    name: str
    account: str | None
    commits: list[dict] = field(default_factory=list)
    left: list[dict] = field(default_factory=list)
    clean_on: list[str] = field(default_factory=list)
    paths: dict[str, list[str]] = field(default_factory=dict)

    @property
    def latest(self) -> int:
        return max((c["time"] for c in self.commits), default=0)


def clean(text: str) -> str:
    return _CONTROL.sub("", text)


def build(facts: Sequence[dict], identities: dict[str, str], since: int, until: int,
          exclude: Sequence[str] = ()) -> list[Project]:
    """Every project the reached machines have, with the author's commits
    between since and until."""
    groups: dict[str, list[tuple[str, dict]]] = {}
    for m in facts:
        if not m.get("reached"):
            continue
        for repo in m["repos"]:
            if _excluded(repo["path"], m.get("home"), exclude):
                continue
            key = repo["root"] or f"{m['label']}:{repo['path']}"
            groups.setdefault(key, []).append((m["label"], repo))
    return [_project(key, members, identities, since, until) for key, members in groups.items()]


def _excluded(path: str, home: str | None, exclude: Sequence[str]) -> bool:
    for ex in exclude:
        if ex == "~" or ex.startswith("~/"):
            if not home:
                continue
            ex = home + ex[1:]
        ex = ex.rstrip("/")
        if path == ex or path.startswith(ex + "/"):
            return True
    return False


def _project(key: str, members: list[tuple[str, dict]], identities: dict[str, str],
             since: int, until: int) -> Project:
    names = Counter(os.path.basename(r["path"].rstrip("/")) for _, r in members)
    account = next((identities[r["email"].lower()] for _, r in members
                    if r["email"] and r["email"].lower() in identities), None)
    p = Project(key, clean(names.most_common(1)[0][0]), account)

    commits: dict[str, dict] = {}
    for label, repo in members:
        p.paths.setdefault(label, []).append(repo["path"])
        made = set(repo["made"])
        for c in repo["commits"]:
            if c["email"].lower() not in identities or not since <= c["time"] <= until:
                continue
            entry = commits.setdefault(c["hash"], {
                "hash": c["hash"], "time": c["time"], "subject": c["subject"],
                "account": identities[c["email"].lower()], "made_on": []})
            if c["hash"] in made and label not in entry["made_on"]:
                entry["made_on"].append(label)
    p.commits = sorted(commits.values(), key=lambda c: c["time"], reverse=True)
    if p.account is None and p.commits:
        p.account = Counter(c["account"] for c in p.commits).most_common(1)[0][0]

    for label in dict.fromkeys(label for label, _ in members):
        repos = [r for l, r in members if l == label]
        left = _left(label, repos)
        p.left += left
        if not left:
            p.clean_on.append(label)
    return p


def _left(label: str, repos: list[dict]) -> list[dict]:
    """What is left off on one machine, across its clones (worktrees share
    branches, so each branch counts once)."""
    out = []
    several = len(repos) > 1
    if all(r["remotes"] == 0 for r in repos):
        out.append({"machine": label, "kind": "no-remote",
                    "text": f"{label}: no remote, so none of it is pushed anywhere"})
    branches: dict[str, dict] = {}
    for r in repos:
        if r["remotes"] == 0:
            continue
        for b in r["branches"]:
            branches.setdefault(b["name"], b)
    for name, b in branches.items():
        n = b["unpushed"] or 0
        if n and b["upstream"] is None:
            out.append({"machine": label, "kind": "never-pushed", "branch": name, "count": n,
                        "text": f"{label}: branch {clean(name)} was never pushed "
                                f"({_n(n, 'commit')})"})
        elif n:
            out.append({"machine": label, "kind": "unpushed", "branch": name, "count": n,
                        "text": f"{label}: {_n(n, 'commit')} on {clean(name)} not pushed"})
    for r in repos:
        where = f"{label} ({clean(r['path'])})" if several else label
        head = next((b for b in r["branches"] if b["name"] == r["head"]), None)
        if head and head["upstream"] and head["track"]:
            behind = _BEHIND.search(head["track"])
            if behind:
                n = int(behind.group(1))
                synced = f", as of {_day(r['synced'])}" if r["synced"] else ""
                out.append({"machine": label, "kind": "behind", "branch": head["name"],
                            "count": n,
                            "text": f"{where}: {clean(head['name'])} is {_n(n, 'commit')} behind "
                                    f"{clean(head['upstream'])}{synced}"})
            elif head["track"] == "gone":
                out.append({"machine": label, "kind": "gone", "branch": head["name"],
                            "text": f"{where}: {clean(head['name'])}'s upstream "
                                    f"{clean(head['upstream'])} is gone"})
        changed, untracked = r["changed"] or 0, r["untracked"] or 0
        if changed or untracked:
            parts = [f"{changed} changed" if changed else "",
                     f"{untracked} untracked" if untracked else ""]
            out.append({"machine": label, "kind": "uncommitted", "path": r["path"],
                        "changed": changed, "untracked": untracked,
                        "text": f"{where}: uncommitted changes "
                                f"({', '.join(x for x in parts if x)} "
                                f"{'file' if changed + untracked == 1 else 'files'})"})
        elif r["changed"] is None:
            out.append({"machine": label, "kind": "unknown", "path": r["path"],
                        "text": f"{where}: could not tell whether anything is uncommitted"})
    stashes = max((r["stashes"] for r in repos), default=0)
    if stashes:
        out.append({"machine": label, "kind": "stash", "count": stashes,
                    "text": f"{label}: {_n(stashes, 'stash', 'stashes')}"})
    return out


def _n(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def _time(t: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(t)


def _day(t: int) -> str:
    d = _time(t)
    return f"{d:%b} {d.day}"


def _stamp(t: int) -> str:
    return datetime.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


def _list(labels: Sequence[str]) -> str:
    if len(labels) <= 1:
        return "".join(labels)
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


# --- Markdown -------------------------------------------------------------

def markdown(facts: Sequence[dict], projects: Sequence[Project], since: int, until: int,
             status: bool = False) -> str:
    lines = []
    if status:
        lines += [f"# Left off, {_day(until)} {_time(until):%H:%M}", ""]
    else:
        lines += [f"# Recap, {_day(since)} to {_day(until)}", ""]
    lines += [_read_line(facts), ""]

    if status:
        shown = sorted((p for p in projects if p.left), key=lambda p: p.name.lower())
        for p in shown:
            lines += [f"## {_title(p)}", "", *_left_lines(p), ""]
        tidy = sorted((p for p in projects if not p.left), key=lambda p: p.name.lower())
        if tidy:
            lines += ["## All pushed and committed", ""]
            lines += [f"- {_title(p)}: {_list(p.clean_on)}" for p in tidy]
            lines.append("")
        if not projects:
            lines += ["No repos found.", ""]
    else:
        worked = sorted((p for p in projects if p.commits), key=lambda p: p.latest, reverse=True)
        for p in worked:
            lines += [f"## {_title(p)}, {_n(len(p.commits), 'commit')}", ""]
            for c in p.commits[:SHOWN]:
                on = f" {'+'.join(c['made_on'])}" if c["made_on"] else ""
                lines.append(f"- {_day(c['time'])}{on}: {clean(c['subject'])}")
            if len(p.commits) > SHOWN:
                lines.append(f"- and {len(p.commits) - SHOWN} more")
            lines += ["", *_left_lines(p), ""]
        if not worked:
            lines += ["No commits of yours in this time.", ""]
        waiting = sorted((p for p in projects if not p.commits and p.left),
                         key=lambda p: p.name.lower())
        if waiting:
            lines += ["## Also left off", ""]
            for p in waiting:
                lines += [f"### {_title(p)}", "", *_left_lines(p), ""]

    lines += _gaps(facts)
    return "\n".join(lines).rstrip("\n") + "\n"


def _title(p: Project) -> str:
    return f"{p.name} ({p.account})" if p.account else p.name


def _left_lines(p: Project) -> list[str]:
    if not p.left:
        return [f"Left off: all pushed and committed on {_list(p.clean_on)}."]
    return ["Left off:", *(f"- {e['text']}" for e in p.left)]


def _read_line(facts: Sequence[dict]) -> str:
    read = [m["label"] for m in facts if m.get("reached")]
    missed = [m["label"] for m in facts if not m.get("reached")]
    line = f"Read from {_list(read)}." if read else "No machine could be read."
    if missed:
        line += f" Not reached: {_list(missed)}."
    return line


def _gaps(facts: Sequence[dict]) -> list[str]:
    out = []
    missed = [m for m in facts if not m.get("reached")]
    if missed:
        out += ["## Not reached", ""]
        for m in missed:
            tried = ""
            if m.get("tries", 1) > 1 and m.get("first_tried"):
                first = _time(m["first_tried"])
                tried = f", tried {m['tries']} times since {first:%a} {first:%H:%M}"
            out.append(f"- {m['label']}: {clean(m['error'] or 'no answer')}{tried}")
        out.append("")
    partial = [m for m in facts if m.get("reached")
               and (not m.get("complete") or m.get("problems"))]
    if partial:
        out += ["## Not fully read", ""]
        for m in partial:
            if not m.get("complete"):
                out.append(f"- {m['label']}: {clean(m['error'] or 'the output was cut off')}")
            for pr in m.get("problems", []):
                where = f"{clean(pr['path'])}: " if pr["path"] else ""
                out.append(f"- {m['label']}: {where}{clean(pr['reason'])}")
        out.append("")
    return out


# --- JSON -----------------------------------------------------------------

def as_json(facts: Sequence[dict], projects: Sequence[Project], since: int, until: int,
            status: bool = False) -> str:
    data = {
        "schema": SCHEMA,
        "kind": "status" if status else "recap",
        "since": None if status else _stamp(since),
        "until": _stamp(until),
        "machines": [{
            "label": m["label"], "reached": bool(m.get("reached")),
            "complete": bool(m.get("complete")), "error": m.get("error"),
            "read_at": _stamp(m["read_at"]) if m.get("read_at") else None,
            "tries": m.get("tries", 1),
            "problems": m.get("problems", []), "missing_folders": m.get("missing", []),
        } for m in facts],
        "projects": [{
            "name": p.name, "account": p.account, "root": p.key if ":" not in p.key else None,
            "paths": p.paths,
            "commits": [] if status else [
                {**c, "time": _stamp(c["time"])} for c in p.commits],
            "left_off": p.left, "clean_on": p.clean_on,
        } for p in sorted(projects, key=lambda p: (-p.latest, p.name.lower()))],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def all_read(facts: Sequence[dict]) -> bool:
    return all(m.get("reached") and m.get("complete") and not m.get("problems") for m in facts)
