"""From the machines' facts to projects, and from projects to text.

A project is one repo however many machines it is cloned on, matched by its
first commit (its root), so a renamed folder or remote still matches. A repo
with no commits yet has no root and is a project on its own.

Only the author's commits count: those whose author email is one of the
identities. A commit on three machines is shown once, under the machines
whose HEAD reflog says it was made there (a commit, cherry-pick, rebase,
pull --rebase or merge, not a plain pull or a fast-forward), or under no
machine when none says so.

Left off is a project's state now, on every machine that has it: branches
ahead of their upstream by commits that are on no remote, branches never
pushed, the checked-out branch behind its upstream as of the last sync,
uncommitted files and stashes. A project with none of that is "all pushed and
committed" on the machines that were read, and only those.

The lines say it as git does, ahead of and behind an upstream: "2 commits
ahead of origin/main", "4 commits behind origin/main". The branch is named
only when it is not its upstream's namesake.

A clone knows its remote only as of its last fetch, so one that looks up to
date may not be. Every machine is read, so they are compared: where another
clone has more commits on the same branch of the same remote, the one that
has not fetched them is behind by those too (not-fetched): one line, with
what it is behind its own upstream added in. The line is short; --json also
says how many of them are not fetched, names the machine that has them and
when that one last heard from its remotes. Nothing asks the remote.

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
# What build and the renderers raise on facts of the wrong shape.
UNREADABLE = (KeyError, TypeError, ValueError, AttributeError)
SHOWN = 10  # commits a project lists in the Markdown recap
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_BEHIND = re.compile(r"behind (\d+)")
_AHEAD = re.compile(r"ahead (\d+)")


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
          exclude: Sequence[str] = (), exclude_projects: Sequence[str] = ()) -> list[Project]:
    """Every project the reached machines have, with the author's commits
    between since and until. Repos under an exclude path are left out, and
    then the projects named in exclude_projects."""
    groups: dict[str, list[tuple[str, dict]]] = {}
    for m in facts:
        if not m.get("reached"):
            continue
        for repo in m["repos"]:
            if _excluded(repo["path"], m.get("home"), exclude):
                continue
            key = repo["root"] or f"{m['label']}:{repo['path']}"
            groups.setdefault(key, []).append((m["label"], repo))
    projects = (_project(key, members, identities, since, until) for key, members in groups.items())
    return [p for p in projects if p.name not in exclude_projects]


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

    unfetched = _unfetched(members)
    for label in dict.fromkeys(label for label, _ in members):
        repos = [r for l, r in members if l == label]
        left = _left(label, repos, unfetched)
        p.left += left
        if not left:
            p.clean_on.append(label)
    return p


def _unfetched(members: list[tuple[str, dict]]) -> dict[tuple[str, str], dict]:
    """The clones, by machine and path, whose checked-out branch tracks a
    branch that another clone of the project has further on, on the same
    remote: what this one has not fetched, as far as the other one heard.

    Each clone says where it has its upstreams, and their last commits with
    parents (history). Put together, that tells whether one clone's upstream
    is in another's past, and how many commits lie between. count is exact
    unless at_least is set: then a commit between them has parents no machine
    sent, and there may be more behind it. When neither is in the other's
    past as far as the histories go (more commits apart than were sent, or a
    rewritten branch), count is None, and the clone whose upstream is the
    older commit is the one that says so."""
    graph: dict[str, list[str]] = {}
    for _, r in members:
        graph.update(r.get("history") or {})
    views: dict[tuple[str, str], list[tuple[str, dict, dict]]] = {}
    for label, r in members:
        for b in r["branches"]:
            if b.get("upstream_tip") and b.get("remote") and b.get("remote_branch"):
                views.setdefault((b["remote"], b["remote_branch"]), []).append((label, r, b))
    past: dict[str, set[str]] = {}

    def reach(tip: str) -> set[str]:
        if tip not in past:
            seen, todo = {tip}, [tip]
            while todo:
                for parent in graph.get(todo.pop(), ()):
                    if parent not in seen:
                        seen.add(parent)
                        todo.append(parent)
            past[tip] = seen
        return past[tip]

    out = {}
    for label, r in members:
        head = next((b for b in r["branches"] if b["name"] == r["head"]), None)
        if head is None or not head.get("upstream_tip"):
            continue
        mine = head["upstream_tip"]
        best = None
        for other_label, other, b in views.get((head.get("remote"), head.get("remote_branch")), ()):
            theirs = b["upstream_tip"]
            if theirs == mine:
                continue
            if mine in reach(theirs):
                ahead = reach(theirs) - reach(mine)
                count = sum(c in graph for c in ahead)
                rank = (1, count)
                found = {"count": count, "at_least": count < len(ahead)}
            elif theirs in reach(mine):
                continue  # that one has not fetched what this one has
            elif (head.get("upstream_time") or 0) <= (b.get("upstream_time") or 0):
                rank = (0, b.get("upstream_time") or 0)
                found = {"count": None, "at_least": False}
            else:
                continue
            if best is None or rank > best[0]:
                has = other_label if other_label != label else clean(other["path"])
                best = (rank, {**found, "has": has, "synced": other.get("synced")})
        if best:
            out[label, r["path"]] = best[1]
    return out


def _left(label: str, repos: list[dict],
          unfetched: dict[tuple[str, str], dict] | None = None) -> list[dict]:
    """What is left off on one machine, across its clones. Worktrees of one
    clone share its branches and stashes, so those count once per clone, by
    the git common dir; facts read before it was collected count them once
    per machine. unfetched is what _unfetched found for the project."""
    out = []
    several = len(repos) > 1
    groups: dict[str | None, list[dict]] = {}
    for r in repos:
        groups.setdefault(r.get("common"), []).append(r)
    # With several clones, each line says which one, and its path goes to the
    # agent button.
    clones = [(clone, {"machine": label, "path": clone[0]["path"]},
               f"{label} ({clean(clone[0]['path'])})") if len(groups) > 1
              else (clone, {"machine": label}, label) for clone in groups.values()]
    for clone, at, who in clones:
        if all(r["remotes"] == 0 for r in clone):
            out.append({**at, "kind": "no-remote",
                        "text": f"{who}: no remote, so none of it is pushed anywhere"})
        branches: dict[str, dict] = {}
        for r in clone:
            if r["remotes"] == 0:
                continue
            for b in r["branches"]:
                branches.setdefault(b["name"], b)
        for name, b in branches.items():
            n = b["unpushed"] or 0
            if n and b["upstream"] is None:
                out.append({**at, "kind": "never-pushed", "branch": name, "count": n,
                            "text": f"{who}: branch {clean(name)} was never pushed "
                                    f"({_n(n, 'commit')})"})
            elif n and (ahead := _AHEAD.search(b["track"] or "")):
                # Said when commits are on no remote, as before. The count is
                # git's: what the branch is ahead of its upstream by, which
                # also holds commits that are only on another branch there.
                n = int(ahead.group(1))
                out.append({**at, "kind": "unpushed", "branch": name, "count": n,
                            "text": f"{who}: {_is(name, b['upstream'])}{_n(n, 'commit')} "
                                    f"ahead of {clean(b['upstream'])}"})
            elif n:
                # Its upstream is gone, so there is nothing to be ahead of.
                out.append({**at, "kind": "unpushed", "branch": name, "count": n,
                            "text": f"{who}: {_n(n, 'commit')} on {clean(name)} on no "
                                    f"remote"})
    for r in repos:
        where = f"{label} ({clean(r['path'])})" if several else label
        head = next((b for b in r["branches"] if b["name"] == r["head"]), None)
        u = (unfetched or {}).get((label, r["path"])) if head else None
        behind = 0
        if head and head["upstream"] and head["track"]:
            if found := _BEHIND.search(head["track"]):
                behind = int(found.group(1))
            elif head["track"] == "gone":
                out.append({"machine": label, "kind": "gone", "branch": head["name"],
                            "text": f"{where}: {clean(head['name'])}'s upstream "
                                    f"{clean(head['upstream'])} is gone"})
        # Behind its own upstream as of its last sync, and behind what another
        # machine has fetched since: one line, for the two together.
        if behind and (u is None or u["count"] is None):
            synced = f", as of {_day(r['synced'])}" if r["synced"] else ""
            out.append({"machine": label, "kind": "behind", "branch": head["name"],
                        "count": behind,
                        "text": f"{where}: {_is(head['name'], head['upstream'])}"
                                f"{_n(behind, 'commit')} behind {clean(head['upstream'])}"
                                f"{synced}"})
        if u:
            up = clean(head["upstream"])
            if u["count"] is None:
                count = None
                text = (f"{where}: {up} is not where {clean(u['has'])} has it, too far "
                        f"apart to count or rewritten")
            else:
                count = behind + u["count"]
                text = (f"{where}: {_is(head['name'], head['upstream'])}"
                        f"{'at least ' if u['at_least'] else ''}{_n(count, 'commit')} "
                        f"behind {up}")
            out.append({"machine": label, "kind": "not-fetched", "path": r["path"],
                        "branch": head["name"], "upstream": head["upstream"],
                        "count": count, "not_fetched": u["count"],
                        "at_least": u["at_least"], "has": u["has"],
                        "as_of": _stamp(u["synced"]) if u["synced"] else None,
                        "text": text})
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
    for clone, at, who in clones:
        if stashes := max(r["stashes"] for r in clone):
            out.append({**at, "kind": "stash", "count": stashes,
                        "text": f"{who}: {_n(stashes, 'stash', 'stashes')}"})
    return out


def _is(branch: str, upstream: str) -> str:
    """How a line about a branch and its upstream starts: with nothing for
    main and origin/main, and with "fix is " for fix and origin/main."""
    return "" if upstream.endswith("/" + branch) else f"{clean(branch)} is "


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
    unfound = [(m["label"], f) for m in facts for f in m.get("folders_not_found", [])]
    if unfound:
        out += ["## Folders not found", ""]
        out += [f"- {label}: {clean(f)}, named for it in [folders]" for label, f in unfound]
        out.append("")
    return out


# --- JSON -----------------------------------------------------------------

def as_json(facts: Sequence[dict], projects: Sequence[Project], since: int, until: int,
            status: bool = False, notices: Sequence[str] = (), group: str = "machine") -> str:
    """notices: about this machine's setup, such as timers that are not what
    the config says, each saying what to run. group: [panel] group in the
    config, for the panel, which reads nothing but this."""
    data = {
        "schema": SCHEMA,
        "kind": "status" if status else "recap",
        "since": None if status else _stamp(since),
        "until": _stamp(until),
        "notices": list(notices),
        "panel": {"group": group},
        "machines": [{
            "label": m["label"], "local": bool(m.get("local")),
            "reached": bool(m.get("reached")), "complete": bool(m.get("complete")),
            "error": m.get("error"),
            "read_at": _stamp(m["read_at"]) if m.get("read_at") else None,
            "tries": m.get("tries", 1),
            "problems": m.get("problems", []), "missing_folders": m.get("missing", []),
            "folders_not_found": m.get("folders_not_found", []),
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
