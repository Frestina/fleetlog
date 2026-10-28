import datetime
import os
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

from fleetlog import notify, timers, weekly
from tests.fleet import FleetTest


def quiet(fn, *args):
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        return fn(*args)


class NotifyTest(FleetTest):
    def setUp(self):
        super().setUp()
        repo = self.fleet.repo("anvil", "Projects/tool")
        self.fleet.commit(repo, "First", when=int(time.time()) - 60)
        self.cfg = self.fleet.load()
        quiet(weekly.weekly, self.cfg)

    def run_notify(self, how="ok"):
        with mock.patch.dict(os.environ, {"FL_NOTIFY": how}):
            return quiet(notify.run, self.cfg)

    def test_shown_once(self):
        self.assertEqual(self.run_notify(), 0)
        [call] = self.fleet.calls("notify-send")
        self.assertIn("Your week: 1 commit in 1 project", call)
        self.assertIn("--urgency=critical", call)
        self.assertIn("tool: 1, work left", call[-1])
        self.assertEqual(self.run_notify(), 0)
        self.assertEqual(len(self.fleet.calls("notify-send")), 1)
        self.assertEqual(self.fleet.calls("xdg-terminal-exec"), [])

    def test_not_marked_shown_when_it_did_not_go_up(self):
        self.assertEqual(self.run_notify("fail"), 1)
        self.assertEqual(self.run_notify(), 0)
        self.assertEqual(len(self.fleet.calls("notify-send")), 2)

    def test_marked_shown_while_it_is_up(self):
        with mock.patch.object(notify, "UP", 0.5):
            self.assertEqual(self.run_notify("slow"), 0)
        self.assertEqual(notify._read(notify.SHOWN), weekly.window_id(weekly.load_local()))

    def test_a_click_opens_the_recap_outside_the_service(self):
        self.assertEqual(self.run_notify("open"), 0)
        [call] = self.fleet.calls("systemd-run")
        copy = str(weekly.state_file(notify.COPY))
        self.assertEqual(call[-4:], ["xdg-terminal-exec", "less", "--", copy])
        with open(copy) as f:
            self.assertIn("## tool", f.read())

    def test_an_old_recap_is_not_shown(self):
        data = weekly.load_local()
        data["until"] -= notify.SHOW_FOR + 60
        weekly.save(data)
        self.assertEqual(self.run_notify(), 0)
        self.assertEqual(self.fleet.calls("notify-send"), [])

    def remote_main(self):
        self.fleet.config('[main]\nmachine = "bench"\n')
        self.cfg = self.fleet.load()

    def test_unreachable_main_machine_is_said_once_a_day(self):
        self.remote_main()
        self.fleet.unreachable("bench")
        self.assertEqual(self.run_notify(), 1)
        self.assertEqual(self.run_notify(), 1)
        [call] = self.fleet.calls("notify-send")
        self.assertIn("git-fleetlog: no weekly recap", call)

    def test_nothing_is_said_while_this_machine_is_offline(self):
        self.remote_main()
        self.fleet.offline()
        self.assertEqual(self.run_notify(), 1)
        self.assertEqual(self.fleet.calls("notify-send"), [])
        self.assertIsNone(notify._read(notify.SAID))

    def test_main_machine_is_not_asked_once_the_due_recap_was_shown(self):
        self.assertEqual(self.run_notify(), 0)
        self.remote_main()
        self.fleet.unreachable("bench")
        self.fleet.clear_calls()
        self.assertEqual(self.run_notify(), 0)
        self.assertEqual(self.fleet.calls("ssh"), [])
        self.assertEqual(self.fleet.calls("notify-send"), [])

    def test_main_machine_is_asked_when_a_newer_recap_is_due(self):
        due = timers.last_weekly(time.time())
        notify._write(notify.SHOWN, str(due - 60))
        self.remote_main()
        self.fleet.unreachable("bench")
        self.fleet.clear_calls()
        self.assertEqual(self.run_notify(), 1)
        self.assertEqual(len(self.fleet.calls("ssh")), 1)


class LastWeeklyTest(unittest.TestCase):
    def due(self, *when):
        return datetime.datetime.fromtimestamp(
            timers.last_weekly(datetime.datetime(*when).timestamp()))

    def test_the_latest_friday_at_15_15(self):
        # Fri Oct 23 2026 15:15
        friday = datetime.datetime(2026, 10, 23, 15, 15)
        self.assertEqual(self.due(2026, 10, 27, 11, 9), friday)  # Tuesday
        self.assertEqual(self.due(2026, 10, 25, 15, 30), friday)  # Sunday
        self.assertEqual(self.due(2026, 10, 23, 15, 15), friday)
        self.assertEqual(self.due(2026, 10, 30, 15, 14), friday)
        self.assertEqual(self.due(2026, 10, 30, 15, 50), datetime.datetime(2026, 10, 30, 15, 15))

    def test_matches_the_timer(self):
        self.assertIn("OnCalendar=Fri *-*-* 15:15:00", timers.MAIN[0].schedule)


if __name__ == "__main__":
    unittest.main()
