"""demo/fixtures/read.json, the fictional fleet in preview.png: it still reads
with this version, and shows what the preview is meant to."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "demo" / "fixtures" / "read.json"


class DemoTest(unittest.TestCase):
    def test_the_fixture_reads(self):
        """Served from the cache, as demo/run serves it to the panel."""
        fixture = json.loads(FIXTURE.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".cache" / "git-fleetlog").mkdir(parents=True)
            (home / ".cache" / "git-fleetlog" / "read.json").write_text(FIXTURE.read_text())
            (home / ".config" / "git-fleetlog").mkdir(parents=True)
            (home / ".config" / "git-fleetlog" / "config").write_text(
                "[identity]\nemails = personal work\n")
            env = {"PATH": os.environ["PATH"], "HOME": tmp, "GIT_CONFIG_GLOBAL": os.devnull,
                   "XDG_CONFIG_HOME": str(home / ".config"),
                   "XDG_CACHE_HOME": str(home / ".cache")}
            done = subprocess.run([str(ROOT / "bin" / "git-fleetlog"), "--json", "--reuse-from",
                                   str(fixture["until"])], capture_output=True, text=True,
                                  env=env, timeout=30)
        self.assertEqual(done.returncode, 1, done.stderr)  # pi is not reached
        data = json.loads(done.stdout)
        self.assertEqual([m["label"] for m in data["machines"]],
                         ["laptop", "desktop", "homeserver", "pi"])
        projects = {p["name"]: p for p in data["projects"]}
        self.assertEqual(set(projects), {"dotfiles", "invoice-tool", "weather-widget",
                                         "recipe-site", "homelab"})
        self.assertEqual([p for p in projects if projects[p]["left_off"]],
                         ["dotfiles", "invoice-tool", "weather-widget"])
        self.assertEqual(projects["invoice-tool"]["account"], "work")
