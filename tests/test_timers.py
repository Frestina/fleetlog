import argparse
import unittest
from contextlib import redirect_stdout
from io import StringIO

from fleetlog import cli, config, timers
from fleetlog.config import WHEN
from tests.fleet import FleetTest


def quiet(fn, *args):
    with redirect_stdout(StringIO()) as out:
        result = fn(*args)
    return result, out.getvalue()


class TimersTest(FleetTest):
    def test_main_services_run_at_the_lowest_priority(self):
        for name, text in timers.units(timers.timers("main", WHEN)).items():
            if name.endswith(".service"):
                for want in ("Nice=19", "CPUSchedulingPolicy=idle", "IOSchedulingClass=idle",
                             "MemoryMax=", "TimeoutStartSec="):
                    self.assertIn(want, text)

    def test_install_main_and_remove(self):
        rc, out = quiet(timers.install, "main", self.fleet.load())
        self.assertEqual(rc, 0)
        files = sorted(p.name for p in timers.unit_dir().iterdir())
        self.assertEqual(files, ["fleetlog-retry.service", "fleetlog-retry.timer",
                                 "fleetlog-weekly.service", "fleetlog-weekly.timer"])
        calls = [c[1:] for c in self.fleet.calls("systemctl")]
        self.assertIn(["daemon-reload"], calls)
        self.assertIn(["enable", "--now", "fleetlog-weekly.timer",
                       "fleetlog-retry.timer"], calls)
        self.assertNotIn("enable-linger", str(self.fleet.calls("loginctl")))
        quiet(timers.remove)
        self.assertEqual(list(timers.unit_dir().iterdir()), [])

    def test_install_refuses_to_overwrite_a_unit_it_did_not_write(self):
        timers.unit_dir().mkdir(parents=True)
        (timers.unit_dir() / "fleetlog-notify.timer").write_text("[Timer]\n")
        with self.assertRaises(timers.TimersError):
            timers.install("viewer", self.fleet.load())
        quiet(timers.remove)
        self.assertTrue((timers.unit_dir() / "fleetlog-notify.timer").exists())

    def test_the_schedules_keep_off_fleet_doctors_minutes(self):
        fleetdoctor = {0} | set(range(2, 60, 5))
        self.assertEqual(config.DOCTOR, fleetdoctor)
        for when in (WHEN, (0, 8, 30), (6, 23, 59)):
            for t in timers.timers("main", when) + timers.timers("viewer", when):
                for line in t.schedule:
                    if line.startswith("OnCalendar="):
                        minute = int(line.rsplit(":", 2)[-2])
                        self.assertNotIn(minute, fleetdoctor, line)


class RecapTimersTest(FleetTest):
    def install(self, role: str) -> str:
        rc, out = quiet(timers.install, role, self.fleet.load())
        self.assertEqual(rc, 0)
        return out

    def drift(self) -> list[str]:
        return timers.drift(self.fleet.load())

    def test_the_default_schedules_are_the_ones_before_the_setting(self):
        main, viewer = timers.timers("main", WHEN), timers.timers("viewer", WHEN)
        self.assertEqual([t.schedule for t in main + viewer], [
            ("OnCalendar=Fri *-*-* 15:15:00", "Persistent=true"),
            ("OnCalendar=Fri *-*-* 16..23:45:00", "OnCalendar=Sat,Sun *-*-* *:45:00"),
            ("OnCalendar=Fri..Sun *-*-* *:50:00",)])

    def test_another_time_and_days_past_sunday(self):
        self.fleet.config('[recap]\nwhen = "Sun 23:10"\n')
        self.assertIn("OnCalendar=Sun *-*-* 23:10:00", self.install("main"))
        text = (timers.unit_dir() / "fleetlog-retry.timer").read_text()
        self.assertIn("OnCalendar=Mon,Tue *-*-* *:45:00\n", text)
        self.assertNotIn("Sun *-*-* 24", text)
        self.install("viewer")
        self.assertIn("OnCalendar=Sun,Mon,Tue *-*-* *:50:00\n",
                      (timers.unit_dir() / "fleetlog-notify.timer").read_text())
        self.assertEqual(self.drift(), [])

    def test_a_changed_time_says_to_install_again(self):
        self.install("main")
        self.install("viewer")
        self.fleet.config('[recap]\nwhen = "Mon 08:30"\n')
        self.assertEqual(self.drift(), [
            "the weekly timers here are not as [recap] says: run `fleetlog timers install main`",
            "the notification timers here are not as [recap] says: run "
            "`fleetlog timers install viewer`"])
        self.fleet.clear_calls()
        rc, out = quiet(timers.status, self.fleet.load())
        self.assertEqual(rc, 1)
        self.assertIn("note: the weekly timers here are not as [recap] says", out)
        self.install("main")
        self.install("viewer")
        self.assertEqual(self.drift(), [])
        rc, _ = quiet(timers.status, self.fleet.load())
        self.assertEqual(rc, 0)

    def test_off_installs_nothing_and_says_to_remove_what_is_there(self):
        self.install("main")
        self.fleet.config('[recap]\nwhen = "off"\n')
        with self.assertRaisesRegex(timers.TimersError, "the weekly recap is off"):
            timers.install("viewer", self.fleet.load())
        self.assertEqual(self.drift(), [
            'the weekly recap is off ([recap] when = "off"), but its timers are still here: '
            "`fleetlog timers remove` removes them"])
        quiet(timers.remove)
        self.assertEqual(self.drift(), [])

    def test_a_viewer_not_in_notify(self):
        self.fleet.config('[recap]\nnotify = ["bench"]\n')
        with self.assertRaisesRegex(timers.TimersError, "anvil is not in \\[recap\\] notify"):
            timers.install("viewer", self.fleet.load())
        self.assertEqual(timers.installed(), [])
        self.fleet.config("")
        self.install("viewer")
        self.fleet.config('[recap]\nnotify = ["bench"]\n')
        self.assertEqual(self.drift(), [
            "anvil is not in [recap] notify, so its notification timer shows nothing: "
            "`fleetlog timers remove` removes it"])

    def test_a_viewer_in_notify_without_the_timer(self):
        self.fleet.config('[recap]\nnotify = ["anvil"]\n')
        self.assertEqual(self.drift(), [
            "anvil is in [recap] notify but has no notification timer: run "
            "`fleetlog timers install viewer`"])
        self.fleet.config("")
        self.assertEqual(self.drift(), [])  # "all" asks no machine to install it


class SinceTest(unittest.TestCase):
    def test_since(self):
        self.assertGreater(cli.since("2d"), cli.since("1w"))
        self.assertEqual(cli.since("2026-10-01"), cli.since("2026-10-01"))
        with self.assertRaises(argparse.ArgumentTypeError):
            cli.since("last friday")


if __name__ == "__main__":
    unittest.main()
