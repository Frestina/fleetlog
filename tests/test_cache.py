import contextlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path

from fleetlog import cache, cli
from tests.fleet import FleetTest

COMMAND = Path(__file__).resolve().parent.parent / "bin" / "git-fleetlog"


class CacheTest(FleetTest):
    def run_cli(self, *argv: str) -> tuple[int, dict]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main([*argv, "--json"])
        return code, json.loads(out.getvalue())

    def reads(self) -> int:
        """Reads of every machine so far, by the ssh calls to bench."""
        return sum(1 for c in self.fleet.calls() if c[c.index("--") + 1] == "bench")

    def test_a_read_since_the_given_time_is_reused(self):
        self.fleet.commit(self.fleet.repo("anvil", "Projects/tool"), "First")
        start = int(time.time())
        code, first = self.run_cli("--reuse-from", str(start))
        self.assertEqual(code, 0)
        self.assertEqual(self.reads(), 1)
        code, again = self.run_cli("--reuse-from", str(start))
        self.assertEqual(self.reads(), 1)
        self.assertEqual(again["until"], first["until"])
        self.assertEqual([p["name"] for p in again["projects"]], ["tool"])

    def test_an_older_read_is_not_reused(self):
        self.run_cli("--reuse-from", str(int(time.time())))
        self.run_cli("--reuse-from", str(int(time.time()) + 3600))
        self.assertEqual(self.reads(), 2)

    def test_an_unreadable_cache_is_read_again(self):
        cache.cache_dir().mkdir(parents=True)
        (cache.cache_dir() / cache.NAME).write_text("{not json")
        code, _ = self.run_cli("--reuse-from", "0")
        self.assertEqual((code, self.reads()), (0, 1))

    def test_a_machine_not_reached_is_kept_in_the_read(self):
        self.fleet.unreachable("crate")
        start = str(int(time.time()))
        self.assertEqual(self.run_cli("--reuse-from", start)[0], 1)
        code, data = self.run_cli("--reuse-from", start)
        self.assertEqual(code, 1)
        self.assertFalse(next(m for m in data["machines"] if m["label"] == "crate")["reached"])

    def test_callers_that_come_together_share_one_read(self):
        self.fleet.commit(self.fleet.repo("bench", "Projects/tool"), "First")
        argv = [sys.executable, str(COMMAND), "--reuse-from", str(int(time.time())), "--json"]
        procs = [subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(3)]
        outs = [p.communicate(timeout=60)[0] for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0, 0])
        self.assertEqual(self.reads(), 1)
        self.assertEqual(len({json.loads(o)["until"] for o in outs}), 1)

    def test_it_reads_only_the_last_7_days(self):
        for argv in (["--reuse-from", "0", "--since", "2w"], ["--reuse-from", "0", "status"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as e:
                cli.main(argv)
            self.assertEqual(e.exception.code, 2)
