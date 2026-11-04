import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.fleet import FleetTest

ROOT = Path(__file__).resolve().parent.parent


class PluginFolderTest(FleetTest):
    def test_a_run_writes_no_bytecode_into_the_plugin_folder(self):
        # A fresh install, as `omarchy plugin add` leaves it: no __pycache__.
        plugin = self.fleet.root / "plugin"
        skip = shutil.ignore_patterns("__pycache__", "*.pyc")
        for part in ("bin", "fleetlog"):
            shutil.copytree(ROOT / part, plugin / part, ignore=skip, symlinks=True)
        self.fleet.commit(self.fleet.repo("anvil", "Projects/tool"), "First")
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
        for argv in (["--json"], ["--json", "--reuse-from", "0"], ["--help"]):
            run = subprocess.run([sys.executable, str(plugin / "bin" / "fleetlog"), *argv],
                                 stdin=subprocess.DEVNULL, capture_output=True, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(sorted(str(p.relative_to(plugin)) for p in plugin.rglob("*")
                                if p.name == "__pycache__" or p.suffix == ".pyc"), [])
