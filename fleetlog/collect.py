"""Reading the machines: collect.sh on each, one call per machine.

The local machine runs collect.sh with nice -n 19 bash -s; every other one
gets it on stdin over one ssh call. Every ssh call is batch mode with no
agent (ForwardAgent=no, IdentityAgent=none): on the author's machines a
forwarded login repoints the far side's agent socket and cuts off its
sessions, and an unattended run must never raise a key prompt.

What comes back is a machine's facts, a plain dict that json can store:

    label, reached, complete, error, hostname, read_at, home,
    missing (folders not there), problems (repos that did not read),
    repos: path, root, email, synced, remotes, head, branches, commits,
           made, changed, untracked, stashes

A machine that never answered is reached=False with the ssh error. One that
answered but whose output stops before the end record is complete=False:
what was read is kept, and the recap says it was cut off.

Far-side output is facts, never commands: it is only parsed.
"""

import re
import shlex
import subprocess
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fleetlog.config import Config, Machine

SCRIPT = Path(__file__).with_name("collect.sh")
SSH = ("ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
       "-o", "ForwardAgent=no", "-o", "IdentityAgent=none", "-o", "ClearAllForwardings=yes")
RUN = ("nice", "-n", "19", "bash", "-s", "--")
TIMEOUT = 90  # seconds, for one machine
LIMIT = 16 * 1024 * 1024  # bytes of output kept from one machine
US = "\x1f"

# Reflog subjects of a commit made on this machine, as opposed to one that
# arrived by pull, fetch or checkout. A rebase's picks are made here, those of
# pull --rebase too. A fast-forward merge and a rebase's finish only move HEAD
# to a commit that is there already, maybe one made elsewhere; every commit
# made here has a line of its own. Branch names hold no colon.
MADE = re.compile(r"(?:commit|cherry-pick|revert|am|merge(?![^:]*: Fast-forward)"
                  r"|(?:rebase|pull)[^:(]* \((?:pick|reword|squash|fixup|edit|continue)\))"
                  r"(?![\w-])")


def command(machine: Machine, since: int, until: int, folders: Sequence[str]) -> list[str]:
    args = [*RUN, str(since), str(until), *folders]
    if machine.local:
        return args
    return [*SSH, "--", machine.target, " ".join(shlex.quote(a) for a in args)]


def collect_all(cfg: Config, since: int, until: int,
                machines: Sequence[Machine] | None = None) -> list[dict]:
    """Every machine's facts, in the config's order, read at the same time."""
    machines = cfg.machines if machines is None else machines
    with ThreadPoolExecutor(max_workers=max(1, len(machines))) as pool:
        return list(pool.map(
            lambda m: collect(m, since, until, cfg.folders_for(m.label)), machines))


def collect(machine: Machine, since: int, until: int, folders: Sequence[str]) -> dict:
    script = SCRIPT.read_bytes()
    try:
        proc = subprocess.Popen(command(machine, since, until, folders), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        return unreached(machine.label, f"cannot run {e.filename or 'ssh'}: {e.strerror}")
    try:
        out, err = proc.communicate(script, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        facts = parse(machine.label, out[:LIMIT])
        if not facts["reached"]:
            return unreached(machine.label, f"no answer in {TIMEOUT}s")
        facts["error"] = f"stopped after {TIMEOUT}s, so some repos were not read"
        return facts
    stderr = err.decode(errors="replace").strip()
    last = stderr.splitlines()[-1] if stderr else f"exit {proc.returncode}"
    facts = parse(machine.label, out[:LIMIT])
    if not facts["reached"]:
        return unreached(machine.label, last)
    if len(out) > LIMIT:
        facts["complete"] = False
        facts["error"] = "too much output, so some repos were not read"
    elif not facts["complete"]:
        facts["error"] = f"the output was cut off ({last})"
    return facts


def unreached(label: str, error: str) -> dict:
    return {"label": label, "reached": False, "complete": False, "error": error,
            "read_at": int(time.time())}


def parse(label: str, out: bytes) -> dict:
    """collect.sh's output as facts."""
    facts = {"label": label, "reached": False, "complete": False, "error": None,
             "hostname": None, "read_at": int(time.time()), "home": None,
             "missing": [], "problems": [], "repos": []}
    repo = None
    for raw in out.decode(errors="replace").split("\n"):
        kind, _, rest = raw.partition(US)
        f = rest.split(US) if rest else []
        if kind == "M" and len(f) >= 3:
            facts.update(reached=True, hostname=f[0], read_at=_int(f[1]) or facts["read_at"],
                         home=f[2])
        elif not facts["reached"]:
            continue  # nothing counts before the machine said who it is
        elif kind == "E":
            facts["complete"] = True
            break
        elif kind == "N" and f:
            facts["missing"].append(f[0])
        elif kind == "X" and len(f) >= 2:
            facts["problems"].append({"path": f[0], "reason": f[1]})
        elif kind == "R" and len(f) >= 5:
            repo = {"path": f[0], "root": f[1] or None, "email": f[2] or None,
                    "synced": _int(f[3]), "remotes": _int(f[4]) or 0, "head": None,
                    "branches": [], "commits": [], "made": [], "changed": None,
                    "untracked": None, "stashes": 0}
            facts["repos"].append(repo)
        elif repo is None:
            continue
        elif kind == "H":
            repo["head"] = f[0] if f and f[0] else None
        elif kind == "B" and len(f) >= 4:
            repo["branches"].append({"name": f[0], "upstream": f[1] or None,
                                     "track": f[2] or None, "unpushed": _int(f[3])})
        elif kind == "C" and len(f) >= 4:
            repo["commits"].append({"hash": f[0], "email": f[1], "time": _int(f[2]) or 0,
                                    "subject": US.join(f[3:])})
        elif kind == "L" and len(f) >= 2 and MADE.match(f[1]):
            repo["made"].append(f[0])
        elif kind == "D" and len(f) >= 2:
            repo["changed"], repo["untracked"] = _int(f[0]), _int(f[1])
        elif kind == "S" and f:
            repo["stashes"] = _int(f[0]) or 0
    for r in facts["repos"]:
        hashes = {c["hash"] for c in r["commits"]}
        r["made"] = sorted(set(r["made"]) & hashes)
    return facts


def _int(s: str) -> int | None:
    try:
        return int(s.strip())
    except ValueError:
        return None
