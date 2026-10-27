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


class MachinesTest(FleetTest):
    def fleetwatch(self) -> Path:
        return self.fleet.home("anvil") / ".config" / "fleetwatch" / "hosts"

    def own(self) -> Path:
        return self.fleet.home("anvil") / ".config" / "git-fleetlog" / "hosts"

    def edit(self) -> subprocess.CompletedProcess:
        return subprocess.run([str(COMMAND), "machines"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def test_opens_the_fleetwatch_hosts_file_when_there(self):
        before = self.fleetwatch().read_text()
        done = self.edit()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.fleet.calls("omarchy-launch-editor"), [[str(self.fleetwatch())]])
        self.assertEqual(self.fleetwatch().read_text(), before)
        self.assertFalse(self.own().exists())

    def test_without_fleetwatch_writes_its_own_with_this_machine(self):
        self.fleetwatch().unlink()
        done = self.edit()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.fleet.calls("omarchy-launch-editor"), [[str(self.own())]])
        here = config._hostname()
        self.assertEqual(self.own().read_text(), config.HOSTS_TEMPLATE.format(name=here))
        self.assertEqual(self.fleet.load().machines, (config.Machine(here, here, local=True),))

    def test_keeps_its_own_there_is(self):
        self.fleetwatch().unlink()
        self.own().parent.mkdir(parents=True)
        self.own().write_text("anvil local\n")
        self.assertEqual(self.edit().returncode, 0)
        self.assertEqual(self.own().read_text(), "anvil local\n")

    def test_its_own_is_read_without_fleetwatch(self):
        self.fleetwatch().unlink()
        self.own().parent.mkdir(parents=True)
        self.own().write_text("anvil local\nbench bench\n")
        self.assertEqual(self.fleet.load().machines,
                         (config.Machine("anvil", "local", local=True),
                          config.Machine("bench", "bench")))

    def test_its_own_adds_to_fleetwatch(self):
        self.own().parent.mkdir(parents=True)
        self.own().write_text("bench elsewhere\nnas nas\n")
        machines = self.fleet.load().machines
        self.assertEqual([(m.label, m.target) for m in machines],
                         [("anvil", "local"), ("bench", "bench"), ("crate", "crate"),
                          ("nas", "nas")])
