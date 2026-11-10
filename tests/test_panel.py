"""The panel's model, panel/model.js, on fleetlog's real --json.

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

from fleetlog import cli, timers
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

    def model(self, text: str, now: float | None = None, query: str | None = None) -> dict:
        now = datetime.datetime.now(datetime.timezone.utc).timestamp() if now is None else now
        done = subprocess.run([NODE, str(RUNNER), str(int(now * 1000)),
                               *([] if query is None else [query])], input=text,
                              capture_output=True, text=True, check=True,
                              env={**os.environ, "TZ": "UTC"})
        return json.loads(done.stdout)

    def view(self, query: str | None = None) -> dict:
        out = self.model(self.recap(), query=query)
        self.assertNotIn("error", out)
        return out["view"]

    def test_only_this_machine_until_others_are_listed(self):
        self.assertFalse(self.view()["onlyThisMachine"])
        self.fleet.hosts("anvil local\n")
        self.assertTrue(self.view()["onlyThisMachine"])

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
            "icon": "no-remote", "project": "notes", "machine": "bench",
            "ask": {"machine": "bench", "path": notes_path(self, "bench"),
                    "lines": ["bench: no remote, so none of it is pushed anywhere"]},
            "group": {"machine": "bench", "path": notes_path(self, "bench"),
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
            "anvil: 1 commit ahead of origin/main",
            "anvil: uncommitted changes (1 untracked file)",
            "bench: 1 commit ahead of origin/main",
        ])
        self.assertEqual([line["icon"] for line in p["left"]], ["push", "commit", "push"])
        first, second, third = p["left"]
        self.assertEqual(first["ask"], {"machine": "anvil", "path": str(tool),
                                        "lines": [first["text"], second["text"]]})
        self.assertIsNone(second["ask"])
        self.assertEqual(third["ask"], {"machine": "bench", "path": str(there),
                                        "lines": [third["text"]]})

    def test_every_kind_of_line_has_its_icon(self):
        tool = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(tool, "First")
        bare = self.fleet.remote(tool)
        there = self.fleet.clone(bare, "bench", "Projects/tool")
        late = self.fleet.clone(bare, "crate", "Projects/tool")
        self.fleet.commit(tool, "Pushed")
        self.fleet.git(tool, "push", "-q")
        self.fleet.git(there, "fetch", "-q")
        self.fleet.git(tool, "checkout", "-q", "-b", "idea")
        self.fleet.commit(tool, "An idea", name="idea")
        self.fleet.git(tool, "checkout", "-q", "main")
        (tool / "f0").write_text("put away\n")
        self.fleet.git(tool, "stash", "-q")
        self.fleet.git(late, "push", "-q", "origin", "main:gone")
        self.fleet.git(late, "checkout", "-q", "-b", "gone", "--track", "origin/gone")
        self.fleet.git(late, "push", "-q", "origin", "--delete", "gone")
        self.fleet.git(late, "branch", "-q", "--set-upstream-to", "origin/main", "main")

        [p] = self.view()["attention"]
        self.assertEqual([(line["text"].split(":")[0], line["icon"]) for line in p["left"]],
                         [("anvil", "push"), ("anvil", "stash"), ("bench", "pull"),
                          ("crate", "gone")])
        self.fleet.git(late, "checkout", "-q", "main")
        [p] = self.view()["attention"]
        self.assertEqual([line["icon"] for line in p["left"] if line["text"].startswith("crate")],
                         ["fetch"])
        # A kind from a newer command than this panel: no icon, so a bullet.
        data = json.loads(self.recap())
        data["projects"][0]["left_off"][0]["kind"] = "constructor"
        out = self.model(json.dumps(data))["view"]
        self.assertEqual(out["attention"][0]["left"][0]["icon"], "")

    def test_the_same_lines_by_machine(self):
        tool = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(tool, "First")
        bare = self.fleet.remote(tool)
        there = self.fleet.clone(bare, "bench", "Projects/tool")
        self.fleet.commit(there, "There")
        (there / "draft").write_text("half done\n")
        notes = self.fleet.repo("bench", "Projects/notes")
        self.fleet.commit(notes, "Write it down")
        tidy = self.fleet.repo("crate", "Projects/tidy")
        self.fleet.commit(tidy, "Done")
        self.fleet.remote(tidy)

        view = self.view()
        # Only bench has anything left off: its lines name the project, each
        # project's first has the agent button, and its commits were made there.
        [bench] = view["machines"]
        self.assertEqual((bench["name"], bench["countText"], bench["needs"]),
                         ("bench", "2 commits", True))
        self.assertEqual([(line["text"], line["icon"]) for line in bench["left"]], [
            ("notes: no remote, so none of it is pushed anywhere", "no-remote"),
            ("tool: 1 commit ahead of origin/main", "push"),
            ("tool: uncommitted changes (1 untracked file)", "commit"),
        ])
        first, second, third = bench["left"]
        self.assertEqual(first["ask"]["path"], str(notes))
        self.assertEqual(second["ask"], {"machine": "bench", "path": str(there),
                                         "lines": ["bench: 1 commit ahead of origin/main",
                                                   "bench: uncommitted changes (1 untracked "
                                                   "file)"]})
        self.assertIsNone(third["ask"])
        self.assertEqual([line.split(" ", 2)[2] for line in bench["commits"]],
                         ["notes: Write it down", "tool: There"])
        # Every project with commits, with what needs work marked, not listed.
        self.assertEqual([(p["name"], p["needs"], p["left"]) for p in view["week"]],
                         [("tidy", False, []), ("notes", True, []), ("tool", True, [])])
        self.assertNotIn(bench["key"], [p["key"] for p in view["week"]])

    def test_several_clones_on_a_machine_keep_their_paths_by_machine(self):
        tool = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(tool, "First")
        bare = self.fleet.remote(tool)
        copy = self.fleet.clone(bare, "anvil", "Projects/tool-copy")
        self.fleet.commit(copy, "Only in the copy")
        view = self.view()
        [anvil] = view["machines"]
        self.assertEqual([line["text"] for line in anvil["left"]],
                         [f"{view['attention'][0]['name']} ({copy}): 1 commit ahead of "
                          "origin/main"])

    def filtered(self):
        """tool on anvil (pushed) and bench (a commit and a draft left), notes
        on bench with no remote, and tidy on crate, all pushed."""
        tool = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(tool, "First")
        bare = self.fleet.remote(tool)
        there = self.fleet.clone(bare, "bench", "Projects/tool")
        self.fleet.commit(there, "There")
        (there / "draft").write_text("half done\n")
        (tool / "draft").write_text("half done here too\n")
        notes = self.fleet.repo("bench", "Projects/notes")
        self.fleet.commit(notes, "Write it down")
        tidy = self.fleet.repo("crate", "Projects/tidy")
        self.fleet.commit(tidy, "Done")
        self.fleet.remote(tidy)
        return there

    def shape(self, view):
        return {
            "attention": [(p["name"], [line["text"] for line in p["left"]])
                          for p in view["attention"]],
            "machines": [(m["name"], [line["text"] for line in m["left"]])
                         for m in view["machines"]],
            "worked": [p["name"] for p in view["worked"]],
            "week": [p["name"] for p in view["week"]],
        }

    def test_a_filter_keeps_what_a_project_or_a_machine_names(self):
        self.filtered()
        whole = self.view()
        for nothing in ("", "   "):
            self.assertEqual(self.view(nothing), whole)

        # A project, in any case, in both groupings.
        self.assertEqual(self.shape(self.view("NOTE")), {
            "attention": [("notes", ["bench: no remote, so none of it is pushed anywhere"])],
            "machines": [("bench", ["notes: no remote, so none of it is pushed anywhere"])],
            "worked": [], "week": ["notes"]})
        # A machine: its lines, and the projects that are on it.
        self.assertEqual(self.shape(self.view("anv")), {
            "attention": [("tool", ["anvil: uncommitted changes (1 untracked file)"])],
            "machines": [("anvil", ["tool: uncommitted changes (1 untracked file)"])],
            "worked": [], "week": ["tool"]})
        self.assertEqual(self.shape(self.view("crate")), {
            "attention": [], "machines": [], "worked": ["tidy"], "week": ["tidy"]})
        # Every word has to match: a project on a machine.
        self.assertEqual(self.shape(self.view(" bench  tool ")), {
            "attention": [("tool", ["bench: 1 commit ahead of origin/main",
                                    "bench: uncommitted changes (1 untracked file)"])],
            "machines": [("bench", ["tool: 1 commit ahead of origin/main",
                                    "tool: uncommitted changes (1 untracked file)"])],
            "worked": [], "week": ["tool"]})
        self.assertEqual(self.shape(self.view("nowhere")), {
            "attention": [], "machines": [], "worked": [], "week": []})

    def test_a_filter_keeps_the_counts_the_gaps_and_an_agent_button(self):
        there = self.filtered()
        self.fleet.unreachable("crate")
        whole, view = self.view(), self.view("tool")
        for key in ("attentionCount", "gaps", "readLine", "header", "quiet"):
            self.assertEqual(view[key], whole[key], key)
        self.assertEqual(len(view["gaps"]), 1)
        # bench's row lists only tool's commits, and counts all it made.
        [anvil, bench] = view["machines"]
        self.assertEqual([line.split(" ", 2)[2] for line in bench["commits"]], ["tool: There"])
        self.assertEqual(bench["countText"], "2 commits")
        # The first line that is left has the button, for the whole group.
        only = self.view("bench tool")["attention"][0]["left"]
        self.assertEqual([line["ask"] is not None for line in only], [True, False])
        self.assertEqual(only[0]["ask"]["path"], str(there))
        anvil_line = self.view("anvil")["attention"][0]["left"]
        self.assertEqual([line["ask"]["machine"] for line in anvil_line], ["anvil"])

    def test_the_grouping_it_starts_with_is_the_configs(self):
        self.assertEqual(self.view()["group"], "machine")
        self.fleet.config('[panel]\ngroup = "project"\n')
        self.assertEqual(self.view()["group"], "project")
        # A read from before the setting, or anything else: by machine.
        data = json.loads(self.recap())
        for panel in (None, {}, {"group": "repo"}, "project"):
            data["panel"] = panel
            self.assertEqual(self.model(json.dumps(data))["view"]["group"], "machine")
        del data["panel"]
        self.assertEqual(self.model(json.dumps(data))["view"]["group"], "machine")

    def test_a_machine_not_reached_comes_first_and_is_named(self):
        self.fleet.commit(self.fleet.repo("anvil", "Projects/tool"), "First")
        self.fleet.unreachable("crate")
        view = self.view()
        [gap] = view["gaps"]
        self.assertEqual(gap["machine"], "crate")
        self.assertTrue(gap["text"].startswith("not reached: ssh: connect to host crate"), gap)
        self.assertEqual(view["readLine"], "Read from anvil and bench. Not reached: crate.")

    def test_a_folder_named_for_a_machine_that_is_not_there_is_a_gap(self):
        self.fleet.config('[folders]\nbench = ["~/srv"]\n')
        self.assertEqual(self.view()["gaps"],
                         [{"machine": "bench", "text": "folder not found: ~/srv"}])

    def test_timers_the_config_changed_are_a_gap_on_this_machine(self):
        with contextlib.redirect_stdout(io.StringIO()):
            timers.install("main", self.fleet.load())
        self.fleet.config('[recap]\nwhen = "Mon 08:30"\n')
        self.assertEqual(self.view()["gaps"], [
            {"machine": "anvil", "text": "the weekly timers here are not as [recap] says: "
                                         "run `fleetlog timers install main`"}])

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
        self.assertEqual(self.model("fleetlog: oops")["error"], "fleetlog gave no JSON")
        newer = json.loads(self.recap())
        newer["schema"] = 2
        self.assertIn("schema 2", self.model(json.dumps(newer))["error"])
        status = json.loads(self.recap())
        status["kind"] = "status"
        self.assertEqual(self.model(json.dumps(status))["error"],
                         "fleetlog gave JSON this panel does not read")


def notes_path(test: PanelTest, machine: str) -> str:
    return str(test.fleet.home(machine) / "Projects" / "notes")
