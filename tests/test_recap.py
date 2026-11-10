import json
import unittest

from fleetlog import collect, recap
from tests.fleet import OTHER, WORK, FleetTest

ALL = (0, 2_000_000_000)


class RecapTest(FleetTest):
    def build(self):
        cfg = self.fleet.load()
        facts = collect.collect_all(cfg, *ALL)
        return facts, recap.build(facts, cfg.identities, *ALL, cfg.exclude,
                                   cfg.exclude_projects)

    def test_a_repo_on_two_machines_is_one_project_with_each_commit_once(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        bare = self.fleet.remote(repo)
        other = self.fleet.clone(bare, "bench", "Code/renamed")
        self.fleet.config('[folders]\nall = ["~/Projects", "~/Code"]\n')
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

    def pushed_past(self, *subjects, where="bench"):
        """A project on anvil and on `where`, and then commits pushed from
        anvil that the other never fetched."""
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        bare = self.fleet.remote(repo)
        other = self.fleet.clone(bare, where, "Projects/tool-copy" if where == "anvil"
                                 else "Projects/tool")
        for subject in subjects:
            self.fleet.commit(repo, subject)
        self.fleet.git(repo, "push", "-q")
        return repo, other

    def not_fetched(self, projects):
        return [e for p in projects for e in p.left if e["kind"] == "not-fetched"]

    def test_what_another_machine_fetched_and_this_one_did_not(self):
        repo, other = self.pushed_past("Second", "Third")
        facts, [p] = self.build()
        [e] = p.left
        self.assertEqual(e["text"], "bench: 2 commits behind origin/main")
        # Which machine has them, and when it last heard, are in the JSON.
        self.assertEqual({k: e[k] for k in ("machine", "kind", "path", "branch", "upstream",
                                            "count", "not_fetched", "at_least", "has",
                                            "as_of")},
                         {"machine": "bench", "kind": "not-fetched", "path": str(other),
                          "branch": "main", "upstream": "origin/main", "count": 2,
                          "not_fetched": 2, "at_least": False, "has": "anvil",
                          "as_of": recap._stamp(facts[0]["repos"][0]["synced"])})
        self.assertEqual(p.clean_on, ["anvil"])
        self.assertIn("Left off:\n- bench: 2 commits behind origin/main\n",
                      recap.markdown(facts, projects=[p], since=ALL[0], until=ALL[1]))
        # Once it fetches, it is behind its own upstream, which it says itself.
        self.fleet.git(other, "fetch", "-q")
        facts, [p] = self.build()
        day = recap._day(facts[1]["repos"][0]["synced"])
        self.assertEqual([(e["kind"], e["text"]) for e in p.left],
                         [("behind", f"bench: 2 commits behind origin/main, as of {day}")])

    def test_behind_its_upstream_and_not_fetched_is_one_line(self):
        repo, other = self.pushed_past("Second", "Third")
        self.fleet.git(other, "fetch", "-q")
        self.fleet.commit(repo, "Fourth")
        self.fleet.git(repo, "push", "-q")
        _, [p] = self.build()
        self.assertEqual([(e["kind"], e["count"], e["not_fetched"], e["text"]) for e in p.left],
                         [("not-fetched", 3, 1, "bench: 3 commits behind origin/main")])

    def test_a_branch_is_named_when_it_is_not_its_upstreams_namesake(self):
        repo, other = self.pushed_past("Second")
        self.fleet.git(other, "checkout", "-q", "-b", "fix", "--track", "origin/main")
        self.fleet.git(other, "branch", "-q", "-D", "main")
        self.fleet.commit(other, "A fix")
        _, [p] = self.build()
        self.assertEqual([e["text"] for e in p.left],
                         ["bench: fix is 1 commit ahead of origin/main",
                          "bench: fix is 1 commit behind origin/main"])

    def test_commits_on_a_branch_whose_upstream_is_gone(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        self.fleet.remote(repo)
        self.fleet.git(repo, "checkout", "-q", "-b", "idea")
        self.fleet.commit(repo, "An idea")
        self.fleet.git(repo, "push", "-q", "-u", "origin", "idea")
        self.fleet.commit(repo, "More of it")
        self.fleet.git(repo, "push", "-q", "origin", "--delete", "idea")
        _, [p] = self.build()
        self.assertEqual([e["text"] for e in p.left],
                         ["anvil: 2 commits on idea on no remote",
                          "anvil: idea's upstream origin/idea is gone"])

    def test_not_fetched_never_fetches(self):
        _, other = self.pushed_past("Second")
        before = self.fleet.git(other, "rev-parse", "origin/main")
        _, projects = self.build()
        self.assertEqual(len(self.not_fetched(projects)), 1)
        self.assertEqual(self.fleet.git(other, "rev-parse", "origin/main"), before)
        self.assertFalse((other / ".git" / "FETCH_HEAD").exists())

    def test_not_fetched_counts_a_merge_and_what_it_brought(self):
        repo, _ = self.pushed_past()
        self.fleet.git(repo, "checkout", "-q", "-b", "side")
        self.fleet.commit(repo, "On the side", name="side")
        self.fleet.git(repo, "checkout", "-q", "main")
        self.fleet.commit(repo, "On main")
        self.fleet.git(repo, "merge", "-q", "--no-ff", "-m", "Merge side", "side")
        self.fleet.git(repo, "push", "-q")
        _, projects = self.build()
        [e] = self.not_fetched(projects)
        self.assertEqual((e["machine"], e["count"], e["at_least"]), ("bench", 3, False))

    def test_not_fetched_names_the_machine_furthest_on(self):
        repo, _ = self.pushed_past("Second")
        bare = self.fleet.git(repo, "remote", "get-url", "origin")
        self.fleet.clone(bare, "crate", "Projects/tool")
        self.fleet.commit(repo, "Third")
        self.fleet.git(repo, "push", "-q")
        _, projects = self.build()
        self.assertEqual([(e["machine"], e["count"], e["has"]) for e in
                          self.not_fetched(projects)],
                         [("bench", 2, "anvil"), ("crate", 1, "anvil")])

    def test_not_fetched_between_two_clones_on_one_machine(self):
        repo, other = self.pushed_past("Second", where="anvil")
        _, projects = self.build()
        [e] = self.not_fetched(projects)
        self.assertEqual(e["text"], f"anvil ({other}): 1 commit behind origin/main")
        self.assertEqual(e["has"], str(repo))

    def test_not_fetched_is_about_the_same_remote_under_any_url(self):
        repo, other = self.pushed_past("Second")
        bare = self.fleet.git(repo, "remote", "get-url", "origin")
        fork = self.fleet.clone(bare, "crate", "Projects/tool")
        self.fleet.git(fork, "reset", "-q", "--hard", "HEAD~1")
        self.fleet.git(fork, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.fleet.git(repo, "remote", "set-url", "origin", "https://example.org/Owner/Tool")
        self.fleet.git(other, "remote", "rename", "origin", "forge")
        self.fleet.git(other, "remote", "set-url", "forge", "git@forge-alias:owner/tool.git")
        self.fleet.git(fork, "remote", "set-url", "origin", "git@forge-alias:someone/tool.git")
        _, projects = self.build()
        self.assertEqual([(e["machine"], e["upstream"]) for e in self.not_fetched(projects)],
                         [("bench", "forge/main")])

    def test_not_fetched_is_said_for_the_checked_out_branch_only(self):
        repo, other = self.pushed_past("Second")
        self.fleet.git(other, "checkout", "-q", "-b", "idea")
        _, projects = self.build()
        self.assertEqual(self.not_fetched(projects), [])

    def test_a_rewritten_upstream_is_said_where_it_is_older(self):
        repo, other = self.pushed_past("Second")
        self.fleet.git(other, "fetch", "-q")
        self.fleet.git(repo, "commit", "-q", "--amend", "-m", "Second, again")
        self.fleet.git(repo, "push", "-q", "--force")
        _, projects = self.build()
        [e] = self.not_fetched(projects)
        self.assertEqual(e["text"], "bench: origin/main is not where anvil has it, too far "
                                    "apart to count or rewritten")
        self.assertEqual((e["count"], e["at_least"], e["has"]), (None, False, "anvil"))

    def test_not_fetched_beyond_the_history_that_was_sent(self):
        repo, _ = self.pushed_past()
        self.fleet.git(repo, "checkout", "-q", "-b", "side")
        self.fleet.commit(repo, "On the side", name="side")
        self.fleet.git(repo, "checkout", "-q", "main")
        self.fleet.commit(repo, "On main")
        self.fleet.git(repo, "merge", "-q", "--no-ff", "-m", "Merge side", "side")
        self.fleet.git(repo, "push", "-q")
        side = self.fleet.git(repo, "rev-parse", "side")
        first = self.fleet.git(repo, "rev-parse", "HEAD~2")
        facts, _ = self.build()
        identities = self.fleet.load().identities
        # As if the side branch were older than the commits sent: it is in the
        # merge's parents, and its own are not known.
        for f in facts:
            for r in f["repos"]:
                r["history"].pop(side, None)
        [e] = self.not_fetched(recap.build(facts, identities, *ALL))
        self.assertEqual((e["count"], e["at_least"]), (2, True))
        self.assertEqual(e["text"], "bench: at least 2 commits behind origin/main")
        # As if bench's commit were: nothing joins the two.
        for f in facts:
            for r in f["repos"]:
                r["history"] = {h: [p for p in ps if p != first]
                                for h, ps in r["history"].items() if h != first}
        [e] = self.not_fetched(recap.build(facts, identities, *ALL))
        self.assertEqual((e["machine"], e["count"]), ("bench", None))
        self.assertIn("too far apart to count or rewritten", e["text"])

    def test_facts_from_before_upstreams_were_read_say_nothing_of_it(self):
        self.pushed_past("Second")
        facts, _ = self.build()
        for f in facts:
            for r in f["repos"]:
                del r["history"]
                for b in r["branches"]:
                    for key in ("upstream_tip", "upstream_time", "remote_branch", "remote"):
                        del b[key]
        projects = recap.build(facts, self.fleet.load().identities, *ALL)
        self.assertEqual([p.left for p in projects], [[]])

    def test_two_clones_on_one_machine_each_keep_their_branches(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        bare = self.fleet.remote(repo)
        copy = self.fleet.clone(bare, "anvil", "Projects/tool-copy")
        for i in range(3):
            self.fleet.commit(copy, f"Only in the copy {i}")
        _, [p] = self.build()
        copy_path = str(self.fleet.home("anvil") / "Projects/tool-copy")
        self.assertEqual([(e["kind"], e.get("count"), e.get("path")) for e in p.left],
                         [("unpushed", 3, copy_path)])
        self.assertEqual(p.left[0]["text"],
                         f"anvil ({copy_path}): 3 commits ahead of origin/main")
        self.assertEqual(p.clean_on, [])

    def test_worktrees_share_their_branches(self):
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First")
        self.fleet.remote(repo)
        self.fleet.commit(repo, "Not pushed")
        self.fleet.git(repo, "worktree", "add", "-q", "-b", "side",
                       str(self.fleet.home("anvil") / "Projects/tool-side"))
        _, [p] = self.build()
        self.assertEqual([(e["kind"], e.get("branch"), e["text"]) for e in p.left],
                         [("unpushed", "main", "anvil: 1 commit ahead of origin/main"),
                          ("never-pushed", "side", "anvil: branch side was never pushed "
                                                   "(1 commit)")])

    def test_a_folder_named_for_a_machine_that_is_not_there_is_said(self):
        self.fleet.config('[folders]\nbench = ["~/srv"]\n')
        facts, projects = self.build()
        text = recap.markdown(facts, projects, *ALL)
        self.assertIn("## Folders not found\n\n- bench: ~/srv, named for it in [folders]\n",
                      text)
        self.assertEqual(json.loads(recap.as_json(facts, projects, *ALL))["machines"][1]
                         ["folders_not_found"], ["~/srv"])

    def test_exclude(self):
        self.fleet.repo("anvil", "Projects/keep")
        self.fleet.repo("anvil", "Projects/scratch/thing")
        self.fleet.config('[exclude]\nrepos = ["~/Projects/scratch"]\n')
        _, projects = self.build()
        self.assertEqual([p.name for p in projects], ["keep"])

    def test_exclude_by_name(self):
        self.fleet.repo("anvil", "Projects/keep")
        self.fleet.repo("anvil", "Projects/scratch")
        self.fleet.repo("bench", "Projects/old/scratch")
        self.fleet.config('[exclude]\nprojects = ["scratch"]\n')
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
