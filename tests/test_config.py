"""`fleetlog config` and `machines`: the files they write, the editor they
open, and how the config and the shared hosts file read."""

import re
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from fleetlog import config
from tests.fleet import FleetTest

COMMAND = Path(__file__).resolve().parent.parent / "bin" / "fleetlog"


class ConfigTest(FleetTest):
    def path(self) -> Path:
        return self.fleet.home("anvil") / ".config" / "fleet" / "log" / "config.toml"

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
        self.fleet.config('[main]\nmachine = "anvil"\n')
        self.assertEqual(self.edit().returncode, 0)
        self.assertEqual(self.path().read_text(), '[main]\nmachine = "anvil"\n')
        self.assertEqual(self.fleet.calls("omarchy-launch-editor"), [[str(self.path())]])

    def test_opens_a_config_that_does_not_read(self):
        self.fleet.config("[main\n")
        done = self.edit()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.fleet.calls("omarchy-launch-editor")), 1)


    def test_reads_every_setting(self):
        self.fleet.config("""
[main]
machine = "bench"
[folders]
all = ["~/Code"]
bench = ["~/srv"]
[exclude]
projects = ["scratch"]
repos = ["~/Projects/old"]
[identity]
emails = ["Old@Example.org"]
""")
        cfg = self.fleet.load()
        self.assertEqual(cfg.main_machine().label, "bench")
        self.assertEqual(cfg.folders_for("bench"), ("~/Code", "~/srv"))
        self.assertEqual(cfg.folders_for("crate"), ("~/Code",))
        self.assertEqual(cfg.exclude_projects, ("scratch",))
        self.assertEqual(cfg.exclude, ("~/Projects/old",))
        self.assertIn("old@example.org", cfg.identities)

    def test_says_what_is_wrong(self):
        for text, says in (("[main\n", "does not read"),
                           ("[main]\nmachine = bench\n", "does not read"),
                           ("[main]\nmachine = 1\n", "[main] machine must be a label in quotes"),
                           ('[folders]\nall = "~/Code"\n', "[folders] all must be a list"),
                           ('[exclude]\nprojects = "a b"\n', "[exclude] projects must be a list"),
                           ("[machines]\nnas = 1\n", "[machines] nas must be an ssh target"),
                           ('[machines]\nskip = "bench"\n', "[machines] skip must be a list"),
                           ('main = "bench"\n', "main must be a section")):
            with self.subTest(text=text):
                self.fleet.config(text)
                with self.assertRaisesRegex(config.ConfigError, re.escape(says)):
                    self.fleet.load()


class MachinesTest(FleetTest):
    def hosts(self) -> Path:
        return self.fleet.home("anvil") / ".config" / "fleet" / "hosts"

    def edit(self) -> subprocess.CompletedProcess:
        return subprocess.run([str(COMMAND), "machines"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)

    def labels(self) -> list[tuple[str, str, bool]]:
        return [(m.label, m.target, m.local) for m in self.fleet.load().machines]

    def test_opens_the_hosts_file_and_keeps_it(self):
        before = self.hosts().read_text()
        done = self.edit()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.fleet.calls("omarchy-launch-editor"), [[str(self.hosts())]])
        self.assertEqual(self.hosts().read_text(), before)

    def test_without_one_writes_it_with_this_machine(self):
        self.hosts().unlink()
        self.hosts().parent.rmdir()
        done = self.edit()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.fleet.calls("omarchy-launch-editor"), [[str(self.hosts())]])
        name = socket.gethostname()
        short = name.split(".")[0]
        self.assertEqual(self.hosts().read_text(),
                         config.HOSTS_TEMPLATE.format(short=short, name=name))
        self.assertTrue(self.hosts().read_text().endswith(f"\n{short}  {short}  {name}\n"))
        self.assertEqual(self.labels(), [(short, short, True)])

    def test_a_link_is_kept(self):
        real = self.fleet.home("anvil") / "dotfiles" / "hosts"
        real.parent.mkdir()
        self.hosts().rename(real)
        self.hosts().symlink_to(real)
        self.assertEqual(self.edit().returncode, 0)
        self.assertTrue(self.hosts().is_symlink())
        real.unlink()  # dangling: still never replaced
        self.assertEqual(self.edit().returncode, 0)
        self.assertTrue(self.hosts().is_symlink())
        self.assertFalse(real.exists())

    def test_without_one_the_fleet_is_this_machine(self):
        self.hosts().unlink()
        self.assertEqual(self.labels(), [(config._hostname(), "local", True)])

    def test_this_machine_by_its_hostname_in_full_or_short(self):
        self.fleet.hosts("anvil anvil.lan anvil.example.org\nbench bench bench\n"
                         "crate crate  # no hostname\n")
        with mock.patch.object(socket, "gethostname", return_value="anvil.example.org"):
            self.assertEqual(self.labels(), [("anvil", "anvil.lan", True),
                                             ("bench", "bench", False),
                                             ("crate", "crate", False)])
        self.fleet.hosts("anvil anvil.lan anvil\n")
        with mock.patch.object(socket, "gethostname", return_value="anvil.example.org"):
            self.assertEqual(self.labels(), [("anvil", "anvil.lan", True)])

    def test_extra_columns_are_ignored(self):
        self.fleet.hosts("anvil local anvil future-field\nbench bench bench more and more\n")
        self.assertEqual(self.labels(), [("anvil", "local", True), ("bench", "bench", False)])

    def test_a_line_without_a_target_says_which(self):
        self.fleet.hosts("# machines\nanvil local\nbench\n")
        with self.assertRaisesRegex(config.ConfigError, "hosts line 3: needs a label and an ssh"):
            self.fleet.load()

    def test_the_config_adds_machines(self):
        self.fleet.config('[machines]\nnas = "nas"\n')
        self.assertEqual(self.labels(), [("anvil", "local", True), ("bench", "bench", False),
                                         ("crate", "crate", False), ("nas", "nas", False)])

    def test_a_label_in_both_is_an_error(self):
        self.fleet.config('[machines]\nbench = "elsewhere"\n')
        with self.assertRaisesRegex(config.ConfigError, "bench is listed twice"):
            self.fleet.load()

    def test_skip_leaves_machines_out(self):
        self.fleet.config('[machines]\nskip = ["bench", "gone"]\n')
        self.assertEqual(self.labels(), [("anvil", "local", True), ("crate", "crate", False)])

    def test_skipping_this_machine_reads_only_the_others(self):
        self.fleet.config('[machines]\nskip = ["anvil"]\n')
        self.assertEqual(self.labels(), [("bench", "bench", False), ("crate", "crate", False)])

    def test_skipping_every_machine_is_an_error(self):
        self.fleet.hosts("anvil local\n")
        self.fleet.config('[machines]\nskip = ["anvil"]\n')
        with self.assertRaisesRegex(config.ConfigError, "leaves no machine"):
            self.fleet.load()


if __name__ == "__main__":
    unittest.main()
