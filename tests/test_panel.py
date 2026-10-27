"""The panel's model, panel/model.js, on git-fleetlog's real --json.

It runs under node (tests/panel_view.js); the shell runs the same file as a
QML library. Skipped when node is not installed.
"""

import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from fleetlog import cli
from tests.fleet import FleetTest

NODE = shutil.which("node")
RUNNER = Path(__file__).with_name("panel_view.js")
SINCE = "2023-11-01"  # the fake fleet's clock starts in November 2023
OLD = 1_600_000_000  # a commit long before SINCE


@unittest.skipUnless(NODE, "node is not installed")
class PanelTest(FleetTest):
    def recap(self) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--since", SINCE, "--json"])
        return out.getvalue()

    def model(self, text: str, now: float | None = None) -> dict:
        now = datetime.datetime.now(datetime.timezone.utc).timestamp() if now is None else now
        done = subprocess.run([NODE, str(RUNNER), str(int(now * 1000))], input=text,
                              capture_output=True, text=True, check=True,
                              env={**os.environ, "TZ": "UTC"})
        return json.loads(done.stdout)

    def view(self) -> dict:
        out = self.model(self.recap())
        self.assertNotIn("error", out)
        return out["view"]

    def test_projects_are_sorted_by_what_needs_doing(self):
        tool = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(tool, "Draw beds")
        self.fleet.remote(tool)
        notes = self.fleet.repo("bench", "Projects/notes")
        self.fleet.commit(notes, "Write it down")
        old = self.fleet.repo("crate", "Projects/old")
        self.fleet.commit(old, "Long ago", when=OLD)
        self.fleet.remote(old)

        view = self.view()
        self.assertEqual([p["name"] for p in view["attention"]], ["notes"])
        self.assertEqual([p["name"] for p in view["worked"]], ["tool"])
        self.assertEqual(view["quiet"], 1)
        self.assertEqual(view["gaps"], [])
        self.assertEqual(view["readLine"], "Read from anvil, bench and crate.")

        [notes] = view["attention"]
        self.assertEqual(notes["account"], "personal")
        self.assertEqual(notes["countText"], "1 commit")
        self.assertEqual(notes["left"], [{
            "text": "bench: no remote, so none of it is pushed anywhere",
            "ask": {"machine": "bench", "path": notes_path(self, "bench"),
                    "lines": ["bench: no remote, so none of it is pushed anywhere"]}}])
        [line] = notes["commits"]
        self.assertTrue(line.startswith("Nov "), line)
        self.assertTrue(line.endswith(" bench: Write it down"), line)
        self.assertEqual(notes["machines"], [f"bench: {notes_path(self, 'bench')}"])

    def test_each_machine_with_work_left_gets_one_agent_button(self):
        tool = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(tool, "First")
        bare = self.fleet.remote(tool)
        self.fleet.commit(tool, "Here")
        (tool / "draft").write_text("half done\n")
        there = self.fleet.clone(bare, "bench", "Projects/tool")
        self.fleet.commit(there, "There")

        [p] = self.view()["attention"]
        self.assertEqual([line["text"] for line in p["left"]], [
            "anvil: 1 commit on main not pushed",
            "anvil: uncommitted changes (1 untracked file)",
            "bench: 1 commit on main not pushed",
        ])
        first, second, third = p["left"]
        self.assertEqual(first["ask"], {"machine": "anvil", "path": str(tool),
                                        "lines": [first["text"], second["text"]]})
        self.assertIsNone(second["ask"])
        self.assertEqual(third["ask"], {"machine": "bench", "path": str(there),
                                        "lines": [third["text"]]})

    def test_a_machine_not_reached_comes_first_and_is_named(self):
        self.fleet.commit(self.fleet.repo("anvil", "Projects/tool"), "First")
        self.fleet.unreachable("crate")
        view = self.view()
        [gap] = view["gaps"]
        self.assertEqual(gap["machine"], "crate")
        self.assertTrue(gap["text"].startswith("not reached: ssh: connect to host crate"), gap)
        self.assertEqual(view["readLine"], "Read from anvil and bench. Not reached: crate.")

    def test_the_header_says_when_the_machines_were_read(self):
        text = self.recap()
        until = datetime.datetime.fromisoformat(json.loads(text)["until"]).astimezone(
            datetime.timezone.utc)
        now = until.timestamp()
        self.assertEqual(self.model(text, now)["view"]["header"], f"Read at {until:%H:%M}")
        self.assertEqual(self.model(text, now + 24 * 3600)["view"]["header"],
                         f"Read {until:%a %H:%M}")

    def test_text_from_machines_loses_control_characters_and_stays_literal(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "\x1b]0;retitled\x07<b>Bold</b> \x1b[31mred")
        [p] = self.view()["attention"]
        self.assertTrue(p["commits"][0].endswith(": ]0;retitled<b>Bold</b> [31mred"),
                        p["commits"][0])

    def test_json_it_cannot_read_is_refused_with_a_reason(self):
        self.assertEqual(self.model("git-fleetlog: oops")["error"], "git-fleetlog gave no JSON")
        newer = json.loads(self.recap())
        newer["schema"] = 2
        self.assertIn("schema 2", self.model(json.dumps(newer))["error"])
        status = json.loads(self.recap())
        status["kind"] = "status"
        self.assertEqual(self.model(json.dumps(status))["error"],
                         "git-fleetlog gave JSON this panel does not read")


def notes_path(test: PanelTest, machine: str) -> str:
    return str(test.fleet.home(machine) / "Projects" / "notes")
