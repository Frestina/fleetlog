"""`git fleetlog uninstall`: what it lists, what each answer removes, and
what it never touches."""

import contextlib
import io
import subprocess
from pathlib import Path
from unittest import mock

from fleetlog import timers, uninstall
from tests.fleet import FleetTest

COMMAND = Path(__file__).resolve().parent.parent / "bin" / "git-fleetlog"


class UninstallTest(FleetTest):
    def setUp(self):
        super().setUp()
        self.home = self.fleet.home("anvil")
        self.plugin = self.home / ".config" / "omarchy" / "plugins" / uninstall.PLUGIN_ID
        self.plugin.mkdir(parents=True)
        (self.plugin / "manifest.json").write_text("{}\n")
        self.folders = [self.home / ".config" / "fleet" / "log",
                        self.home / ".cache" / "fleet" / "log",
                        self.home / ".local" / "state" / "fleet" / "log"]
        self.hosts = self.home / ".config" / "fleet" / "hosts"
        for folder in self.folders:
            folder.mkdir(parents=True)
            (folder / "kept").write_text("x\n")
        self.link = self.home / ".local" / "bin" / "git-fleetlog"
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(uninstall.COMMAND)
        with contextlib.redirect_stdout(io.StringIO()):
            timers.install("viewer")
        self.fleet.clear_calls()

    def run_it(self, answer: str | None) -> tuple[int, str, list[list[str]]]:
        """Uninstall, answering the question with the option that starts
        with answer (None cancels): the exit code, the output and the
        options offered."""
        offered = []

        def ask(options):
            offered.append(options)
            return next((o for o in options if answer and o.startswith(answer)), None)

        out = io.StringIO()
        with mock.patch.object(uninstall, "interactive", return_value=True), \
                mock.patch.object(uninstall, "ask", ask), contextlib.redirect_stdout(out):
            code = uninstall.run()
        return code, out.getvalue(), offered

    def test_lists_what_is_there_and_removes_all_of_it(self):
        code, out, offered = self.run_it("Remove the plugin and all")
        self.assertEqual(code, 0, out)
        self.assertEqual(offered, [["Remove the plugin and all of this", "Remove only the plugin",
                                    "Cancel"]])
        for line in ("the timers git-fleetlog-notify", "~/.config/fleet/log/",
                     "~/.cache/fleet/log/", "~/.local/state/fleet/log/",
                     "~/.config/fleet/hosts, your list of machines (no other Fleet tool",
                     "~/.local/bin/git-fleetlog, the link"):
            self.assertIn(line, out)
        self.assertEqual(self.fleet.calls("omarchy-plugin-remove"),
                         [[uninstall.PLUGIN_ID, "--yes"]])
        self.assertFalse(self.plugin.exists())
        for folder in self.folders:
            self.assertFalse(folder.exists(), folder)
        self.assertFalse(self.link.is_symlink())
        self.assertEqual(timers.installed(), [])
        self.assertFalse(self.hosts.exists())
        self.assertFalse(self.hosts.parent.exists())

    def test_keeps_the_hosts_file_while_another_fleet_tool_uses_it(self):
        watch = self.hosts.parent / "watch"
        watch.mkdir()
        before = self.hosts.read_text()
        _, out, _ = self.run_it("Remove the plugin and all")
        self.assertNotIn("your list of machines", out)
        self.assertEqual(self.hosts.read_text(), before)
        self.assertTrue(watch.exists())
        self.assertIn("~/.config/fleet/hosts stays, for the other Fleet tools here "
                      "(~/.config/fleet/watch)", out)

    def test_a_linked_hosts_file_loses_only_the_link(self):
        real = self.home / "dotfiles" / "fleet" / "hosts"
        real.parent.mkdir(parents=True)
        self.hosts.rename(real)
        self.hosts.symlink_to(real)
        _, out, _ = self.run_it("Remove the plugin and all")
        self.assertIn("~/.config/fleet/hosts, only the link to ~/dotfiles/fleet/hosts", out)
        self.assertFalse(self.hosts.is_symlink())
        self.assertTrue(real.exists())

    def test_only_the_plugin_keeps_the_rest(self):
        code, _, _ = self.run_it("Remove only the plugin")
        self.assertEqual(code, 0)
        self.assertFalse(self.plugin.exists())
        for folder in self.folders:
            self.assertTrue((folder / "kept").exists(), folder)
        self.assertTrue(self.link.is_symlink())
        self.assertNotEqual(timers.installed(), [])

    def test_cancel_removes_nothing(self):
        code, out, _ = self.run_it(None)
        self.assertEqual(code, 1)
        self.assertIn("Nothing removed", out)
        self.assertEqual(self.fleet.calls("omarchy-plugin-remove"), [])
        self.assertTrue(self.plugin.exists())
        for folder in self.folders:
            self.assertTrue(folder.exists(), folder)

    def test_when_the_plugin_stays_nothing_else_goes(self):
        (self.fleet.root / "plugin-remove-fails").touch()
        with contextlib.redirect_stderr(io.StringIO()):
            code, _, _ = self.run_it("Remove the plugin and all")
        self.assertEqual(code, 1)
        for folder in self.folders:
            self.assertTrue(folder.exists(), folder)
        self.assertNotEqual(timers.installed(), [])

    def test_a_linked_folder_loses_only_the_link(self):
        config = self.folders[0]
        real = self.home / "dotfiles" / "fleet-log"
        real.parent.mkdir()
        config.rename(real)
        config.symlink_to(real)
        _, out, _ = self.run_it("Remove the plugin and all")
        self.assertIn("~/.config/fleet/log, only the link to ~/dotfiles/fleet-log", out)
        self.assertFalse(config.is_symlink())
        self.assertTrue((real / "kept").exists())

    def test_a_link_to_another_command_stays(self):
        self.link.unlink()
        self.link.symlink_to(self.home / "elsewhere" / "git-fleetlog")
        _, out, _ = self.run_it("Remove the plugin and all")
        self.assertNotIn("~/.local/bin/git-fleetlog", out)
        self.assertTrue(self.link.is_symlink())

    def test_a_linked_plugin_loses_only_the_link(self):
        checkout = self.home / "Projects" / "git-fleetlog"
        checkout.parent.mkdir()
        self.plugin.rename(checkout)
        self.plugin.symlink_to(checkout)
        self.run_it("Remove the plugin and all")
        self.assertFalse(self.plugin.is_symlink())
        self.assertTrue((checkout / "manifest.json").exists())

    def test_without_the_plugin_the_checkout_stays(self):
        (self.plugin / "manifest.json").unlink()
        self.plugin.rmdir()
        code, out, offered = self.run_it("Remove all")
        self.assertEqual(code, 0)
        self.assertEqual(offered, [["Remove all of this", "Cancel"]])
        self.assertEqual(self.fleet.calls("omarchy-plugin-remove"), [])
        self.assertIn("delete that folder", out)
        for folder in self.folders:
            self.assertFalse(folder.exists(), folder)

    def test_points_out_a_keybinding_and_leaves_it(self):
        bindings = self.home / ".config" / "hypr" / "bindings.lua"
        bindings.parent.mkdir(parents=True)
        text = ("-- The fleet (io.github.frestina.fleetlog)\n"
                'o.bind("SUPER + CTRL + G", "Fleetlog", '
                '"omarchy-shell shell toggle io.github.frestina.fleetlog")\n')
        bindings.write_text(text)
        _, out, _ = self.run_it("Remove the plugin and all")
        self.assertIn("~/.config/hypr/bindings.lua:2", out)
        self.assertNotIn("bindings.lua:1", out)
        self.assertEqual(bindings.read_text(), text)

    def test_asks_only_in_a_terminal(self):
        done = subprocess.run([str(COMMAND), "uninstall"], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 2)
        self.assertIn("run it in a terminal", done.stderr)
        self.assertTrue(self.plugin.exists())
        self.assertEqual(self.fleet.calls("omarchy-plugin-remove"), [])
