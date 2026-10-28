"""A fake fleet for tests: no ssh, no second machine, no real home.

FakeFleet gives every machine a throwaway home and puts tests/bin first on
the PATH. Its ssh runs the remote command here with HOME set to the target's
home, and notify-send, systemctl, loginctl, systemd-run, xdg-terminal-exec
and Omarchy's launchers only record their calls (omarchy-agent-prompt with
the folder it ran in first). The default agent is claude, or none after
no_agent(). The local machine is the first one, with its own
home as HOME, and the shared hosts file lists them all. Git reads a
fixture global config with two identities, and never the real one.

    class MyTest(FleetTest):
        def test_something(self):
            repo = self.fleet.repo("bench", "Projects/tool")
            self.fleet.commit(repo, "First")
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fleetlog import config

BIN = Path(__file__).resolve().parent / "bin"
ME = "me@example.org"
WORK = "work@example.com"
OTHER = "someone@example.net"
GITCONFIG = f"""[user]
  name = Me
  email = {ME}
[identity "personal"]
  email = {ME}
[identity "work"]
  email = {WORK}
[init]
  defaultBranch = main
[protocol "file"]
  allow = always
"""


class FakeFleet:
    def __init__(self, names=("anvil", "bench", "crate")):
        self.root = Path(tempfile.mkdtemp(prefix="fleetlog-test-"))
        (self.root / "calls").mkdir()
        self.names = names
        for name in names:
            self.home(name).mkdir(parents=True)
        (self.root / "gitconfig").write_text(GITCONFIG)
        local = self.home(names[0])
        env = {
            "PATH": f"{BIN}{os.pathsep}{os.environ.get('PATH', '')}",
            "FL_FAKE": str(self.root),
            "HOME": str(local),
            "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Me", "GIT_COMMITTER_NAME": "Me",
        }
        self._env = mock.patch.dict(os.environ, env)
        self.hosts("".join(f"{n} {'local' if n == names[0] else n}\n" for n in names))
        self._clock = 1_700_000_000

    def __enter__(self):
        self._env.start()
        for key in [k for k in os.environ if k.startswith("XDG_") and k.endswith("_HOME")]:
            del os.environ[key]
        for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL", "GIT_AUTHOR_DATE",
                    "GIT_COMMITTER_DATE", "GIT_DIR", "GIT_WORK_TREE"):
            os.environ.pop(key, None)
        return self

    def __exit__(self, *exc):
        self._env.stop()
        shutil.rmtree(self.root)

    def home(self, name: str) -> Path:
        return self.root / "homes" / name

    def hosts(self, text: str) -> None:
        path = self.home(self.names[0]) / ".config" / "fleet" / "hosts"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def config(self, text: str) -> None:
        path = self.home(self.names[0]) / ".config" / "fleet" / "log" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    # Quoted: in this class body, config is the method above, and Pythons
    # before 3.14 evaluate annotations when the class is made.
    def load(self) -> "config.Config":
        return config.load()

    def unreachable(self, name: str) -> None:
        off = self.root / "off" / name
        off.parent.mkdir(exist_ok=True)
        self.home(name).rename(off)

    def back(self, name: str) -> None:
        (self.root / "off" / name).rename(self.home(name))

    def offline(self, on: bool = True) -> None:
        """This machine has no network: ssh reaches no target."""
        flag = self.root / "offline"
        if on:
            flag.touch()
        else:
            flag.unlink()

    def no_agent(self) -> None:
        """No default coding agent is picked, here or on any machine."""
        (self.root / "no-agent").touch()

    def calls(self, name: str = "ssh") -> list[list[str]]:
        out = []
        for f in sorted((self.root / "calls").glob(f"{name}.*"), key=os.path.getmtime):
            out.append(f.read_bytes().split(b"\0")[:-1])
        return [[a.decode() for a in c] for c in out]

    def clear_calls(self) -> None:
        for f in (self.root / "calls").iterdir():
            f.unlink()

    # --- repos ------------------------------------------------------------

    def git(self, repo: Path, *args: str, email: str = ME, when: int | None = None) -> str:
        if when is None:
            self._clock += 60
            when = self._clock
        env = {**os.environ, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_EMAIL": email,
               "GIT_AUTHOR_DATE": f"@{when} +0000", "GIT_COMMITTER_DATE": f"@{when} +0000"}
        done = subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True,
                              text=True, check=True)
        return done.stdout.strip()

    def repo(self, machine: str, path: str) -> Path:
        repo = self.home(machine) / path
        repo.mkdir(parents=True)
        self.git(repo, "init", "-q")
        return repo

    def commit(self, repo: Path, subject: str, email: str = ME, when: int | None = None,
               name: str | None = None) -> str:
        name = name or f"f{len(list(repo.glob('f*')))}"
        (repo / name).write_text(subject + "\n")
        self.git(repo, "add", name)
        self.git(repo, "commit", "-q", "-m", subject, email=email, when=when)
        return self.git(repo, "rev-parse", "HEAD")

    def remote(self, repo: Path) -> Path:
        """A bare remote for repo, pushed to and tracked."""
        bare = self.root / "remotes" / f"{repo.parent.parent.name}-{repo.name}.git"
        bare.parent.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        self.git(repo, "remote", "add", "origin", str(bare))
        self.git(repo, "push", "-q", "-u", "origin", "HEAD")
        return bare

    def clone(self, bare: Path, machine: str, path: str) -> Path:
        repo = self.home(machine) / path
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", str(bare), str(repo)], check=True)
        return repo


class FleetTest(unittest.TestCase):
    names = ("anvil", "bench", "crate")

    def setUp(self):
        self.fleet = FakeFleet(self.names)
        self.fleet.__enter__()
        self.addCleanup(self.fleet.__exit__, None, None, None)
