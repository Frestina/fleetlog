"""The weekly recap on the main machine, and fetching it from anywhere.

weekly reads every machine for the last 7 days and stores their facts in
latest.json in the state folder, replacing last week's: past weeks are not
kept, since --since builds any of them again. weekly --retry reads only the
machines that were not reached or not fully read, with the same window, and
stores what it gets. It does nothing more than 3 days after the window ends,
or when everything was read.

Both take a lock first. A run that finds it taken exits, so a slow run and the
next timer never read the machines twice at once.

latest fetches latest.json: from the state folder on the main machine, and
with one ssh call (cat, nothing else) from anywhere else.
"""

import fcntl
import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from fleetlog import collect, config, recap
from fleetlog.config import Config

LATEST = "latest.json"
WEEK = 7 * 24 * 3600
RETRY_FOR = 3 * 24 * 3600  # after the window ends
REMOTE = 'cat -- "${XDG_STATE_HOME:-$HOME/.local/state}/fleet/log/latest.json"'
TIMEOUT = 30


class Busy(Exception):
    """Another run holds the lock."""


class NoRecap(Exception):
    """The latest recap could not be had; says why."""


class Unreachable(NoRecap):
    """The main machine did not answer."""


class Offline(Unreachable):
    """This machine has no network, so the main machine was never asked."""


# ssh errors that come from this machine having no network (no route at all,
# no name server), as just after a resume, not from the main machine.
OFFLINE = ("Network is unreachable", "Temporary failure in name resolution")


@contextmanager
def locked():
    d = config.state_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(d / "lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy("another fleetlog run is reading the machines") from None
        yield


def weekly(cfg: Config) -> int:
    with locked():
        until = int(time.time())
        since = until - WEEK
        facts = collect.collect_all(cfg, since, until)
        for f in facts:
            f["tries"], f["first_tried"] = 1, f["read_at"]
        save({"schema": recap.SCHEMA, "since": since, "until": until, "built_at": until,
              "updated_at": until, "facts": facts})
        _report(facts)
        return 0 if recap.all_read(facts) else 1


def retry(cfg: Config) -> int:
    with locked():
        try:
            data = load_local()
        except NoRecap as e:
            print(f"nothing to retry: {e}")
            return 0
        now = int(time.time())
        if now - data["until"] > RETRY_FOR:
            print("nothing to retry: the latest recap is too old")
            return 0
        todo = [f for f in data["facts"] if not recap.all_read([f])]
        machines = [m for f in todo if (m := cfg.machine(f["label"])) is not None]
        if not machines:
            print("nothing to retry: every machine was read")
            return 0
        new = {f["label"]: f for f in collect.collect_all(cfg, data["since"], data["until"],
                                                          machines)}
        for i, old in enumerate(data["facts"]):
            f = new.get(old["label"])
            if f is None:
                continue
            f["tries"] = old.get("tries", 1) + 1
            f["first_tried"] = old.get("first_tried", old.get("read_at"))
            if not f["reached"] and old.get("reached"):
                # Keep what an earlier try did read, and say this one failed.
                old.update(tries=f["tries"], error=f"{old.get('error')}; then {f['error']}")
                continue
            data["facts"][i] = f
        data["updated_at"] = now
        save(data)
        _report([new[m.label] for m in machines])
        return 0 if recap.all_read(data["facts"]) else 1


def _report(facts: list[dict]) -> None:
    for f in facts:
        if recap.all_read([f]):
            print(f"{f['label']}: read, {len(f['repos'])} repos")
        else:
            print(f"{f['label']}: {f.get('error') or 'not fully read'}")


def save(data: dict) -> None:
    path = config.state_dir() / LATEST
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data) + "\n")
    os.replace(tmp, path)


def load_local() -> dict:
    path = config.state_dir() / LATEST
    try:
        return check(path.read_bytes(), "here")
    except FileNotFoundError:
        raise NoRecap("no weekly recap has been built here yet") from None
    except OSError as e:
        raise NoRecap(f"cannot read {path}: {e.strerror}") from None


def fetch(cfg: Config) -> dict:
    """The latest recap, from the main machine, or NoRecap."""
    main = cfg.main_machine()
    if main is None or main.local:
        return load_local()
    argv = [*collect.SSH, "--", main.target, REMOTE]
    try:
        done = subprocess.run(argv, capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=TIMEOUT)
    except OSError as e:
        raise Unreachable(f"cannot run ssh: {e.strerror}") from None
    except subprocess.TimeoutExpired:
        raise Unreachable(f"{main.label} gave no answer in {TIMEOUT}s") from None
    err = done.stderr.decode(errors="replace").strip().splitlines()
    if done.returncode == 255:
        last = err[-1] if err else "ssh exited 255"
        if any(o in last for o in OFFLINE):
            raise Offline(f"cannot reach {main.label}, this machine is offline: {last}")
        raise Unreachable(f"cannot reach {main.label}: {last}")
    if done.returncode != 0:
        if any("No such file" in line for line in err):
            raise NoRecap(f"no weekly recap has been built on {main.label} yet")
        raise NoRecap(f"cannot read the recap on {main.label}: "
                      f"{err[-1] if err else f'exit {done.returncode}'}")
    return check(done.stdout, main.label)


def check(raw: bytes, where: str) -> dict:
    """The stored recap, if it has the shape this version writes, or NoRecap."""
    try:
        data = json.loads(raw)
        if data["schema"] != recap.SCHEMA:
            raise ValueError(f"schema {data['schema']!r}")
        for key in ("since", "until"):
            if not isinstance(data[key], int):
                raise TypeError(key)
        if not all(isinstance(f, dict) and isinstance(f.get("label"), str)
                   for f in data["facts"]):
            raise TypeError("facts")
    except (ValueError, KeyError, TypeError) as e:
        raise NoRecap(f"the recap on {where} does not read ({type(e).__name__}: {e})") from None
    return data


def window_id(data: dict) -> str:
    return str(data["until"])


def state_file(name: str) -> Path:
    return config.state_dir() / name
