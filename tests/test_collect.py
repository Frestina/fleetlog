import os
import subprocess
import unittest
from unittest import mock

from fleetlog import collect
from tests.fleet import OTHER, FleetTest

ALL = (0, 2_000_000_000)


class CollectTest(FleetTest):
    def test_one_ssh_call_per_machine_and_none_for_the_local_one(self):
        self.fleet.repo("anvil", "Projects/a")
        self.fleet.repo("bench", "Projects/b")
        facts = collect.collect_all(self.fleet.load(), *ALL)
        self.assertEqual([f["label"] for f in facts], ["anvil", "bench", "crate"])
        self.assertTrue(all(f["reached"] and f["complete"] for f in facts))
        calls = self.fleet.calls()
        self.assertEqual(sorted(c[c.index("--") + 1] for c in calls), ["bench", "crate"])

    def test_ssh_never_forwards_the_agent_or_asks(self):
        collect.collect_all(self.fleet.load(), *ALL)
        for call in self.fleet.calls():
            options = call[:call.index("--")]
            for want in ("BatchMode=yes", "ForwardAgent=no", "IdentityAgent=none"):
                self.assertIn(want, options)
            self.assertNotIn("-A", options)

    def test_repo_facts(self):
        repo = self.fleet.repo("bench", "Projects/tool")
        first = self.fleet.commit(repo, "First")
        self.fleet.remote(repo)
        second = self.fleet.commit(repo, "Second")
        self.fleet.commit(repo, "Theirs", email=OTHER)
        self.fleet.git(repo, "checkout", "-q", "-b", "idea")
        self.fleet.commit(repo, "On a branch")
        (repo / "f0").write_text("changed\n")
        (repo / "new").write_text("untracked\n")
        self.fleet.git(repo, "stash", "push", "-q", "--", "f0")
        (repo / "f1").write_text("changed too\n")

        facts = collect.collect_all(self.fleet.load(), *ALL)[1]
        self.assertTrue(facts["complete"], facts["error"])
        [r] = facts["repos"]
        self.assertEqual(r["path"], str(repo))
        self.assertEqual(r["root"], first)
        self.assertEqual(r["remotes"], 1)
        self.assertEqual(r["head"], "idea")
        self.assertIsNotNone(r["synced"])
        branches = {b["name"]: b for b in r["branches"]}
        self.assertEqual(branches["main"]["upstream"], "origin/main")
        self.assertEqual(branches["main"]["unpushed"], 2)
        self.assertEqual(branches["main"]["track"], "ahead 2")
        self.assertIsNone(branches["idea"]["upstream"])
        self.assertEqual(branches["idea"]["unpushed"], 3)
        self.assertEqual({c["subject"] for c in r["commits"]},
                         {"First", "Second", "Theirs", "On a branch"})
        self.assertIn(second, r["made"])
        self.assertEqual((r["changed"], r["untracked"], r["stashes"]), (1, 1, 1))

    def test_a_cloned_commit_was_not_made_there(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        made = self.fleet.commit(repo, "First")
        bare = self.fleet.remote(repo)
        self.fleet.clone(bare, "bench", "Projects/tool")
        anvil, bench = collect.collect_all(self.fleet.load(), *ALL)[:2]
        self.assertEqual(anvil["repos"][0]["made"], [made])
        self.assertEqual(bench["repos"][0]["made"], [])

    def test_a_rebased_commit_was_made_there(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        bare = self.fleet.remote(repo)
        other = self.fleet.clone(bare, "bench", "Projects/tool")
        self.fleet.commit(repo, "Elsewhere")
        self.fleet.git(repo, "push", "-q")
        self.fleet.commit(other, "Rebased", name="rebased")
        self.fleet.git(other, "fetch", "-q")
        self.fleet.git(other, "rebase", "-q", "origin/main")
        self.fleet.git(other, "push", "-q")
        self.fleet.git(repo, "pull", "-q")
        self.fleet.commit(repo, "Elsewhere too")
        self.fleet.git(repo, "push", "-q")
        self.fleet.commit(other, "Pulled with rebase", name="pulled")
        self.fleet.git(other, "pull", "-q", "--rebase")
        [r] = collect.collect_all(self.fleet.load(), *ALL)[1]["repos"]
        made = {c["subject"] for c in r["commits"] if c["hash"] in r["made"]}
        self.assertEqual(made, {"Rebased", "Pulled with rebase"})

    def test_a_fast_forward_made_nothing_there(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        bare = self.fleet.remote(repo)
        other = self.fleet.clone(bare, "bench", "Projects/tool")
        self.fleet.commit(repo, "Merged in")
        self.fleet.git(repo, "push", "-q")
        self.fleet.git(other, "fetch", "-q")
        self.fleet.git(other, "merge", "-q", "origin/main")
        self.fleet.commit(repo, "Rebased onto")
        self.fleet.git(repo, "push", "-q")
        self.fleet.git(other, "fetch", "-q")
        self.fleet.git(other, "rebase", "-q", "origin/main")
        bench = collect.collect_all(self.fleet.load(), *ALL)[1]
        self.assertEqual(bench["repos"][0]["made"], [])

    def test_which_reflog_lines_say_a_commit_was_made_there(self):
        for subject, made in [
            ("commit: Draw beds", True),
            ("commit (initial): First", True),
            ("commit (amend): Draw beds", True),
            ("cherry-pick: Draw beds", True),
            ("revert: Revert \"Draw beds\"", True),
            ("am: Draw beds", True),
            ("rebase (pick): Draw beds", True),
            ("rebase -i (pick): Draw beds", True),
            ("rebase (reword): Draw beds", True),
            ("rebase (continue): Draw beds", True),
            ("pull --rebase (pick): Draw beds", True),
            ("pull -q --rebase (pick): Draw beds", True),
            ("merge idea: Fast-forward", False),
            ("merge origin/main: Fast-forward", False),
            ("rebase (start): checkout origin/main", False),
            ("rebase (finish): returning to refs/heads/main", False),
            ("pull --rebase (finish): returning to refs/heads/main", False),
            ("pull: Fast-forward", False),
            ("checkout: moving from main to idea", False),
            ("reset: moving to HEAD~1", False),
            ("clone: from example.org:tool.git", False),
        ]:
            with self.subTest(subject):
                self.assertEqual(bool(collect.MADE.match(subject)), made)

    def test_reading_never_writes_the_index(self):
        repo = self.fleet.repo("bench", "Projects/tool")
        self.fleet.commit(repo, "First")
        os.utime(repo / "f0", (1, 1))  # stat data no longer matches the index
        index = repo / ".git" / "index"
        before = (index.read_bytes(), index.stat().st_mtime_ns)
        collect.collect_all(self.fleet.load(), *ALL)
        self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), before)
        self.assertFalse((repo / ".git" / "FETCH_HEAD").exists())

    def test_window(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "Old", when=1_000)
        self.fleet.commit(repo, "New", when=5_000)
        facts = collect.collect_all(self.fleet.load(), 4_000, 6_000)[0]
        self.assertEqual([c["subject"] for c in facts["repos"][0]["commits"]], ["New"])

    def test_folders_from_the_config_and_missing_ones(self):
        self.fleet.repo("bench", "Projects/a")
        self.fleet.repo("bench", "srv/b")
        self.fleet.config("[folders]\nbench = ~/srv\n")
        facts = collect.collect_all(self.fleet.load(), *ALL)
        self.assertEqual(sorted(os.path.basename(r["path"]) for r in facts[1]["repos"]),
                         ["a", "b"])
        self.assertIn(str(self.fleet.home("crate") / "dotfiles"), facts[2]["missing"])

    def test_overlapping_folders_read_a_repo_once(self):
        self.fleet.repo("anvil", "Projects/Personal/a")
        self.fleet.config("[folders]\nall = ~/Projects ~/Projects/Personal\n")
        facts = collect.collect_all(self.fleet.load(), *ALL)[0]
        self.assertEqual(len(facts["repos"]), 1)

    def test_machines_from_the_config_alone(self):
        (self.fleet.home("anvil") / ".config" / "fleetwatch" / "hosts").unlink()
        self.fleet.config("[machines]\nbench = bench\nhere = local  # this one\n")
        cfg = self.fleet.load()
        self.assertEqual([(m.label, m.local) for m in cfg.machines],
                         [("bench", False), ("here", True)])
        self.fleet.repo("anvil", "Projects/a")
        facts = collect.collect_all(cfg, *ALL)
        self.assertEqual([len(f["repos"]) for f in facts], [0, 1])
        self.assertEqual(len(self.fleet.calls()), 1)

    def test_unreachable(self):
        self.fleet.unreachable("crate")
        facts = collect.collect_all(self.fleet.load(), *ALL)[2]
        self.assertFalse(facts["reached"])
        self.assertIn("No route to host", facts["error"])

    def test_cut_off_output_is_not_complete(self):
        out = collect.SCRIPT.read_bytes()
        done = subprocess.run(["bash", "-s", "--", "0", "1", "~/Projects"], input=out,
                              capture_output=True, check=True)
        cut = done.stdout.replace(b"E\n", b"")
        facts = collect.parse("x", cut)
        self.assertTrue(facts["reached"])
        self.assertFalse(facts["complete"])

    def test_timeout_keeps_what_was_read(self):
        with mock.patch.object(collect, "TIMEOUT", 0.001):
            facts = collect.collect_all(self.fleet.load(), *ALL)[1]
        self.assertFalse(facts["complete"])
        self.assertTrue(facts["error"])


if __name__ == "__main__":
    unittest.main()
