"""A read of every machine that several callers share: the bar icon.

The icon on each monitor asks for the last 7 days every hour, and one read
should answer them all. `--reuse-from <unix time>` reuses the last read if it
started at or after that time; otherwise it reads every machine now and keeps
that read, in the cache folder, for the next caller. A lock makes callers
that come together wait for one read instead of starting their own.

The read is stored as the machines' facts, like the weekly recap's
latest.json, so it is rendered like any other read.
"""

import fcntl
import json
import os
import time
from pathlib import Path

from fleetlog import collect, recap, weekly
from fleetlog.config import Config

NAME = "read.json"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "git-fleetlog"


def read(cfg: Config, reuse_from: int) -> dict:
    """The last read if it started at or after reuse_from, else a new one."""
    d = cache_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = d / NAME
    with open(d / "lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = weekly.check(path.read_bytes(), "the cache")
            if data["until"] >= reuse_from:
                return data
        except (OSError, weekly.NoRecap):
            pass  # none yet, or unreadable: read again
        until = int(time.time())
        since = until - weekly.WEEK
        data = {"schema": recap.SCHEMA, "since": since, "until": until,
                "facts": collect.collect_all(cfg, since, until)}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data) + "\n")
        os.replace(tmp, path)
        return data
