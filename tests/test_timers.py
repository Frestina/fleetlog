import unittest
from contextlib import redirect_stdout
from io import StringIO

from fleetlog import cli, timers
from tests.fleet import FleetTest


def quiet(fn, *args):
    with redirect_stdout(StringIO()) as out:
        result = fn(*args)
    return result, out.getvalue()


class TimersTest(FleetTest):
    def test_main_services_run_at_the_lowest_priority(self):
        for name, text in timers.units(timers.MAIN).items():
            if name.endswith(".service"):
                for want in ("Nice=19", "CPUSchedulingPolicy=idle", "IOSchedulingClass=idle",
                             "MemoryMax=", "TimeoutStartSec="):
                    self.assertIn(want, text)

    def test_install_main_and_remove(self):
        rc, out = quiet(timers.install, "main")
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
            timers.install("viewer")
        quiet(timers.remove)
        self.assertTrue((timers.unit_dir() / "fleetlog-notify.timer").exists())

    def test_the_schedules_keep_off_fleet_doctors_minutes(self):
        fleetdoctor = {0} | set(range(2, 60, 5))
        for t in timers.ALL:
            for line in t.schedule:
                if line.startswith("OnCalendar="):
                    minute = int(line.rsplit(":", 2)[-2])
                    self.assertNotIn(minute, fleetdoctor, line)


class SinceTest(unittest.TestCase):
    def test_since(self):
        self.assertGreater(cli.since("2d"), cli.since("1w"))
        self.assertEqual(cli.since("2026-10-01"), cli.since("2026-10-01"))
        with self.assertRaises(Exception):
            cli.since("last friday")


if __name__ == "__main__":
    unittest.main()
