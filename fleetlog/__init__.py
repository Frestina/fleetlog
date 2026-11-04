from pathlib import Path

# The checkout, or the plugin's folder, and the command in it.
ROOT = Path(__file__).resolve().parent.parent
COMMAND = ROOT / "bin" / "fleetlog"
