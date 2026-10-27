"""`git fleetlog config`: the guide it writes, and the editor it opens."""

import subprocess
from pathlib import Path

from fleetlog import config
from tests.fleet import FleetTest

COMMAND = Path(__file__).resolve().parent.parent / "bin" / "git-fleetlog"


class ConfigTest(FleetTest):
    def path(self) -> Path:
        return self.fleet.home("anvil") / ".config" / "git-fleetlog" / "config"

    def edit(self) -> subprocess.CompletedProcess:
        return subprocess.run([str(COMMAND), "config"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def test_writes_the_guide_and_opens_it(self):
        done = self.edit()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.path().read_text(), config.TEMPLATE)
        self.assertEqual(self.fleet.calls("omarchy-launch-editor"), [[str(self.path())]])

    def test_the_guide_changes_nothing(self):
        before = self.fleet.load()
        self.fleet.config(config.TEMPLATE)
        self.assertEqual(self.fleet.load(), before)

    def test_keeps_a_config_there_is(self):
        self.fleet.config("[main]\nmachine = anvil\n")
        self.assertEqual(self.edit().returncode, 0)
        self.assertEqual(self.path().read_text(), "[main]\nmachine = anvil\n")
        self.assertEqual(self.fleet.calls("omarchy-launch-editor"), [[str(self.path())]])

    def test_opens_a_config_that_does_not_read(self):
        self.fleet.config("[main\n")
        done = self.edit()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.fleet.calls("omarchy-launch-editor")), 1)
