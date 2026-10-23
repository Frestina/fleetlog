import json
import unittest

from fleetlog import collect, recap
from tests.fleet import OTHER, WORK, FleetTest

ALL = (0, 2_000_000_000)


class RecapTest(FleetTest):
    def build(self):
        cfg = self.fleet.load()
        facts = collect.collect_all(cfg, *ALL)
        return facts, recap.build(facts, cfg.identities, *ALL, cfg.exclude)

    def test_a_repo_on_two_machines_is_one_project_with_each_commit_once(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        bare = self.fleet.remote(repo)
        other = self.fleet.clone(bare, "bench", "Code/renamed")
        self.fleet.config("[folders]\nall = ~/Projects ~/Code\n")
        self.fleet.commit(other, "Made on bench")
        _, projects = self.build()
        [p] = projects
        self.assertEqual(p.name, "tool")
        self.assertEqual(p.account, "personal")
        self.assertEqual([(c["subject"], c["made_on"]) for c in p.commits],
                         [("Made on bench", ["bench"]), ("First", ["anvil"])])
        self.assertEqual([e["kind"] for e in p.left], ["unpushed"])
        self.assertEqual(p.left[0]["machine"], "bench")
        self.assertEqual(p.clean_on, ["anvil"])

    def test_only_the_authors_commits_count(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "Mine")
        self.fleet.commit(repo, "Work", email=WORK)
        self.fleet.commit(repo, "Theirs", email=OTHER)
        _, [p] = self.build()
        self.assertEqual({c["subject"]: c["account"] for c in p.commits},
                         {"Mine": "personal", "Work": "work"})

    def test_left_off(self):
        local = self.fleet.repo("anvil", "Projects/local")
        self.fleet.commit(local, "Only here")
        repo = self.fleet.repo("bench", "Projects/tool")
        self.fleet.commit(repo, "First")
        bare = self.fleet.remote(repo)
        behind = self.fleet.clone(bare, "crate", "Projects/tool")
        self.fleet.commit(repo, "Ahead")
        self.fleet.git(repo, "push", "-q")
        self.fleet.git(behind, "fetch", "-q")
        (behind / "f0").write_text("edited\n")
        _, projects = self.build()
        by = {p.name: p for p in projects}
        self.assertEqual([e["kind"] for e in by["local"].left], ["no-remote"])
        kinds = {(e["machine"], e["kind"]) for e in by["tool"].left}
        self.assertEqual(kinds, {("crate", "behind"), ("crate", "uncommitted")})
        self.assertEqual(by["tool"].clean_on, ["bench"])

    def test_exclude(self):
        self.fleet.repo("anvil", "Projects/keep")
        self.fleet.repo("anvil", "Projects/scratch/thing")
        self.fleet.config("[exclude]\nrepos = ~/Projects/scratch\n")
        _, projects = self.build()
        self.assertEqual([p.name for p in projects], ["keep"])

    def test_markdown(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "Fix the \x1b]0;evil\x07 title")
        self.fleet.repo("bench", "Projects/idle")
        self.fleet.unreachable("crate")
        facts, projects = self.build()
        text = recap.markdown(facts, projects, *ALL)
        self.assertIn("## tool (personal), 1 commit", text)
        self.assertIn("anvil: Fix the ]0;evil title", text)
        self.assertNotIn("\x1b", text)
        self.assertIn("Left off:\n- anvil: no remote", text)
        self.assertIn("## Also left off", text)
        self.assertIn("Not reached: crate.", text)
        self.assertIn("## Not reached\n\n- crate: ssh: connect", text)

    def test_status_lists_tidy_projects_with_the_machines_read(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        bare = self.fleet.remote(repo)
        self.fleet.clone(bare, "bench", "Projects/tool")
        facts, projects = self.build()
        text = recap.markdown(facts, projects, *ALL, status=True)
        self.assertIn("## All pushed and committed\n\n- tool (personal): anvil and bench", text)

    def test_json(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        facts, projects = self.build()
        data = json.loads(recap.as_json(facts, projects, *ALL))
        self.assertEqual(data["schema"], recap.SCHEMA)
        [p] = data["projects"]
        self.assertEqual(p["commits"][0]["subject"], "First")
        self.assertEqual(p["left_off"][0]["kind"], "no-remote")
        self.assertTrue(all(m["reached"] for m in data["machines"]))


if __name__ == "__main__":
    unittest.main()
