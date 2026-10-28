import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from fleetlog import config, weekly
from tests.fleet import FleetTest


def quiet(fn, *args):
    with redirect_stdout(StringIO()):
        return fn(*args)


class WeeklyTest(FleetTest):
    def stored(self) -> dict:
        return json.loads((config.state_dir() / weekly.LATEST).read_text())

    def test_weekly_stores_every_machine(self):
        self.fleet.repo("bench", "Projects/tool")
        self.fleet.unreachable("crate")
        self.assertEqual(quiet(weekly.weekly, self.fleet.load()), 1)
        data = self.stored()
        self.assertEqual(data["until"] - data["since"], weekly.WEEK)
        self.assertEqual([f["reached"] for f in data["facts"]], [True, True, False])
        self.assertEqual(data["facts"][2]["tries"], 1)

    def test_retry_reads_only_what_was_missed_with_the_same_window(self):
        self.fleet.unreachable("crate")
        quiet(weekly.weekly, self.fleet.load())
        before = self.stored()
        self.fleet.clear_calls()
        self.fleet.back("crate")
        self.assertEqual(quiet(weekly.retry, self.fleet.load()), 0)
        targets = [c[c.index("--") + 1] for c in self.fleet.calls()]
        self.assertEqual(targets, ["crate"])
        after = self.stored()
        self.assertEqual((after["since"], after["until"]), (before["since"], before["until"]))
        self.assertTrue(after["facts"][2]["reached"])
        self.assertEqual(after["facts"][2]["tries"], 2)

    def test_retry_counts_tries(self):
        self.fleet.unreachable("crate")
        quiet(weekly.weekly, self.fleet.load())
        quiet(weekly.retry, self.fleet.load())
        self.assertEqual(self.stored()["facts"][2]["tries"], 2)

    def test_retry_with_nothing_missed_reads_nothing(self):
        quiet(weekly.weekly, self.fleet.load())
        self.fleet.clear_calls()
        self.assertEqual(quiet(weekly.retry, self.fleet.load()), 0)
        self.assertEqual(self.fleet.calls(), [])

    def test_retry_stops_when_the_recap_is_old(self):
        self.fleet.unreachable("crate")
        quiet(weekly.weekly, self.fleet.load())
        data = self.stored()
        data["until"] -= weekly.RETRY_FOR + 60
        weekly.save(data)
        self.fleet.clear_calls()
        quiet(weekly.retry, self.fleet.load())
        self.assertEqual(self.fleet.calls(), [])

    def test_one_run_at_a_time(self):
        with weekly.locked():
            with self.assertRaises(weekly.Busy):
                weekly.weekly(self.fleet.load())

    def test_fetch_from_the_main_machine_over_one_cat(self):
        self.fleet.config('[main]\nmachine = "bench"\n')
        with self.assertRaisesRegex(weekly.NoRecap, "no weekly recap has been built on bench"):
            weekly.fetch(self.fleet.load())
        data = {"schema": 1, "since": 1, "until": 2, "facts": [{"label": "anvil"}]}
        path = self.fleet.home("bench") / ".local" / "state" / "fleet" / "log" / weekly.LATEST
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data))
        self.fleet.clear_calls()
        self.assertEqual(weekly.fetch(self.fleet.load()), data)
        [call] = self.fleet.calls()
        self.assertEqual(call[-1], weekly.REMOTE)

    def test_fetch_from_an_unreachable_main_machine(self):
        self.fleet.config('[main]\nmachine = "bench"\n')
        self.fleet.unreachable("bench")
        with self.assertRaises(weekly.Unreachable) as caught:
            weekly.fetch(self.fleet.load())
        self.assertNotIsInstance(caught.exception, weekly.Offline)

    def test_fetch_while_this_machine_is_offline(self):
        self.fleet.config('[main]\nmachine = "bench"\n')
        self.fleet.offline()
        with self.assertRaisesRegex(weekly.Offline, "this machine is offline"):
            weekly.fetch(self.fleet.load())

    def test_a_recap_that_does_not_read(self):
        with self.assertRaises(weekly.NoRecap):
            weekly.check(b'{"schema": 1, "since": "x"}', "here")


if __name__ == "__main__":
    unittest.main()
